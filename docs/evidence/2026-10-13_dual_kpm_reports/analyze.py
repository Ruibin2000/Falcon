#!/usr/bin/env python3
"""Retain and analyze the two completed Spark KPM captures using operator inputs."""
import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import tempfile
from zoneinfo import ZoneInfo

os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='falcon-kpm-mpl-', dir='/tmp'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path('/home/nyu/Desktop/Falcon_repo/Falcon/docs/evidence/2026-10-13_dual_kpm_reports')
TZ = ZoneInfo('America/New_York')
METRICS = ('DRB.RlcSduDelayDl', 'DRB.UEThpDl', 'DRB.UEThpUl', 'RRU.PrbTotDl', 'RRU.PrbTotUl')
RUNS = ('falcon-dual-kpm.X95e8zHm', 'falcon-dual-kpm.0B8F17Sp')

def iso(unix_us):
    return datetime.fromtimestamp(unix_us / 1e6, TZ).isoformat()

def stats(values):
    if not values:
        return None
    return dict(count=len(values), min=min(values), mean=statistics.mean(values),
                median=statistics.median(values), p95=float(np.percentile(values, 95)), max=max(values))

def parse(path):
    rows, callbacks, current, row = [], [], None, None
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if line.startswith('FALCON_KPM_NODE '):
            values = dict(re.findall(r'(\w+)=(\S+)', line))
            current = dict(unix_us=int(values['unix_us']), gnb_id=int(values['gnb_id']),
                           du_id=int(values['du_id']), ran_type=values['ran_type'], source_line=number)
            callbacks.append(current)
            row = None
        elif current is not None:
            age = re.search(r'report_age_us = (-?\d+)', line)
            if age:
                current['report_age_us'] = int(age[1])
            ue = re.search(r'UE ID type = gNB-DU, gnb_cu_ue_f1ap = (\d+)', line)
            if ue:
                row = dict(current, f1ap_ue_id=int(ue[1]), unreliable=False, metrics={})
                rows.append(row)
            metric = re.fullmatch(r'([A-Za-z0-9.]+) = (-?\d+(?:\.\d+)?)', line)
            if metric and row is not None and metric[1] in METRICS:
                assert metric[1] not in row['metrics'], 'Unindexed multiple records require a richer decoder'
                row['metrics'][metric[1]] = float(metric[2])
            if line == 'Measurement Record not reliable' and row is not None:
                row['unreliable'] = True
    assert len(rows) == len(callbacks), 'Expected one UE record per observed callback'
    assert all(r['gnb_id'] == 411 and r['ran_type'] == 'ngran_gNB_DU' for r in rows)
    assert {r['du_id'] for r in rows} == {1, 2}
    assert {(r['du_id'], r['f1ap_ue_id']) for r in rows} == {(1, 11), (2, 7)}
    return rows

ROOT.mkdir(parents=True, exist_ok=True)
inputs = json.loads((ROOT / 'operator_inputs.json').read_text())
clock = inputs['simultaneous_clock_readback']
offset = (datetime.fromisoformat(clock['spark']) - datetime.fromisoformat(clock['laptop'])).total_seconds()
assert 190 < offset < 210
laptop = inputs['laptop_summary']
corrected_start = datetime.fromisoformat(laptop['started_at']) + timedelta(seconds=offset)
corrected_end = datetime.fromisoformat(laptop['ended_at']) + timedelta(seconds=offset)
start_us, end_us = int(corrected_start.timestamp() * 1e6), int(corrected_end.timestamp() * 1e6)
summary = dict(recorded_at=datetime.now(TZ).isoformat(),
               status='Concurrent TCP UL functionality and simultaneous two-DU UE KPM observed; full Plan 3 acceptance pending',
               source='Spark raw KPM/RIC logs; selected CU/PUSCH observations; operator-provided laptop transcript and simultaneous clock readbacks',
               clock=dict(estimated_spark_minus_laptop_seconds=offset, precision='Approximate manually simultaneous readbacks; not a calibrated clock measurement',
                          corrected_laptop_start=corrected_start.isoformat(), corrected_laptop_end=corrected_end.isoformat()),
               application=dict(source_directory='/tmp/falcon-dual-ul-iakb3ttb', source='Operator transcript, selected fields normalized',
                                status=laptop['status'], links=inputs['application_results'],
                                sum_of_reported_receiver_mean_mbps=31.1), runs=[])

all_rows = []
for index, dirname in enumerate(RUNS, 1):
    target = ROOT / f'run-{index:02d}'
    target.mkdir(exist_ok=True)
    origin = Path('/tmp') / dirname
    for name in ('kpm.log', 'start.txt', 'end.txt', 'exit.txt'):
        shutil.copy2(origin / name, target / name)
    rows = parse(target / 'kpm.log')
    all_rows.append(rows)
    log = (target / 'kpm.log').read_text()
    lifecycle = dict(subscriptions=log.count('[xApp]: SUBSCRIPTION RESPONSE rx'),
                     deletion_responses=log.count('[xApp]: E42 SUBSCRIPTION DELETE RESPONSE rx'),
                     success_marker='Test xApp run SUCCESSFULLY' in log,
                     normal_stop='[xApp]: Sucessfully stopped' in log,
                     pipeline_exit=int((target / 'exit.txt').read_text().split('=')[1]))
    assert lifecycle['subscriptions'] == lifecycle['deletion_responses'] == 2
    assert lifecycle['pipeline_exit'] == 0 and lifecycle['success_marker'] and lifecycle['normal_stop']
    run = dict(source_directory=str(origin), start=(target / 'start.txt').read_text().strip(),
               end=(target / 'end.txt').read_text().strip(), lifecycle=lifecycle,
               kpm_sha256=hashlib.sha256((target / 'kpm.log').read_bytes()).hexdigest(), links=[])
    for du in (1, 2):
        selected = [r for r in rows if r['du_id'] == du]
        active = [r for r in selected if r['metrics'].get('DRB.UEThpUl', 0) > 0]
        complete = [r for r in active if all(k in r['metrics'] for k in METRICS) and not r['unreliable']]
        intervals = [(b['unix_us'] - a['unix_us']) / 1e6 for a, b in zip(selected, selected[1:])]
        link = dict(du_id=du, f1ap_ue_id=selected[0]['f1ap_ue_id'], callbacks=len(selected),
                    ul_positive_rows=len(active), complete_five_metric_ul_positive_rows=len(complete),
                    missing_metric_rows={m: sum(m not in r['metrics'] for r in selected) for m in METRICS},
                    unreliable_rows=sum(r['unreliable'] for r in selected),
                    ul_active_start=iso(active[0]['unix_us']), ul_active_end=iso(active[-1]['unix_us']),
                    ul_mbps_active_samples=stats([r['metrics']['DRB.UEThpUl'] / 1000 for r in active]),
                    ul_prb_percent_active_samples=stats([r['metrics']['RRU.PrbTotUl'] for r in active]),
                    rlc_dl_delay_ms_active_samples=stats([r['metrics']['DRB.RlcSduDelayDl'] / 10 for r in active if 'DRB.RlcSduDelayDl' in r['metrics']]),
                    report_age_us=stats([r['report_age_us'] for r in selected]), callback_gap_seconds=stats(intervals),
                    gaps_over_1_5_seconds=sum(g > 1.5 for g in intervals))
        if index == 2:
            link['complete_ul_rows_in_clock_corrected_laptop_window'] = sum(start_us <= r['unix_us'] <= end_us for r in complete)
        reported = inputs['server_interval_mbps'][str(du)]
        count = min(len(active), len(reported))
        link['relative_profile_comparison'] = dict(method='Pair first positive KPM report and first server interval, without shifting or fitting',
            samples=count, pearson_r=float(np.corrcoef([r['metrics']['DRB.UEThpUl'] / 1000 for r in active[:count]], reported[:count])[0, 1]))
        run['links'].append(link)
    by_du = {du: [r for r in rows if r['du_id'] == du] for du in (1, 2)}
    used, pairs = set(), []
    for row1 in by_du[1]:
        candidates = [(abs(row1['unix_us'] - row2['unix_us']), j, row2) for j, row2 in enumerate(by_du[2]) if j not in used]
        distance, j, row2 = min(candidates)
        if distance <= 50_000:
            used.add(j)
            if all(all(m in r['metrics'] for m in METRICS) and r['metrics']['DRB.UEThpUl'] > 0 and not r['unreliable'] for r in (row1, row2)):
                pairs.append((row1, row2))
    run['simultaneous_complete_ul_pairs'] = dict(count=len(pairs), matching_tolerance_us=50_000,
        first=iso(min(r['unix_us'] for r in pairs[0])), last=iso(max(r['unix_us'] for r in pairs[-1])))
    assert all(link['complete_five_metric_ul_positive_rows'] >= 30 for link in run['links'])
    assert len(pairs) >= 30
    summary['runs'].append(run)
    with (target / 'rows.csv').open('w', newline='') as stream:
        fields = ['unix_us', 'time_edt', 'gnb_id', 'du_id', 'f1ap_ue_id', 'report_age_us', 'unreliable', *METRICS]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: row[k] for k in fields if k in row}, 'time_edt': iso(row['unix_us']), **row['metrics']})

pusch = []
for du, dirname, rnti in ((1, 'falcon-du1-3660.0BgECAjI', '0x460c'), (2, 'falcon-du2-3600.K2QXgUiY', '0x4608')):
    path = Path('/tmp') / dirname / 'du.log'
    records, buckets = [], defaultdict(list)
    with path.open(errors='replace') as stream:
        for line in stream:
            if not '2026-10-14T02:17:26' <= line[:19] < '2026-10-14T02:18:29' or 'PUSCH:' not in line or f'rnti={rnti} ' not in line:
                continue
            values = dict(re.findall(r'\b(mod|rv|tbs|crc|sinr)=([^\s]+)', line))
            assert all(k in values for k in ('mod', 'rv', 'tbs', 'crc', 'sinr'))
            values['sinr'] = float(values['sinr'].removesuffix('dB'))
            values['tbs'] = int(values['tbs'])
            records.append(values)
            buckets[line[:19]].append(values)
    result = dict(du_id=du, rnti=rnti, source_file=str(path), window_utc=['2026-10-14T02:17:26+00:00', '2026-10-14T02:18:29+00:00'],
        end_exclusive=True, pusch_attempts=len(records), crc=dict(Counter(r['crc'] for r in records)),
        crc_failed_attempt_percent=100 * sum(r['crc'] != 'OK' for r in records) / len(records),
        modulation_counts=dict(Counter(r['mod'] for r in records)), rv_counts=dict(Counter(r['rv'] for r in records)),
        sinr_db=stats([r['sinr'] for r in records]), tbs_bytes=stats([r['tbs'] for r in records]))
    pusch.append(result)
    for timestamp, selected in sorted(buckets.items()):
        result.setdefault('per_second', []).append(dict(utc=timestamp + '+00:00', attempts=len(selected),
            crc_ok=sum(r['crc'] == 'OK' for r in selected), crc_ko=sum(r['crc'] != 'OK' for r in selected),
            crc_failed_attempt_percent=100 * sum(r['crc'] != 'OK' for r in selected) / len(selected),
            sinr_mean_db=statistics.mean(r['sinr'] for r in selected)))
summary['phy_observations'] = pusch
summary['units'] = dict(throughput='DRB.UEThpUl: kbps; plotted as decimal Mbit/s', prb='RRU.PrbTotUl: percent',
    rlc_dl_delay='DRB.RlcSduDelayDl: 0.1 ms, converted by /10', report_age='Microseconds; processing/queues/clock offset included, not application RTT')
summary['notes'] = [
    'The latest capture matches the clock-corrected operator UL window and UE1 rate profile (r about 0.96); precise synchronization remains unverified.',
    'Missing idle DRB.RlcSduDelayDl values are left blank, never changed to zero; this monitor does not explicitly print noValue records.',
    'Additional positive KPM reports can outlast the application process due to measurement aggregation and queued traffic.',
    'PUSCH CRC failure is measured over logged decoding attempts, not TCP packet loss or a calibrated first-transmission BLER.',
    'Normal xApp cleanup did not reproduce the earlier RIC deletion-failure abort; the failure-path bug was not repaired by this analysis.',
    'CU confirms (DU1, F1AP11, PCI1, rnti460c) and (DU2, F1AP7, PCI2, rnti4608); direct modem/SIM-to-F1AP correlation is not carried in KPM.',
    'Full repeated solo/concurrent, UDP, deliberate guard/survivor and cold-start acceptance is pending; underflow remediation is deferred.'
]
summary['pending'] = ['Precisely synchronized host timestamps', 'Complete cross-layer modem/SIM/cell/F1AP/bearer ledger',
    'Three same-condition solo/concurrent repetitions and remaining UDP/guard/survivor/cold-start gates']
shutil.copy2('/tmp/falcon-dual-ric.VVGsduP3/ric.log', ROOT / 'ric.log')
(ROOT / 'manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
if Path(__file__).resolve() != (ROOT / 'analyze.py').resolve():
    shutil.copy2(__file__, ROOT / 'analyze.py')

fig, axes = plt.subplots(2, 1, figsize=(11, 6.7), sharex=True, constrained_layout=True)
colors = {1: '#2563eb', 2: '#d97706'}
for du in (1, 2):
    selected = [r for r in all_rows[-1] if r['du_id'] == du]
    times = [(r['unix_us'] - start_us) / 1e6 for r in selected]
    axes[0].plot(times, [r['metrics']['DRB.UEThpUl'] / 1000 for r in selected], color=colors[du], label=f'DU{du} / F1AP UE {selected[0]["f1ap_ue_id"]}')
    observed = pusch[du - 1]['per_second']
    seconds = [(datetime.fromisoformat(r['utc']).timestamp() - corrected_start.timestamp()) for r in observed]
    axes[1].plot(seconds, [r['crc_failed_attempt_percent'] for r in observed], color=colors[du], label=f'DU{du}')
for ax in axes:
    ax.axvspan(0, (corrected_end - corrected_start).total_seconds(), color='#94a3b8', alpha=0.13, label='Approx. clock-corrected UL window')
    ax.grid(alpha=0.25)
    ax.legend(loc='upper right', fontsize=8)
axes[0].set_ylabel('KPM UL throughput (Mbit/s)')
axes[0].set_ylim(bottom=0)
axes[1].set_ylabel('PUSCH CRC failed attempts (%)')
axes[1].set_ylim(bottom=0)
axes[1].set_xlabel('Seconds from estimated UL launch on Spark (22:17:25.532 EDT)')
axes[1].set_xlim(-5, 72)
fig.suptitle('Dual DU uplink: 2026-10-13 latest capture\nKPM/RLC throughput and logged PUSCH decoding attempts')
fig.savefig(ROOT / 'dual_ul_kpm.png', dpi=180)
fig.savefig(ROOT / 'dual_ul_kpm.svg')
plt.close(fig)
with (ROOT / 'phy_per_second.csv').open('w', newline='') as stream:
    fields = ['du_id', 'rnti', 'utc', 'attempts', 'crc_ok', 'crc_ko', 'crc_failed_attempt_percent', 'sinr_mean_db']
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for link in pusch:
        for row in link['per_second']:
            writer.writerow(dict(du_id=link['du_id'], rnti=link['rnti'], **row))
summary['files'] = {str(path.relative_to(ROOT)): {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in sorted(ROOT.rglob('*')) if path.is_file() and path.name != 'manifest.json'}
(ROOT / 'manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({'clock': summary['clock'], 'latest_links': summary['runs'][-1]['links'],
                  'latest_pairs': summary['runs'][-1]['simultaneous_complete_ul_pairs'],
                  'phy_crc_percent': {r['du_id']: r['crc_failed_attempt_percent'] for r in pusch}}, indent=2))
