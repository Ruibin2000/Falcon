"""Default RF and explicit legacy profile compatibility without live services."""

import contextlib
import io
import os
from pathlib import Path
import re
import subprocess
import unittest
from unittest import mock

from test_identity import ROOT
import xapp_ue_identity as app
from metrics import EXPANDED


COLLECTOR = Path(os.environ.get('FALCON_IDENTITY_COLLECTOR', '/tmp/falcon-xapp-ue-identity'))
BASE_METRICS = ['DRB.RlcSduDelayDl', 'DRB.UEThpDl', 'DRB.UEThpUl', 'RRU.PrbTotDl', 'RRU.PrbTotUl']


class ProfileSelectionTests(unittest.TestCase):
    def selected(self, *arguments):
        selected = []

        def run(args, config, mapper, capture, report):
            selected.append(args.e2_config)
            return 0

        with mock.patch('sys.argv', ['xapp_ue_identity.py', *arguments]), mock.patch.object(app, 'run', run):
            self.assertEqual(app.main(), 0)
        return selected[0]

    def test_existing_command_now_selects_seven_metric_default(self):
        self.assertEqual(self.selected(), ROOT / 'configs/flexric/xapp_ue_identity.conf')

    def test_explicit_seven_selects_the_same_default(self):
        self.assertEqual(self.selected('--du-metrics', '7'), self.selected())

    def test_legacy_five_selects_complete_backup_profile(self):
        self.assertEqual(self.selected('--du-metrics', '5'),
                         ROOT / 'configs/flexric/xapp_ue_identity_five.conf')

    def test_expanded_profile_requires_explicit_selection(self):
        self.assertEqual(self.selected('--du-metrics', '27'),
                         ROOT / 'configs/flexric/xapp_ue_identity_expanded.conf')

    def test_custom_e2_configuration_keeps_its_existing_override(self):
        self.assertEqual(self.selected('--e2-config', '/tmp/custom-e2.conf'), Path('/tmp/custom-e2.conf'))

    def test_custom_configuration_and_profile_cannot_silently_override_each_other(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.selected('--e2-config', '/tmp/custom-e2.conf', '--du-metrics', '5')
        self.assertEqual(raised.exception.code, 2)

    def test_invalid_profile_fails_before_runtime_start(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.selected('--du-metrics', '6')
        self.assertEqual(raised.exception.code, 2)


@unittest.skipUnless(COLLECTOR.is_file(), 'build the standalone collector first')
class ProfileCodecTests(unittest.TestCase):
    def test_sdk_parses_all_27_expanded_names_with_100ms_du_and_1s_cu(self):
        result = subprocess.run([str(COLLECTOR), '--check-config',
                                 str(ROOT / 'configs/flexric/xapp_ue_identity_expanded.conf')],
                                capture_output=True, text=True, check=True, timeout=10)
        actions = {ran: names.split() for ran, names in
                   re.findall(r'RAN type (\S+), actions = ([^\n]+)', result.stdout)}
        self.assertEqual(actions['ngran_gNB_DU'], list(EXPANDED))
        periods = {ran: int(period) for period, ran in re.findall(
            r'Sub_ORAN_SM Name: KPM, Time: (\d+)\s+[^\n]*RAN type (\w+),', result.stdout)}
        self.assertEqual(periods['ngran_gNB_DU'], 100)
        for ran in ['ngran_gNB', 'ngran_gNB_CU', 'ngran_gNB_CUCP']:
            self.assertEqual(actions[ran], ['FALCON.UE.RRCState'])
            self.assertEqual(periods[ran], 1000)

    def test_real_sdk_parses_seven_default_and_five_backup_with_identical_cu_identity(self):
        profiles = []
        periods = []
        for name in ['xapp_ue_identity.conf', 'xapp_ue_identity_five.conf']:
            result = subprocess.run([str(COLLECTOR), '--check-config', str(ROOT / 'configs/flexric' / name)],
                                    capture_output=True, text=True, check=True, timeout=10)
            profiles.append({ran: actions.split() for ran, actions in
                             re.findall(r'RAN type (\S+), actions = ([^\n]+)', result.stdout)})
            periods.append({ran: int(period) for period, ran in re.findall(
                r'Sub_ORAN_SM Name: KPM, Time: (\d+)\s+[^\n]*RAN type (\w+),', result.stdout)})
        seven, five = profiles
        self.assertEqual(seven['ngran_gNB_DU'], BASE_METRICS + ['PUSCH.RSRP.dBFS', 'PUSCH.SNR.dB'])
        self.assertEqual(five['ngran_gNB_DU'], BASE_METRICS)
        self.assertEqual(periods[0]['ngran_gNB_DU'], 100)
        self.assertEqual(periods[1]['ngran_gNB_DU'], 1000)
        for ran in ['ngran_gNB', 'ngran_gNB_CU', 'ngran_gNB_CUCP']:
            self.assertEqual(seven[ran], five[ran])
            self.assertEqual(seven[ran], ['FALCON.UE.RRCState'])
            self.assertEqual(periods[0][ran], 1000)
            self.assertEqual(periods[1][ran], 1000)


if __name__ == '__main__':
    unittest.main()
