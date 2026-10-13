#!/usr/bin/env bash
# Apply a reviewed first migration after the selected UE modems are disabled.
set -Eeuo pipefail

if [[ $# != 1 ]]; then
  printf 'Usage: bash %s /tmp/falcon-dual-subnets.BUNDLE\n' "$0" >&2
  exit 2
fi
TASK_SUBNET_BUNDLE=$(realpath -- "$1")
TASK_SUBNET_REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
trap 'printf "STOP: migration failed at line %s. Keep UEs disabled; inspect the output and use the migration rollback guide. Bundle: %s\n" "$LINENO" "$TASK_SUBNET_BUNDLE" >&2' ERR

printf 'Checking reviewed configuration and address allocation...\n'
python3 -B - "$TASK_SUBNET_BUNDLE" "$TASK_SUBNET_REPO" <<'PY'
import importlib.util
import ipaddress
import json
from pathlib import Path
import subprocess
import sys

bundle, repo = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location('preparer', repo / 'scripts/dual_fr1/prepare_dual_subnets.py')
preparer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparer)
for role in ('smf', 'upf'):
    original = (bundle / 'original' / (role + '.yaml')).read_text()
    if preparer.yaml.safe_load(original)[role]['session'] != preparer.OLD:
        raise SystemExit('STOP: this script requires the original first-migration pools')
    if (bundle / 'prepared' / (role + '.yaml')).read_text() != preparer.prepare_yaml(original, role):
        raise SystemExit('STOP: prepared ' + role + ' differs from the reviewed migration')
original_network = (bundle / 'original/99-open5gs.network').read_text()
if '10.46.' in original_network:
    raise SystemExit('STOP: original network file already contains a 10.46 allocation')
if (bundle / 'prepared/99-open5gs.network').read_text() != preparer.prepare_network(original_network):
    raise SystemExit('STOP: prepared network file differs from the reviewed migration')
subnet = ipaddress.IPv4Network('10.46.0.0/16')
addresses = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr', 'show']))
gateway_present = False
for interface in addresses:
    for address in interface.get('addr_info', []):
        value = ipaddress.IPv4Interface(address['local'] + '/' + str(address['prefixlen']))
        if value.network.overlaps(subnet):
            raise SystemExit('STOP: 10.46.0.0/16 overlaps an existing interface allocation')
        if interface['ifname'] == 'ogstun' and str(value) == '10.45.0.1/16':
            gateway_present = True
if not gateway_present:
    raise SystemExit('STOP: original ogstun 10.45.0.1/16 is missing')
routes = json.loads(subprocess.check_output(['ip', '-j', '-4', 'route', 'show', 'table', 'all']))
for route in routes:
    destination = route.get('dst', 'default')
    if destination != 'default' and ipaddress.IPv4Network(destination, strict=False).overlaps(subnet):
        raise SystemExit('STOP: 10.46.0.0/16 overlaps an existing route')
print('Prepared files and new subnet: OK')
PY
sha256sum -c "$TASK_SUBNET_BUNDLE/source.sha256"
sudo -v
sudo docker exec -i -e SUBNET_ACTION=check open5gs-mongo \
  mongosh --quiet --file /dev/stdin < "$TASK_SUBNET_REPO/scripts/dual_fr1/ue2_dnn.js"

printf 'Stopping SMF/UPF and applying the UE2 DNN and configuration...\n'
sudo systemctl stop open5gs-smfd open5gs-upfd
sudo docker exec -i -e SUBNET_ACTION=apply open5gs-mongo \
  mongosh --quiet --file /dev/stdin < "$TASK_SUBNET_REPO/scripts/dual_fr1/ue2_dnn.js"
sudo install -m 0644 "$TASK_SUBNET_BUNDLE/prepared/smf.yaml" /etc/open5gs/smf.yaml
sudo install -m 0644 "$TASK_SUBNET_BUNDLE/prepared/upf.yaml" /etc/open5gs/upf.yaml
sudo install -m 0644 "$TASK_SUBNET_BUNDLE/prepared/99-open5gs.network" /etc/systemd/network/99-open5gs.network
sudo ip -4 addr add 10.46.0.1/16 dev ogstun
sudo ip link set dev ogstun mtu 1400 up
sudo systemctl start open5gs-upfd
sudo systemctl start open5gs-smfd

printf 'Checking the migrated core...\n'
for task_subnet_unit in open5gs-upfd open5gs-smfd; do
  systemctl is-active "$task_subnet_unit"
done
TASK_SUBNET_STATUS=$(sudo docker exec -i -e SUBNET_ACTION=check open5gs-mongo \
  mongosh --quiet --file /dev/stdin < "$TASK_SUBNET_REPO/scripts/dual_fr1/ue2_dnn.js")
printf '%s\n' "$TASK_SUBNET_STATUS"
[[ "$TASK_SUBNET_STATUS" == 'UE1: internet / IPv4; UE2: internet2 / IPv4' ]]
python3 -B - <<'PY'
import json
import subprocess
rows = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr', 'show', 'dev', 'ogstun']))
if len(rows) != 1:
    raise SystemExit('STOP: ogstun is missing after core restart')
addresses = {row['local'] + '/' + str(row['prefixlen']) for row in rows[0].get('addr_info', [])}
if not {'10.45.0.1/16', '10.46.0.1/16'} <= addresses:
    raise SystemExit('STOP: both service addresses must remain on ogstun')
if rows[0].get('mtu') != 1400 or 'UP' not in rows[0].get('flags', []):
    raise SystemExit('STOP: ogstun must remain UP with MTU 1400')
print('Both ogstun service addresses: OK')
PY
ip -o -4 addr show dev ogstun
ip -4 route show 10.45.0.0/16
ip -4 route show 10.46.0.0/16
printf 'Core migration completed. Bundle: %s\nFresh UE registration/PDU/UL checks remain pending.\n' "$TASK_SUBNET_BUNDLE"
