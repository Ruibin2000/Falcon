#!/usr/bin/env python3
"""Exercise migration sequencing with fake privileged/network commands only."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['SUBNET_MOCK_DIR'])
state_file = root/'state.json'
state = json.loads(state_file.read_text())
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
if name == 'sudo':
    with (root/'operations.jsonl').open('a') as out:
        out.write(json.dumps(args)+'\n')
    if args == ['-v']: sys.exit(0)
    name, args = args[0], args[1:]
mode = os.environ.get('SUBNET_MOCK_FAILURE', '')
if name == 'install':
    if mode == 'install': sys.exit(42)
    state['installed'].append(args[-1])
elif name == 'systemctl':
    if args[0] == 'stop':
        for unit in args[1:]: state['units'][unit] = False
    elif args[0] == 'start':
        state['units'][args[1]] = not (mode == 'smf-inactive' and args[1] == 'open5gs-smfd')
    elif args[0] == 'is-active':
        active = state['units'][args[1]]
        print('active' if active else 'inactive')
        if not active: sys.exit(3)
    else: raise RuntimeError(args)
elif name == 'docker':
    if 'SUBNET_ACTION=apply' in args:
        if mode != 'wrong-dnn': state['dnn'] = 'internet2'
        print('UE2 DNN changed: internet -> internet2')
    else:
        print('UE1: internet / IPv4; UE2: '+state['dnn']+' / IPv4')
elif name == 'ip':
    if '-j' in args:
        if 'addr' in args:
            print(json.dumps([{'ifname':'ogstun','mtu':1400,'flags':['UP'],
                'addr_info':[{'local':addr,'prefixlen':16} for addr in state['addresses']]}]))
        else:
            print(json.dumps([{'dst':'default'}]+[{'dst':addr.rsplit('.',1)[0]+'.0/16'} for addr in state['addresses']]))
    elif 'add' in args:
        state['addresses'].append('10.46.0.1')
    elif 'link' in args:
        pass
    elif 'addr' in args:
        print('\n'.join('7: ogstun inet '+addr+'/16' for addr in state['addresses']))
    else:
        print(args[-1]+' dev ogstun')
else:
    raise RuntimeError('Unexpected mocked command: '+name+' '+repr(args))
state_file.write_text(json.dumps(state))
'''


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='falcon-subnets-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        inputs = self.root/'inputs'
        inputs.mkdir()
        pools = [{'subnet':'10.45.0.0/16','gateway':'10.45.0.1'},
                 {'subnet':'2001:db8:cafe::/48','gateway':'2001:db8:cafe::1'}]
        for role in ('smf', 'upf'):
            (inputs/(role+'.yaml')).write_text(yaml.safe_dump(
                {role:{'session':pools,'metrics':{'server':[{'address':'127.0.0.7'}]}}}, sort_keys=False))
        (inputs/'99-open5gs.network').write_text('[Match]\nName=ogstun\n\n[Network]\nAddress=10.45.0.1/16\n')
        self.bundle = self.root/'bundle'
        subprocess.run(['python3',str(REPO/'scripts/dual_fr1/prepare_dual_subnets.py'),
                        '--smf',str(inputs/'smf.yaml'),'--upf',str(inputs/'upf.yaml'),
                        '--network',str(inputs/'99-open5gs.network'),'--output-dir',str(self.bundle)],
                       check=True, capture_output=True, text=True)
        binaries = self.root/'bin'
        binaries.mkdir()
        for name in ('sudo','ip','systemctl'):
            script = binaries/name
            script.write_text(MOCK)
            script.chmod(0o755)
        (self.root/'state.json').write_text(json.dumps({'dnn':'internet','addresses':['10.45.0.1'],
            'installed':[],'units':{'open5gs-upfd':True,'open5gs-smfd':True}}))
        self.env = dict(os.environ, PATH=str(binaries)+os.pathsep+os.environ['PATH'],
                        SUBNET_MOCK_DIR=str(self.root), PYTHONDONTWRITEBYTECODE='1')

    def run_apply(self, failure=''):
        return subprocess.run(['bash',str(REPO/'scripts/dual_fr1/apply_dual_subnets.sh'),str(self.bundle)],
                              env=dict(self.env,SUBNET_MOCK_FAILURE=failure), capture_output=True, text=True)

    def operations(self):
        log = self.root/'operations.jsonl'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def test_success_changes_only_intended_core_components(self):
        result = self.run_apply()
        self.assertEqual(result.returncode,0,result.stderr)
        state = json.loads((self.root/'state.json').read_text())
        self.assertEqual(state['dnn'],'internet2')
        self.assertEqual(state['addresses'],['10.45.0.1','10.46.0.1'])
        self.assertEqual(state['installed'],['/etc/open5gs/smf.yaml','/etc/open5gs/upf.yaml',
                                           '/etc/systemd/network/99-open5gs.network'])
        stops = [args for args in self.operations() if args[:2] == ['systemctl','stop']]
        self.assertEqual(stops,[['systemctl','stop','open5gs-smfd','open5gs-upfd']])
        self.assertTrue(all(state['units'].values()))
        self.assertIn('Core migration completed',result.stdout)

    def test_changed_prepared_file_stops_before_privileged_actions(self):
        target = self.bundle/'prepared/upf.yaml'
        target.write_text(target.read_text().replace('gateway: 10.46.0.1','gateway: 10.46.0.99'))
        self.assertNotEqual(self.run_apply().returncode,0)
        self.assertEqual(self.operations(),[])

    def test_changed_source_stops_before_privileged_actions(self):
        target = self.root/'inputs/smf.yaml'
        target.write_text(target.read_text()+'# changed after preparation\n')
        self.assertNotEqual(self.run_apply().returncode,0)
        self.assertEqual(self.operations(),[])

    def test_install_failure_prevents_later_address_changes_and_restart(self):
        result = self.run_apply('install')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('STOP: migration failed',result.stderr)
        self.assertFalse(any(args[:2] == ['systemctl','start'] for args in self.operations()))
        self.assertFalse(any(args[:4] == ['ip','-4','addr','add'] for args in self.operations()))

    def test_one_inactive_service_prevents_success_claim(self):
        result = self.run_apply('smf-inactive')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('Core migration completed',result.stdout)

    def test_wrong_final_dnn_prevents_success_claim(self):
        result = self.run_apply('wrong-dnn')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('Core migration completed',result.stdout)


if __name__ == '__main__':
    unittest.main()
