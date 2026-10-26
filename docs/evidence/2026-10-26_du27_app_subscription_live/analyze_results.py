"""Analyze retained live subscription artifacts without starting any service."""
from pathlib import Path
from collections import Counter, defaultdict
from bisect import bisect_right
from datetime import datetime, timezone
import argparse
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
args = parser.parse_args()
HERE = args.dummy_dir.resolve()
SERVICE = args.service_dir.resolve() if args.service_dir else Path((HERE / 'service-directory.txt').read_text().strip())
OUTPUT = args.output_dir.resolve() if args.output_dir else HERE
OUTPUT.mkdir(parents=True, exist_ok=True)


def read_jsonl(path):
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def dist(values):
    values = sorted(values)
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
reports = [m for m in messages if m['type'] == 'kpm_report']
source = read_jsonl(SERVICE / 'source.jsonl')
inputs = read_jsonl(SERVICE / 'inputs.ndjson')
source_by_seq = {r['report']['sequence']: r for r in source}
input_by_seq = {r['source_indication_seq']: r for r in inputs if r['kind'] == 'kpm_report'}
cutoff = int(registration['cutoff_at_mono_us'])
ack_received = int(registration['dummy_received_at_mono_us'])
end_received = int(unregistered['dummy_received_at_mono_us'])
expected = {r['report']['sequence'] for r in source if cutoff < int(r['callback_at_mono_us']) < end_received}
assert len(source_by_seq) == len(source)
assert [int(r['delivery_seq']) for r in reports] == list(range(1, len(reports) + 1))
assert len({r['report_seq'] for r in reports}) == len(reports)
assert {int(r['report_seq']) for r in reports} == expected
text = (HERE / 'bindings.txt').read_text()
blocks = text.split('subscription=')[1:]
assert len(blocks) == len(reports)
metrics = registration['metric_names']
assert len(metrics) == 27
core_inputs = sorted([r for r in inputs if r['kind'] == 'core_snapshot'], key=lambda r: int(r['received_at_mono_us']))
core_times = [int(r['received_at_mono_us']) for r in core_inputs]
timing, by_du, metric_stats = defaultdict(list), defaultdict(list), {}
real_checks = 0
core_ages = []
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
    raw_rows = [r for r in raw['rows'] if r['ue'] == record['row']['ue'] and r['sample_idx'] == record['row']['sample_idx']]
    assert len(raw_rows) == 1
    raw_metrics = raw_rows[0]['metrics']
    assert set(raw_metrics) == set(metrics)
    header = dict(re.findall(r'(\w+)=([^ ]+)', block.splitlines()[0]))
    assert header['report_seq'] == message['report_seq']
    assert header['delivery_seq'] == message['delivery_seq']
    assert header['link_id'] == message['link_id']
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
    assert message['broker_instance_id'] == registration['broker_instance_id']
    assert message['subscription_id'] == registration['subscription_id']
    for name, elapsed in [('callback_to_receive_ms', receive-callback), ('push_ms', receive-ready),
                          ('matching_ms', ready-callback), ('publishing_ms', publish-ready),
                          ('queue_and_socket_ms', receive-publish),
                          ('receipt_to_txt_ms', int(message['dummy_written_at_mono_us'])-receive)]:
        timing[name].append(elapsed / 1000)
    b = record['binding']
    core = core_inputs[bisect_right(core_times, ready)-1]
    core_ages.append((ready-int(core['received_at_mono_us']))/1000)
    amf = [u for u in core['amf'] if u['supi'] == b['supi']]
    smf = [p for u in core['smf'] if u['supi'] == b['supi'] for p in u['pdu']
           if str(p['psi']) == b['pdu_session_id'] and p['dnn'] == b['dnn'] and p.get('ipv4') == record['ue_ipv4']]
    assert len(amf) == len(smf) == 1
    assert str(amf[0]['gnb']['amf_ue_ngap_id']) == b['amf_ue_ngap_id']
    assert str(amf[0]['gnb']['ran_ue_ngap_id']) == b['ran_ue_ngap_id']
    assert str(amf[0]['gnb']['gnb_id']) == record['node']['gnb_id']
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
        # RF and MAC getters do not promise a synchronized common sample set.
        if a in ('UL.MCS', 'DL.MCS'):
            assert different == 0

log = (SERVICE / 'xapp.log').read_text()
windows = {}
for index in range(4):
    batch = [r for r in reports if index*30 <=
             (int(r['dummy_received_at_mono_us'])-ack_received)/1e6 < (index+1)*30]
    push = [(int(r['dummy_received_at_mono_us'])-int(r['report_ready_at_mono_us']))/1000 for r in batch]
    windows[f'{index*30}-{(index+1)*30}s'] = {'reports': len(batch), 'push_ms': dist(push)}
summary = {
    'analyzed_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'passed',
    'scope': 'Retained 120-second live E2-to-one-local-dummy run; no new live experiment.',
    'registration_to_unregister_ack_s': (end_received-ack_received)/1e6,
    'message_counts': dict(Counter(m['type'] for m in messages)),
    'source_reports_over_whole_service_lifetime': len(source),
    'source_reports_by_subscription_window': {
        'before_registration': sum(int(r['callback_at_mono_us']) <= cutoff for r in source),
        'during_registration': len(expected),
        'after_unregister_ack': sum(int(r['callback_at_mono_us']) >= end_received for r in source)},
    'eligible_source_reports_after_registration_before_unregister_ack': len(expected),
    'complete_payload_comparisons': len(reports), 'raw_metric_values_compared': len(reports)*27,
    'real_value_bit_comparisons': real_checks, 'txt_reports_compared': len(blocks),
    'delivery_sequence_contiguous': True, 'all_eligible_source_reports_received': True,
    'core_context_cross_checks': len(reports), 'core_snapshot_age_at_ready_ms': dist(core_ages),
    'timing_ms': {k: dist(v) for k,v in timing.items()}, 'per_du': per_du,
    'latency_by_30s_window': windows,
    'metric_statistics': metric_stats,
    'ingress_drop_values': sorted({r.get('ingress_dropped_total') for r in inputs if r['kind']=='kpm_report'}),
    'input_event_counts': dict(Counter(r['kind'] for r in inputs)),
    'shutdown': {'subscription_delete_responses': log.count('E42 SUBSCRIPTION DELETE RESPONSE rx'),
                 'late_indication_registry_warning_count': log.count('Spuriosly can happen.'),
                 'warning_context': 'Registry lookup failure is in SDK indication handler after delete responses; exact race not reproduced.'},
    'limitations': ['No Laptop truth or iperf receiver artifacts in these directories.',
                    'No app reconnect, UE reconnect, slow-client or 30-minute live acceptance in this run.',
                    'Latency starts at collector callback or report-ready, not at PHY sampling.',
                    'Registration occurred after mapping was already established; no cold-start mapping latency measurement.',
                    'Source membership and context IDs did not change within the subscription window.'],
    'sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
               [HERE/'receipts.jsonl', HERE/'bindings.txt', SERVICE/'source.jsonl', SERVICE/'inputs.ndjson', SERVICE/'xapp.log']}}
(OUTPUT / 'analysis.json').write_text(json.dumps(summary, indent=2) + '\n')

os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='falcon-live-analysis-mpl-', dir='/tmp'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig, axes = plt.subplots(2, 2, figsize=(12, 7.5), constrained_layout=True)
for name, label in [('push_ms','Report ready to receive'), ('callback_to_receive_ms','Collector callback to receive')]:
    vals = sorted(timing[name])
    axes[0,0].plot(vals, [(i+1)*100/len(vals) for i in range(len(vals))], label=label)
axes[0,0].set(xlabel='Latency (ms)', ylabel='Cumulative reports (%)', title='A. Local delivery latency')
axes[0,0].axhline(99, color='0.6', ls='--', lw=.8)
axes[0,0].legend(fontsize=8)
for du, batch in sorted(by_du.items()):
    x=[(int(r['dummy_received_at_mono_us'])-ack_received)/1e6 for r in batch]
    interval=[(int(b['dummy_received_at_mono_us'])-int(a['dummy_received_at_mono_us']))/1000 for a,b in zip(batch,batch[1:])]
    axes[0,1].plot(x[1:],interval,lw=.6,alpha=.8,label=f'DU{du}')
    axes[1,1].plot(x,[r['report']['row']['metrics']['UL.MAC.Throughput']['value']/1000 for r in batch],lw=.8,label=f'DU{du}')
axes[0,1].axhline(100,color='0.4',ls='--',lw=.8)
axes[0,1].set(xlabel='Seconds after registration acknowledgment',ylabel='Interval (ms)',title='B. Per-link receipt cadence')
axes[0,1].legend()
x=[(int(r['dummy_received_at_mono_us'])-ack_received)/1e6 for r in reports]
axes[1,0].scatter(x,timing['callback_to_receive_ms'],s=3,alpha=.55,label='Callback to receive')
axes[1,0].scatter(x,timing['push_ms'],s=3,alpha=.65,label='Ready to receive')
axes[1,0].set(xlabel='Seconds after registration acknowledgment',ylabel='Latency (ms)',title='C. Delivery latency over time')
axes[1,0].legend(fontsize=8)
axes[1,1].set(xlabel='Seconds after registration acknowledgment',ylabel='UL MAC throughput (Mbit/s)',title='D. Received KPM activity (not iperf goodput)')
axes[1,1].legend()
for ax in axes.flat:
    ax.grid(alpha=.2)
fig.suptitle('120-second live E2 subscription: two DUs, one dummy, 2,400 reports')
fig.savefig(OUTPUT/'latency-and-cadence.png',dpi=180)
plt.close(fig)
print(json.dumps({k:v for k,v in summary.items() if k not in ('metric_statistics','sha256')},indent=2))
