"""Verify and plot the retained six-minute live KPM subscription experiment."""
from pathlib import Path
from collections import Counter, defaultdict
from bisect import bisect_right
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import argparse
import csv
import hashlib
import json
import math
import os
import re
import statistics
import struct
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dummy-dir', type=Path, default=Path(__file__).resolve().parent)
parser.add_argument('--service-dir', type=Path)
parser.add_argument('--output-dir', type=Path)
parser.add_argument('--traffic-dir', type=Path)
args = parser.parse_args()
HERE = args.dummy_dir.resolve()
SERVICE = args.service_dir.resolve() if args.service_dir else Path((HERE / 'service-directory.txt').read_text().strip())
OUTPUT = args.output_dir.resolve() if args.output_dir else HERE
OUTPUT.mkdir(parents=True, exist_ok=True)
TRAFFIC = args.traffic_dir.resolve() if args.traffic_dir else SERVICE.parent / 'traffic'


def read_jsonl(path):
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def dist(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    return {'count': len(values), 'min': values[0], 'mean': statistics.mean(values),
            **{f'p{p}': values[math.ceil(len(values) * p / 100) - 1] for p in (50, 95, 99)},
            'max': values[-1]}


def bits(value):
    return struct.pack('>d', value).hex()


messages = read_jsonl(HERE / 'receipts.jsonl')
registration = messages[0]
unregistered = messages[-1]
assert registration['type'] == 'registration_status'
assert unregistered['type'] == 'unregistration_status'
assert registration['status'] == 'registered' and unregistered['status'] == 'unregistered'
assert registration['data_source'] == 'e2' and registration['metric_profile'] == 'du27_bound_v1'
assert registration['version'] == 2 and registration['report_period_ms'] == 100
assert registration['filter'] == {'mode': 'all_matched_links'}
reports = [m for m in messages if m['type'] == 'kpm_report']
source = read_jsonl(SERVICE / 'source.jsonl')
inputs = read_jsonl(SERVICE / 'inputs.ndjson')
source_by_seq = {r['report']['sequence']: r for r in source}
input_by_seq = {r['source_indication_seq']: r for r in inputs if r['kind'] == 'kpm_report'}
cutoff = int(registration['cutoff_at_mono_us'])
ack_received = int(registration['dummy_received_at_mono_us'])
end_received = int(unregistered['dummy_received_at_mono_us'])
start_unix = int(registration['dummy_received_at_unix_us'])
duration = int((HERE / 'duration-seconds.txt').read_text())
assert duration == 360 and 360 <= (end_received-ack_received)/1e6 < 361
expected = {r['report']['sequence'] for r in source if cutoff < int(r['callback_at_mono_us']) < end_received}
assert len(source_by_seq) == len(source)
assert [int(r['delivery_seq']) for r in reports] == list(range(1, len(reports) + 1))
assert len({r['report_seq'] for r in reports}) == len(reports)
assert {int(r['report_seq']) for r in reports} == expected
raw_in_window = [r for r in inputs if r['kind'] == 'kpm_report'
                 and r['node']['node_type'] == 'ngran_gNB_DU'
                 and cutoff < int(r['callback_at_mono_us']) < end_received]
def row_key(event, row):
    return (event['source_instance_id'], event['source_indication_seq'],
            json.dumps(row['ue'], sort_keys=True), row['sample_idx'])
raw_keys = [row_key(event, row) for event in raw_in_window for row in event['rows']]
received_keys = [row_key(m['report'], m['report']['row']) for m in reports]
assert len(set(raw_keys)) == len(raw_keys) == len(reports) == 7200
assert set(raw_keys) == set(received_keys)
text = (HERE / 'bindings.txt').read_text()
blocks = text.split('subscription=')[1:]
assert len(blocks) == len(reports)
metrics = registration['metric_names']
assert len(metrics) == 27
core_inputs = sorted([r for r in inputs if r['kind'] == 'core_snapshot'], key=lambda r: int(r['received_at_mono_us']))
core_times = [int(r['received_at_mono_us']) for r in core_inputs]
cu_inputs = sorted([r for r in inputs if r['kind'] == 'kpm_report'
                    and r['node']['node_type'] != 'ngran_gNB_DU'],
                   key=lambda r: int(r['received_at_mono_us']))
cu_times = [int(r['received_at_mono_us']) for r in cu_inputs]
timing, by_du, metric_stats = defaultdict(list), defaultdict(list), {}
real_checks = 0
core_ages = []
cu_ages = []
for block, message in zip(blocks, reports):
    record = message['report']
    seq = int(message['report_seq'])
    original = source_by_seq[seq]
    assert json.dumps(original['report'], sort_keys=True) == json.dumps(record, sort_keys=True)
    assert original['ingress_admitted']
    assert record['binding_status'] == 'matched'
    assert set(record['row']['metrics']) == set(metrics)
    assert record['row']['granularity_ms'] == 100
    raw = input_by_seq[record['source_indication_seq']]
    assert raw['source_instance_id'] == record['source_instance_id']
    assert raw['node']['du_id'] == record['node']['du_id']
    assert raw['node']['gnb_id'] == record['node']['gnb_id']
    raw_rows = [r for r in raw['rows'] if r['ue'] == record['row']['ue'] and r['sample_idx'] == record['row']['sample_idx']]
    assert len(raw_rows) == 1
    raw_metrics = raw_rows[0]['metrics']
    assert set(raw_metrics) == set(metrics)
    header = dict(re.findall(r'(\w+)=([^ ]+)', block.splitlines()[0]))
    assert header['report_seq'] == message['report_seq']
    assert header['delivery_seq'] == message['delivery_seq']
    assert header['link_id'] == message['link_id']
    assert block.split(' ', 1)[0] == message['subscription_id']
    assert header['binding_revision'] == message['binding_revision']
    binding = record['binding']
    assert f"DU_ID={record['node']['du_id']} UE(gNB-CU UE F1AP ID)={record['row']['ue']['gnb_cu_ue_f1ap_id']}" in block
    assert f"SUPI={binding['supi']} AMF_UE_NGAP_ID={binding['amf_ue_ngap_id']} RAN_UE_NGAP_ID={binding['ran_ue_ngap_id']}" in block
    assert f"PDU_SESSION_ID={binding['pdu_session_id']}" in block
    assert f"serving_DU_ID={binding['serving_du_id']} CU_UE_index={binding['cu_ue_index']}" in block
    assert f"DNN={record['binding']['dnn']} UE_IPv4={record['ue_ipv4']}" in block
    text_metrics = {m.group(1): (m.group(2), m.group(3), m.group(4)) for m in
                    re.finditer(r'^    ([^\n]+?) = (.*?) \[(.*?)\] \((.*?)\)$', block, re.M)}
    for name, metric in record['row']['metrics'].items():
        assert raw_metrics[name]['type'] == metric['type']
        assert raw_metrics[name]['value'] == metric['value']
        value, unit, kind = text_metrics[name]
        assert (unit, kind) == (metric['unit'], metric['type'])
        if kind == 'real':
            assert bits(float(value)) == original['real_bits'][name] == bits(raw_metrics[name]['value'])
            real_checks += 1
        elif kind == 'integer':
            assert int(value) == metric['value']
        else:
            assert kind == 'no_value' and value == 'no_value' and metric['value'] is None
    callback, ready, publish, receive, until = [int(message[k]) for k in
        ('callback_at_mono_us', 'report_ready_at_mono_us', 'published_at_mono_us',
         'dummy_received_at_mono_us', 'valid_until_mono_us')]
    assert cutoff < callback <= ready <= publish <= receive < until
    assert callback == int(original['callback_at_mono_us']) == int(raw['callback_at_mono_us'])
    assert ready == int(original['report_ready_at_mono_us'])
    assert until == int(original['valid_until_mono_us'])
    assert message['broker_instance_id'] == registration['broker_instance_id']
    assert message['subscription_id'] == registration['subscription_id']
    assert message['version'] == 2 and message['data_source'] == 'e2'
    assert message['metric_profile'] == 'du27_bound_v1'
    for name, elapsed in [('callback_to_receive_ms', receive-callback), ('push_ms', receive-ready),
                          ('matching_ms', ready-callback), ('publishing_ms', publish-ready),
                          ('queue_and_socket_ms', receive-publish),
                          ('receipt_to_txt_ms', int(message['dummy_written_at_mono_us'])-receive)]:
        timing[name].append(elapsed / 1000)
    b = record['binding']
    core_index = bisect_right(core_times, ready)-1
    assert core_index >= 0
    core = core_inputs[core_index]
    core_ages.append((ready-int(core['received_at_mono_us']))/1000)
    amf = [u for u in core['amf'] if u['supi'] == b['supi']]
    smf = [p for u in core['smf'] if u['supi'] == b['supi'] for p in u['pdu']
           if str(p['psi']) == b['pdu_session_id'] and p['dnn'] == b['dnn'] and p.get('ipv4') == record['ue_ipv4']]
    assert len(amf) == len(smf) == 1
    assert str(amf[0]['gnb']['amf_ue_ngap_id']) == b['amf_ue_ngap_id']
    assert str(amf[0]['gnb']['ran_ue_ngap_id']) == b['ran_ue_ngap_id']
    assert str(amf[0]['gnb']['gnb_id']) == record['node']['gnb_id']
    cu_index = bisect_right(cu_times, ready)-1
    assert cu_index >= 0
    cu = cu_inputs[cu_index]
    cu_ages.append((ready-int(cu['received_at_mono_us']))/1000)
    contexts = [row for row in cu['rows']
                if row['ue']['amf_ue_ngap_id'] == b['amf_ue_ngap_id']
                and record['row']['ue']['gnb_cu_ue_f1ap_id'] in row['ue']['f1ap_ids']]
    assert len(contexts) == 1
    identity = contexts[0]['ue']
    allocation = int(identity['ran_ue_id_hex'], 16)
    assert allocation >> 28 == int(record['node']['du_id'])
    assert allocation & ((1 << 28)-1) == int(b['cu_ue_index']) == int(b['ran_ue_ngap_id'])
    assert [str(identity['guami'][k]) for k in
            ('mcc','mnc','amf_region_id','amf_set_id','amf_pointer')] == b['guami']
    assert contexts[0]['metrics']['FALCON.UE.RRCState']['value'] == 1
    by_du[record['node']['du_id']].append(message)

per_du = {}
for du, batch in sorted(by_du.items()):
    times = [int(r['dummy_received_at_mono_us']) for r in batch]
    intervals = [(b-a)/1000 for a,b in zip(times,times[1:])]
    headers = [int(r['report']['header_time_us']) for r in batch]
    first = batch[0]['report']
    b = first['binding']
    assert all(r['report']['binding'] == b for r in batch)
    assert all(r['report']['ue_ipv4'] == first['ue_ipv4'] for r in batch)
    per_du[du] = {'reports': len(batch), 'f1ap_id': first['row']['ue']['gnb_cu_ue_f1ap_id'],
                  'binding': b, 'link_id': batch[0]['link_id'],
                  'supi': b['supi'], 'ip': first['ue_ipv4'], 'dnn': b['dnn'],
                  'binding_revisions': dict(Counter(r['binding_revision'] for r in batch)),
                  'first_receipt_after_registration_ack_ms': (times[0]-ack_received)/1000,
                  'first_to_last_receipt_s': (times[-1]-times[0])/1e6,
                  'rate_per_second_from_intervals': (len(times)-1)/((times[-1]-times[0])/1e6),
                  'interval_ms': dist(intervals), 'gaps_above_150_ms': sum(x>150 for x in intervals),
                  'header_interval_ms': dist([(b-a)/1000 for a,b in zip(headers,headers[1:])])}
    per_metric = {}
    for name in metrics:
        values = [r['report']['row']['metrics'][name] for r in batch]
        nums = [m['value'] for m in values if m['type'] != 'no_value']
        per_metric[name] = {'no_value': len(values)-len(nums), 'numeric': len(nums),
                            'unit': values[0]['unit'], 'values': dist(nums) if nums else None}
    metric_stats[du] = per_metric
    high = [r for r in batch if r['report']['row']['metrics']['UL.MAC.Throughput']['value'] > 1000]
    per_du[du]['ul_mac_above_1_mbit_s'] = {
        'samples': len(high),
        'first_s_after_registration': (int(high[0]['dummy_received_at_mono_us'])-ack_received)/1e6,
        'last_s_after_registration': (int(high[-1]['dummy_received_at_mono_us'])-ack_received)/1e6}
    per_du[du]['traffic_details'] = {
        'mean_ul_mac_mbit_s_above_threshold': statistics.mean(
            r['report']['row']['metrics']['UL.MAC.Throughput']['value']/1000 for r in high),
        'rf_no_value_in_high_traffic': sum(
            r['report']['row']['metrics']['PUSCH.SNR.dB']['type'] == 'no_value' for r in high)}
    per_du[du]['sample_availability_comparison'] = {}
    for a, sampled in [('PUSCH.SNR.dB', 'UL.MCS.Samples'), ('UL.MCS', 'UL.MCS.Samples'), ('DL.MCS', 'DL.MCS.Samples')]:
        different = sum((r['report']['row']['metrics'][a]['type'] == 'no_value') !=
                        (r['report']['row']['metrics'][sampled]['value'] == 0) for r in batch)
        per_du[du]['sample_availability_comparison'][f'{a} vs {sampled}'] = different
        # Availability differences are source observations, not delivery errors.

log = (SERVICE / 'xapp.log').read_text()
windows = {}
for index in range(duration//30):
    batch = [r for r in reports if index*30 <=
             (int(r['dummy_received_at_mono_us'])-ack_received)/1e6 < (index+1)*30]
    push = [(int(r['dummy_received_at_mono_us'])-int(r['report_ready_at_mono_us']))/1000 for r in batch]
    windows[f'{index*30}-{(index+1)*30}s'] = {
        'reports': len(batch), 'push_ms': dist(push),
        'callback_to_receive_ms': dist([(int(r['dummy_received_at_mono_us'])-int(r['callback_at_mono_us']))/1000 for r in batch])}
assert all(window['reports'] == 600 for window in windows.values())
dummy_summary = json.loads((HERE/'summary.json').read_text())
publisher = json.loads((SERVICE/'publisher.json').read_text())
assert dummy_summary['status'] == publisher['status'] == 'passed'
assert dummy_summary['reports_received'] == dummy_summary['text_reports_written'] == len(reports)
assert dummy_summary['unregistered'] and not dummy_summary['interrupted']
assert (HERE/'exit.txt').read_text().strip() == 'dummy exit=0'
assert (SERVICE/'exit.txt').read_text().strip() == 'xApp exit=0'
assert not publisher['failures'] and not publisher['counters']['failed']
for key in ('active_connections','active_registrations','ingress_depth','ingress_bytes'):
    assert publisher['counters'][key] == 0
assert publisher['counters']['reports_queued'] == len(reports)
assert publisher['counters']['frames_queued'] == len(messages)
assert publisher['counters']['matched_reports'] == len(source)
for key in ('ingress_dropped','invalid_reports','expired_reports','lifecycle_log_errors'):
    assert publisher['counters'].get(key, 0) == 0
for name, expected_dist in dummy_summary['timing'].items():
    actual = dist(timing[name])
    for key, value in expected_dist.items():
        assert actual[key] == value, (name,key,actual[key],value)
for du, batch in by_du.items():
    actual = per_du[du]['interval_ms']
    for key, value in dummy_summary['per_link_interval_ms'][batch[0]['link_id']].items():
        assert actual[key] == value
assert log.count('E42 SUBSCRIPTION DELETE RESPONSE rx') == 3
lifecycle = [json.loads(line.partition(' ')[2]) for line in log.splitlines()
             if line.startswith('APP_')]
assert len([e for e in lifecycle if e.get('acknowledgement') == 'queued' and e.get('request_id') == 'reg-1']) == 1
assert lifecycle[-1]['reason'] == 'drained' and lifecycle[-1]['active_registrations'] == 0
assert all(int(r.get('ingress_dropped_total', 0)) == 0 for r in inputs if r['kind'] == 'kpm_report')
assert all(int(r['ingress_dropped_total']) == 0 for r in reports)
assert dist(timing['push_ms'])['p95'] <= 10 and dist(timing['push_ms'])['p99'] <= 25
assert dist(timing['push_ms'])['max'] <= 100 and dist(timing['callback_to_receive_ms'])['p99'] <= 100

def parse_server(du):
    sessions, current = [], None
    for line in (TRAFFIC/f'du{du}-server.log').read_text().splitlines():
        stamp, _, body = line.partition(' ')
        unix = datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()
        offset = unix-start_unix/1e6
        if 'Accepted connection from ' in body:
            assert current is None
            current = {'du': du, 'accepted_utc': stamp,
                       'source_ip': re.search(r'Accepted connection from ([^,]+)',body).group(1),
                       'interval_samples': []}
        if current is None:
            continue
        if ' connected to ' in body:
            current.update(data_connection_utc=stamp, start_s=offset)
        match = re.search(r'\[\s*\d+\]\s+([\d.]+)-([\d.]+)\s+sec\s+([\d.]+)\s+(\w+Bytes)\s+([\d.]+)\s+([KMG]?)bits/sec\s*(receiver)?', body)
        if match:
            lo,hi,amount,unit,rate,prefix,receiver = match.groups()
            value = float(rate)*{'':1e-6,'K':1e-3,'M':1,'G':1000}[prefix]
            if receiver:
                current.update(end_s=offset, end_utc=stamp, duration_s=float(hi)-float(lo),
                               transfer=f'{amount} {unit}', receiver_mbit_s=value)
                sessions.append(current)
                current = None
            else:
                current['interval_samples'].append({'end_s': offset, 'receiver_mbit_s': value})
    assert current is None and len(sessions) == 4
    assert all(s['source_ip'] == per_du[du]['ip'] for s in sessions)
    return sessions

sessions = {du: parse_server(du) for du in ('1','2')}
phase_members = [[sessions['1'][0]], [sessions['2'][0]],
                 [sessions['1'][1],sessions['2'][1]], [sessions['1'][2]],
                 [sessions['2'][2]], [sessions['1'][3],sessions['2'][3]]]
phases = []
for index, members in enumerate(phase_members,1):
    lo,hi = min(s['start_s'] for s in members), max(s['end_s'] for s in members)
    assert 0 < lo < hi < duration
    batch = [r for r in reports if lo <= (int(r['dummy_received_at_mono_us'])-ack_received)/1e6 < hi]
    phases.append({'phase': index, 'active_du': [s['du'] for s in members],
                   'start_s': lo, 'end_s': hi, 'reports': len(batch),
                   'push_ms': dist([(int(r['dummy_received_at_mono_us'])-int(r['report_ready_at_mono_us']))/1000 for r in batch]),
                   'callback_to_receive_ms': dist([(int(r['dummy_received_at_mono_us'])-int(r['callback_at_mono_us']))/1000 for r in batch]),
                   'receiver_sessions': [{k:v for k,v in s.items() if k!='interval_samples'} for s in members]})
summary = {
    'analyzed_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'passed',
    'scope': '360-second live E2-to-one-local-dummy run with alternating and concurrent uplink traffic.',
    'registration_received_utc': datetime.fromtimestamp(start_unix/1e6,timezone.utc).isoformat(),
    'unregistration_received_utc': datetime.fromtimestamp(int(unregistered['dummy_received_at_unix_us'])/1e6,timezone.utc).isoformat(),
    'registration_to_unregister_ack_s': (end_received-ack_received)/1e6,
    'message_counts': dict(Counter(m['type'] for m in messages)),
    'source_reports_over_whole_service_lifetime': len(source),
    'raw_du_rows_in_subscription_window': len(raw_keys),
    'all_raw_du_rows_in_window_received': True,
    'source_reports_by_subscription_window': {
        'before_registration': sum(int(r['callback_at_mono_us']) <= cutoff for r in source),
        'during_registration': len(expected),
        'after_unregister_ack': sum(int(r['callback_at_mono_us']) >= end_received for r in source)},
    'eligible_source_reports_after_registration_before_unregister_ack': len(expected),
    'complete_payload_comparisons': len(reports), 'raw_metric_values_compared': len(reports)*27,
    'real_value_bit_comparisons': real_checks, 'txt_reports_compared': len(blocks),
    'delivery_sequence_contiguous': True, 'all_eligible_source_reports_received': True,
    'core_context_cross_checks': len(reports), 'core_snapshot_age_at_ready_ms': dist(core_ages),
    'cu_context_cross_checks': len(reports), 'cu_snapshot_age_at_ready_ms': dist(cu_ages),
    'timing_ms': {k: dist(v) for k,v in timing.items()}, 'per_du': per_du,
    'latency_by_30s_window': windows,
    'metric_statistics': metric_stats,
    'traffic_phases': phases,
    'traffic_time_precision': 'Receiver log timestamps have one-second resolution; phase boundaries are approximate.',
    'publisher_summary': publisher, 'dummy_summary': dummy_summary,
    'ingress_drop_values': sorted({r.get('ingress_dropped_total') for r in inputs if r['kind']=='kpm_report'}),
    'input_event_counts': dict(Counter(r['kind'] for r in inputs)),
    'shutdown': {'subscription_delete_responses': log.count('E42 SUBSCRIPTION DELETE RESPONSE rx'),
                 'late_indication_registry_warning_count': log.count('Spuriosly can happen.'),
                 'xapp_exit': 0, 'dummy_exit': 0,
                 'warning_lines': [line for line in log.splitlines() if re.search(r'warning|error|Spuriosly|not found',line,re.I)]},
    'limitations': ['No current-run Laptop truth, phase client JSON or reconnect watcher records were supplied; receiver sessions establish the observed traffic workload.',
                    'No app reconnect, UE reconnect, slow-client or 30-minute live acceptance in this run.',
                    'Latency starts at collector callback or report-ready, not at PHY sampling.',
                    'Registration occurred after mapping was already established; no cold-start mapping latency measurement.',
                    'Source membership and context IDs did not change within the subscription window.'],
    'sha256': {str(p.parent.name+'/'+p.name): hashlib.sha256(p.read_bytes()).hexdigest() for p in
               [HERE/'receipts.jsonl', HERE/'bindings.txt', HERE/'summary.json', SERVICE/'source.jsonl', SERVICE/'inputs.ndjson', SERVICE/'xapp.log', SERVICE/'publisher.json', TRAFFIC/'du1-server.log', TRAFFIC/'du2-server.log']}}
(OUTPUT / 'analysis.json').write_text(json.dumps(summary, indent=2) + '\n')

os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='falcon-live-analysis-mpl-', dir='/tmp'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.size': 10, 'axes.titlesize': 11,
                     'svg.fonttype': 'none', 'savefig.facecolor': 'white'})
colors = {'1': '#2463a6', '2': '#d56a22'}
phase_colors = {'1': '#2463a6', '2': '#d56a22', 'both': '#8172b2'}
elapsed = lambda r: (int(r['dummy_received_at_mono_us'])-ack_received)/1e6
times_by_du = {du: [elapsed(r) for r in batch] for du,batch in by_du.items()}

def shade_phases(ax, labels=False):
    for p in phases:
        key = p['active_du'][0] if len(p['active_du']) == 1 else 'both'
        ax.axvspan(p['start_s'],p['end_s'],color=phase_colors[key],alpha=.07,zorder=0)
        if labels:
            ax.text((p['start_s']+p['end_s'])/2,.97,f"P{p['phase']}",
                    transform=ax.get_xaxis_transform(),ha='center',va='top',fontsize=8)

def save_plot(fig, name):
    for extension in ('png','svg'):
        fig.savefig(OUTPUT/f'{name}.{extension}',dpi=180)
    plt.close(fig)

interval_by_delivery = {}
for batch in by_du.values():
    for a,b in zip(batch,batch[1:]):
        interval_by_delivery[b['delivery_seq']] = (int(b['dummy_received_at_mono_us'])-int(a['dummy_received_at_mono_us']))/1000
with (OUTPUT/'delivery-timeseries.csv').open('w',newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['delivery_seq','report_seq','du_id','ue_ipv4','binding_revision',
                     'seconds_after_registration_ack','callback_to_receive_ms','ready_to_receive_ms',
                     'callback_to_ready_ms','ready_to_enqueue_ms','enqueue_to_receive_ms',
                     'receive_to_txt_ms','link_receive_interval_ms'])
    for i,r in enumerate(reports):
        writer.writerow([r['delivery_seq'],r['report_seq'],r['report']['node']['du_id'],
                         r['report']['ue_ipv4'],r['binding_revision'],f'{elapsed(r):.6f}',
                         *[timing[k][i] for k in ('callback_to_receive_ms','push_ms','matching_ms',
                                                   'publishing_ms','queue_and_socket_ms','receipt_to_txt_ms')],
                         interval_by_delivery.get(r['delivery_seq'],'')])
with (OUTPUT/'metric-statistics.csv').open('w',newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['du_id','metric','unit','numeric','no_value','min','mean','p50','p95','p99','max'])
    for du,stats in sorted(metric_stats.items()):
        for name,item in stats.items():
            values = item['values'] or {}
            writer.writerow([du,name,item['unit'],item['numeric'],item['no_value'],
                             *[values.get(k,'') for k in ('min','mean','p50','p95','p99','max')]])

fig, axes = plt.subplots(2,2,figsize=(13,8),layout='constrained')
for name, label in [('push_ms','Report ready to receive'), ('callback_to_receive_ms','Collector callback to receive')]:
    vals = sorted(timing[name])
    axes[0,0].plot(vals,[(i+1)*100/len(vals) for i in range(len(vals))],
                   label=f"{label} (p99 {dist(vals)['p99']:.3f} ms)")
axes[0,0].set(xlabel='Latency (ms)', ylabel='Cumulative reports (%)', title='A. Local delivery latency')
axes[0,0].axhline(99, color='0.6', ls='--', lw=.8)
axes[0,0].legend(fontsize=8,loc='lower right')
x = [elapsed(r) for r in reports]
axes[0,1].scatter(x,timing['callback_to_receive_ms'],s=3,alpha=.3,
                  color='#697a87',label='Callback to receive',rasterized=True)
axes[0,1].scatter(x,timing['push_ms'],s=3,alpha=.45,
                  color='#2463a6',label='Ready to receive',rasterized=True)
axes[0,1].plot([i*30+15 for i in range(12)],
               [w['push_ms']['p99'] for w in windows.values()],
               'o-',color='#b03650',ms=3,lw=1.1,label='Ready to receive p99 per 30 s')
shade_phases(axes[0,1],labels=True)
axes[0,1].set(xlabel='Seconds after registration acknowledgement',ylabel='Latency (ms)',
              title='B. Delivery throughout the workload',xlim=(0,360))
axes[0,1].legend(fontsize=8,loc='upper left',bbox_to_anchor=(0,.91))
counts_by_10s = {}
for du, batch in sorted(by_du.items()):
    t = times_by_du[du]
    intervals = [interval_by_delivery[r['delivery_seq']] for r in batch[1:]]
    axes[1,0].plot(t[1:],intervals,lw=.6,alpha=.8,color=colors[du],label=f'DU{du}')
    counts = [sum(lo <= sec < lo+10 for sec in t) for lo in range(0,360,10)]
    assert counts == [100]*36
    counts_by_10s[du] = counts
    offset = -2 if du == '1' else 2
    axes[1,1].bar([lo+5+offset for lo in range(0,360,10)],counts,width=3.8,
                  color=colors[du],alpha=.8,label=f'DU{du}')
axes[1,0].axhline(100,color='0.3',ls='--',lw=.8)
axes[1,0].set(xlabel='Seconds after registration acknowledgement',ylabel='Receive interval (ms)',
              title='C. Per-link reporting cadence',xlim=(0,360))
axes[1,0].legend(fontsize=8)
axes[1,1].set(xlabel='Seconds after registration acknowledgement',ylabel='Reports per 10 s',
              title='D. Exactly 100 reports per DU in every 10 s bin',xlim=(0,360),ylim=(0,120))
axes[1,1].legend(fontsize=8)
for ax in axes.flat:
    ax.grid(alpha=.2)
fig.suptitle('Six minute live E2 delivery: two DUs, one dummy, 7,200 reports',fontsize=14)
save_plot(fig,'delivery-stability')

fig,axes = plt.subplots(3,2,figsize=(13,10),sharex=True,layout='constrained')
for col,(du,batch) in enumerate(sorted(by_du.items())):
    t = times_by_du[du]
    mac = [r['report']['row']['metrics']['UL.MAC.Throughput']['value']/1000 for r in batch]
    axes[0,col].plot(t,mac,lw=.5,color=colors[du],alpha=.3,label='UL MAC KPM (100 ms)')
    bins = defaultdict(list)
    for sec,value in zip(t,mac): bins[int(sec)].append(value)
    axes[0,col].plot([s+.5 for s in sorted(bins)],
                     [statistics.mean(bins[s]) for s in sorted(bins)],
                     lw=1,color=colors[du],label='UL MAC KPM (1 s mean)')
    for i,session in enumerate(sessions[du]):
        samples = session['interval_samples']
        axes[0,col].plot([p['end_s'] for p in samples],
                         [p['receiver_mbit_s'] for p in samples],
                         ls='--',lw=1,color='0.15',alpha=.85,
                         label='iperf receiver interval' if i == 0 else None)
    axes[0,col].set(title=f"DU{du}: {per_du[du]['ip']}",ylabel='Uplink throughput (Mbit/s)')
    for row,name,unit in [(1,'PUSCH.SNR.dB','PUSCH SNR (dB)'),
                           (2,'PRB.UsageUl.Percent','UL PRB utilization (%)')]:
        values = [r['report']['row']['metrics'][name]['value'] for r in batch]
        axes[row,col].plot(t,[v if v is not None else math.nan for v in values],
                           lw=.65,color=colors[du])
        axes[row,col].set(ylabel=unit)
    for row in range(3):
        shade_phases(axes[row,col],labels=row == 0)
        axes[row,col].grid(alpha=.2)
        axes[row,col].set_xlim(0,360)
    axes[2,col].set_xlabel('Seconds after registration acknowledgement')
axes[0,0].legend(fontsize=8,loc='upper right',bbox_to_anchor=(1,.90))
fig.suptitle('Alternating and concurrent uplink activity during KPM delivery\n'
             'P1 UE1 | P2 UE2 | P3 both | P4 UE1 | P5 UE2 | P6 both',fontsize=13)
save_plot(fig,'traffic-and-radio')

# Match the earlier 27-KPM report's separate UL and DL overview row order.
ul_rows = [
    ('PUSCH.SNR.dB', 'PUSCH SNR\n(dB)', 1, False),
    ('PUSCH.RSRP.dBFS', 'PUSCH RSRP\n(dBFS)', 1, False),
    ('UL.CRC.FailureRatio', 'UL CRC NOK\n(%, derived)', 1, True),
    ('UL.PHR.dB', 'UL PHR\n(dB)', 1, False),
    ('UL.MCS', 'UL MCS\n(index)', 1, False),
    ('PRB.UsageUl.Percent', 'UL PRB use\n(%, REAL)', 1, False),
    ('UL.BSR.Bytes', 'UL BSR\n(kB, latest report)', .001, False),
]
dl_rows = [
    ('DL.MAC.Throughput', 'DL MAC rate\n(Mbit/s)', .001, False),
    ('CQI', 'DL CQI\n(index)', 1, False),
    ('DL.MCS', 'DL MCS\n(index)', 1, False),
    ('PRB.UsageDl.Percent', 'DL PRB use\n(%, REAL)', 1, False),
    ('DL.Buffer.Bytes', 'DL buffer\n(bytes, latest)', 1, False),
    ('DRB.RlcSduDelayDl', 'DL RLC SDU delay\n(ms)', .1, False),
    ('DL.HARQ.FailureRatio', 'DL HARQ NOK\n(%, derived)', 1, True),
]
derived_checks = 0
for message in reports:
    record = message['report']
    for prefix in ('UL.CRC', 'DL.HARQ'):
        ok = record['row']['metrics'][prefix+'.Ok']['value']
        nok = record['row']['metrics'][prefix+'.Nok']['value']
        actual = record['derived_metrics'][prefix+'.FailureRatio']['value']
        if ok+nok:
            assert actual is not None and math.isclose(actual,100*nok/(ok+nok),rel_tol=1e-12,abs_tol=1e-12)
        else:
            assert actual is None
        derived_checks += 1

start_local = datetime.fromtimestamp(start_unix/1e6,ZoneInfo('America/New_York'))
overview_xlabel = f'Seconds after registration acknowledgement | {start_local:%Y-%m-%d %H:%M:%S %Z}'

def decorate_overview(ax, phase_labels=False):
    for phase in phases:
        key = phase['active_du'][0] if len(phase['active_du']) == 1 else 'both'
        color = {'1':'#dceaf7','2':'#fce8d4','both':'#dcefe3'}[key]
        ax.axvspan(phase['start_s'],phase['end_s'],color=color,alpha=.65,zorder=0)
        if phase_labels:
            label = f"{phase['phase']}: "+({'1':'UE1','2':'UE2','both':'BOTH'}[key])
            ax.text((phase['start_s']+phase['end_s'])/2,1.02,label,
                    ha='center',va='bottom',transform=ax.get_xaxis_transform(),fontsize=8)
    ax.set_xlim(0,360)
    ax.set_xticks(range(0,361,60))
    ax.grid(axis='y',alpha=.22)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

def plot_overview_paths(ax, name, ylabel, scale=1, derived=False):
    for du,batch in sorted(by_du.items()):
        field = 'derived_metrics' if derived else None
        values = [(r['report'][field] if field else r['report']['row']['metrics'])[name]['value']
                  for r in batch]
        ax.plot(times_by_du[du],[v*scale if v is not None else math.nan for v in values],
                color=colors[du],lw=.55,alpha=.8,label=f'DU{du} / UE{du}')
        isolated = [i for i,v in enumerate(values) if v is not None
                    and (i == 0 or values[i-1] is None)
                    and (i == len(values)-1 or values[i+1] is None)]
        ax.plot([times_by_du[du][i] for i in isolated],[values[i]*scale for i in isolated],
                '.',color=colors[du],ms=2,alpha=.8)
    ax.set_ylabel(ylabel)
    ax.legend(loc='lower left',ncol=2,fontsize=8,frameon=False)
    if derived:
        ax.set_ylim(-2,102)

fig,axes = plt.subplots(2+len(ul_rows),1,figsize=(14,21),sharex=True,layout='constrained')
for index,(du,batch) in enumerate(sorted(by_du.items())):
    ax = axes[index]
    bins = defaultdict(list)
    for t,r in zip(times_by_du[du],batch):
        value = r['report']['row']['metrics']['UL.MAC.Throughput']['value']
        if value is not None:
            bins[int(t)].append(value/1000)
    ax.plot([sec+.5 for sec in sorted(bins)],[statistics.mean(bins[sec]) for sec in sorted(bins)],
            color=colors[du],lw=1.2,label='DU UL MAC throughput (1 s mean)')
    for i,session in enumerate(sessions[du]):
        samples = session['interval_samples']
        ax.plot([p['end_s'] for p in samples],[p['receiver_mbit_s'] for p in samples],
                color='#1f2328',ls='--',lw=1,
                label='iperf3 receiver goodput (~1 s)' if i == 0 else None)
    ax.set_ylabel(f'DU{du} / UE{du}\nUL (Mbit/s)')
    ax.set_ylim(bottom=-.5)
    ax.legend(loc='upper left',ncol=2,fontsize=8,frameon=False)
for ax,row in zip(axes[2:],ul_rows):
    plot_overview_paths(ax,*row)
for index,ax in enumerate(axes):
    decorate_overview(ax,phase_labels=index == 0)
axes[-1].set_xlabel(overview_xlabel)
fig.suptitle('Uplink traffic and main DU metrics received by the dummy over six minutes\n'
             'Traffic rows: solid = DU MAC, dashed = iperf3 receiver | metric rows: 100 ms',fontsize=14)
save_plot(fig,'uplink-overview')

fig,axes = plt.subplots(len(dl_rows),1,figsize=(14,16.5),sharex=True,layout='constrained')
for index,(ax,row) in enumerate(zip(axes,dl_rows)):
    plot_overview_paths(ax,*row)
    decorate_overview(ax,phase_labels=index == 0)
axes[-1].set_xlabel(overview_xlabel)
fig.suptitle('Main downlink metrics received by the dummy during the uplink experiment\n'
             'Blue = DU1 / UE1; orange = DU2 / UE2; phase shading follows the UL workload',fontsize=14)
save_plot(fig,'downlink-overview')

for page in range(3):
    fig,axes = plt.subplots(3,3,figsize=(14,9),sharex=True,layout='constrained')
    for ax,name in zip(axes.flat,metrics[page*9:(page+1)*9]):
        for du,batch in sorted(by_du.items()):
            values = [r['report']['row']['metrics'][name]['value'] for r in batch]
            ax.plot(times_by_du[du],[v if v is not None else math.nan for v in values],
                    color=colors[du],lw=.6,alpha=.8,label=f'DU{du}')
            isolated = [i for i,v in enumerate(values) if v is not None
                        and (i == 0 or values[i-1] is None)
                        and (i == len(values)-1 or values[i+1] is None)]
            ax.plot([times_by_du[du][i] for i in isolated],[values[i] for i in isolated],
                    '.',color=colors[du],ms=2,alpha=.8)
        ax.set(title=name,ylabel=metric_stats['1'][name]['unit'],xlim=(0,360))
        ax.ticklabel_format(axis='y',style='plain',useOffset=False)
        ax.grid(alpha=.2)
    for ax in axes[-1]: ax.set_xlabel('Seconds after registration acknowledgement')
    axes[0,0].legend(fontsize=8)
    fig.suptitle(f'Received raw KPM metrics {page*9+1} to {(page+1)*9} of 27\n'
                 'Gaps represent no_value; numeric zero is retained',fontsize=13)
    save_plot(fig,f'metrics-{page*9+1:02d}-{(page+1)*9:02d}')

summary['reports_by_10s_window_per_du'] = counts_by_10s
summary['overview_rows'] = {'uplink':2+len(ul_rows),'downlink':len(dl_rows)}
summary['overview_order'] = {'uplink':['DU1 UL','DU2 UL']+[row[0] for row in ul_rows],
                             'downlink':[row[0] for row in dl_rows]}
summary['derived_metric_comparisons'] = derived_checks
summary['plot_files'] = [f'{name}.{ext}' for name in
                         ('delivery-stability','traffic-and-radio','uplink-overview',
                          'downlink-overview','metrics-01-09',
                          'metrics-10-18','metrics-19-27') for ext in ('png','svg')]
(OUTPUT/'analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ('status','complete_payload_comparisons',
                 'raw_du_rows_in_subscription_window','raw_metric_values_compared',
                 'real_value_bit_comparisons','timing_ms','shutdown')},indent=2))
