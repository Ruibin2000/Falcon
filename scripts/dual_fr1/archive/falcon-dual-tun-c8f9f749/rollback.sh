#!/usr/bin/env bash
# Restore the captured shared-ogstun files and reverse the interface split.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { printf 'Run this script with sudo bash.\n' >&2; exit 1; }
TUN_BUNDLE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
python3 "$TUN_BUNDLE/guard.py" rollback-guard
systemctl stop open5gs-smfd open5gs-upfd
install -m 0644 "$TUN_BUNDLE/original/upf.yaml" /etc/open5gs/upf.yaml
install -m 0644 "$TUN_BUNDLE/original/99-open5gs.netdev" /etc/systemd/network/99-open5gs.netdev
install -m 0644 "$TUN_BUNDLE/original/99-open5gs.network" /etc/systemd/network/99-open5gs.network
rm -f -- /etc/systemd/network/99-open5gs-ue2.netdev /etc/systemd/network/99-open5gs-ue2.network
if ip link show dev ogstun_2 >/dev/null 2>&1; then
  ip link set dev ogstun_2 down
  ip tuntap del dev ogstun_2 mode tun
fi
if ip link show dev ogstun_1 >/dev/null 2>&1; then
  ip link set dev ogstun_1 down
  ip link set dev ogstun_1 name ogstun
fi
ip -4 addr replace 10.46.0.1/16 dev ogstun
ip link set dev ogstun mtu 1400 up
networkctl reload
networkctl reconfigure ogstun
systemctl start open5gs-upfd
systemctl start open5gs-smfd
sleep 2
python3 "$TUN_BUNDLE/guard.py" verify-shared
printf 'Restored the captured shared-ogstun configuration. Reconnect UE sessions.\n'
