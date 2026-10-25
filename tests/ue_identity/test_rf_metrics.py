"""RF extension compatibility with main's existing identity mapper and formatter."""

import copy
import unittest

from test_identity import core_event, cu_event, du_event, ingest, ready, config
from mapping import Mapper
from text_report import format_record


def rf_event(du=1, stamp=12_000_000, rsrp=-13.125, snr=21.75):
    event = du_event(du, stamp=stamp)
    event['rows'][0]['metrics'].update({
        'PUSCH.RSRP.dBFS': {'type': 'no_value' if rsrp is None else 'real', 'value': rsrp},
        'PUSCH.SNR.dB': {'type': 'no_value' if snr is None else 'real', 'value': snr},
    })
    return event


class RFCompatibilityTests(unittest.TestCase):
    def test_100ms_du_reports_reuse_fresh_1s_identity_and_follow_current_ip(self):
        mapper = ready()
        outputs = []
        for tick in range(100):
            stamp = 12_000_000 + tick * 100_000
            if tick % 10 == 0:
                core = core_event()
                core['received_at_us'] = stamp
                if tick >= 50:
                    core['smf'][0]['pdu'][0]['ipv4'] = '10.45.0.11'
                ingest(mapper, core)
                cu = cu_event()
                cu.update(received_at_us=stamp + 1_000, header_time_us=str(stamp))
                ingest(mapper, cu)
            for du in (1, 2):
                event = rf_event(du, stamp=stamp + 2_000, rsrp=-13.125 - tick / 100)
                event['received_at_us'] = stamp + 3_000
                event['rows'][0]['granularity_ms'] = 100
                row = ingest(mapper, event)[0]
                self.assertEqual(row['binding_status'], 'matched')
                expected = '10.45.0.11' if du == 1 and tick >= 50 else f'10.{44 + du}.0.10'
                self.assertEqual(row['ue_ipv4'], expected)
                self.assertEqual(row['row']['granularity_ms'], 100)
                self.assertEqual(row['row']['metrics']['PUSCH.RSRP.dBFS']['value'], -13.125 - tick / 100)
                outputs.append(row)
        self.assertEqual(len(outputs), 200)

    def test_both_du_bindings_preserve_seven_metrics_and_input_ownership(self):
        mapper = ready()
        for du, ip in [(1, '10.45.0.10'), (2, '10.46.0.10')]:
            event = rf_event(du)
            original = copy.deepcopy(event)
            result = ingest(mapper, event)[0]
            self.assertEqual((result['binding_status'], result['ue_ipv4']), ('matched', ip))
            self.assertEqual(result['node']['du_id'], str(du))
            metrics = result['row']['metrics']
            self.assertEqual(len(metrics), 7)
            self.assertEqual(metrics['PUSCH.RSRP.dBFS'],
                             {'type': 'real', 'value': -13.125, 'unit': 'dBFS'})
            self.assertEqual(metrics['PUSCH.SNR.dB'],
                             {'type': 'real', 'value': 21.75, 'unit': 'dB'})
            self.assertEqual(event, original)

    def test_measured_zero_and_no_value_remain_distinct(self):
        for rsrp, snr in [(0.0, 0.0), (None, None), (-13.125, None), (None, 0.0)]:
            with self.subTest(rsrp=rsrp, snr=snr):
                result = ingest(ready(), rf_event(rsrp=rsrp, snr=snr))[0]
                for name, value in [('PUSCH.RSRP.dBFS', rsrp), ('PUSCH.SNR.dB', snr)]:
                    metric = result['row']['metrics'][name]
                    self.assertEqual(metric['value'], value)
                    self.assertEqual(metric['type'], 'no_value' if value is None else 'real')

    def test_ip_change_updates_only_the_matching_du_binding(self):
        mapper = ready()
        event = core_event()
        event['received_at_us'] = 11_500_000
        event['smf'][0]['pdu'][0]['ipv4'] = '10.45.0.11'
        ingest(mapper, event)
        for du, ip in [(1, '10.45.0.11'), (2, '10.46.0.10')]:
            result = ingest(mapper, rf_event(du))[0]
            self.assertEqual(result['ue_ipv4'], ip)
            self.assertEqual(result['row']['metrics']['PUSCH.RSRP.dBFS']['value'], -13.125)

    def test_strict_scope_withholds_ip_and_preserves_rf_data(self):
        mapper = ready()
        mapper.config['du_scope_mode'] = 'strict'
        result = ingest(mapper, rf_event())[0]
        self.assertEqual(result['binding_status'], 'unresolved')
        self.assertIsNone(result['ue_ipv4'])
        self.assertEqual(result['row']['metrics']['PUSCH.SNR.dB']['unit'], 'dB')

    def test_missing_identity_does_not_fabricate_an_ip(self):
        mapper = Mapper(config())
        result = ingest(mapper, rf_event())[0]
        self.assertIsNone(result['ue_ipv4'])
        self.assertEqual(result['row']['metrics']['PUSCH.RSRP.dBFS']['value'], -13.125)

    def test_existing_text_formatter_exposes_new_names_without_aliases(self):
        result = ingest(ready(), rf_event())[0]
        text = format_record(result)
        self.assertIn('PUSCH.RSRP.dBFS = -13.125 [dBFS] (real)', text)
        self.assertIn('PUSCH.SNR.dB = 21.75 [dB] (real)', text)
        self.assertNotIn('FALCON.PUSCH.', text)


if __name__ == '__main__':
    unittest.main()
