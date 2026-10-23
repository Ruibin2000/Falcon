#!/usr/bin/env bash
# Split the shared UPF path into ogstun_1/ogstun_2, with rollback on failure.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { printf 'Run this script with sudo bash.\n' >&2; exit 1; }
TUN_BUNDLE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if [[ "$TUN_BUNDLE" != /var/backups/falcon-dual-tun-* ]]; then
  TUN_BACKUP="/var/backups/$(basename -- "$TUN_BUNDLE")"
  [[ ! -e "$TUN_BACKUP" && ! -L "$TUN_BACKUP" ]] || { printf 'Backup already exists: %s\n' "$TUN_BACKUP" >&2; exit 1; }
  install -d -m 0700 "$TUN_BACKUP"
  cp -R -- "$TUN_BUNDLE/." "$TUN_BACKUP/"
  chmod 0700 "$TUN_BACKUP"
  exec bash "$TUN_BACKUP/apply.sh"
fi
python3 "$TUN_BUNDLE/guard.py" preflight

recover_tun_split() {
  local failure_status=$?
  trap - ERR
  printf 'Migration failed; restoring the captured shared-TUN layout...\n' >&2
  if ! bash "$TUN_BUNDLE/rollback.sh"; then
    printf 'Automatic rollback failed. Inspect this bundle before reconnecting UEs: %s\n' "$TUN_BUNDLE" >&2
  fi
  exit "$failure_status"
}
trap recover_tun_split ERR

printf 'Stopping SMF/UPF; UE data sessions will be interrupted.\n'
systemctl stop open5gs-smfd open5gs-upfd
install -m 0644 "$TUN_BUNDLE/prepared/upf.yaml" /etc/open5gs/upf.yaml
install -m 0644 "$TUN_BUNDLE/prepared/99-open5gs.netdev" /etc/systemd/network/99-open5gs.netdev
install -m 0644 "$TUN_BUNDLE/prepared/99-open5gs.network" /etc/systemd/network/99-open5gs.network
install -m 0644 "$TUN_BUNDLE/prepared/99-open5gs-ue2.netdev" /etc/systemd/network/99-open5gs-ue2.netdev
install -m 0644 "$TUN_BUNDLE/prepared/99-open5gs-ue2.network" /etc/systemd/network/99-open5gs-ue2.network
ip link set dev ogstun down
ip link set dev ogstun name ogstun_1
ip link set dev ogstun_1 mtu 1400 up
ip tuntap add dev ogstun_2 mode tun
ip link set dev ogstun_2 mtu 1400 up
ip -4 addr del 10.46.0.1/16 dev ogstun_1
ip -4 addr replace 10.46.0.1/16 dev ogstun_2
networkctl reload
networkctl reconfigure ogstun_1 ogstun_2
systemctl start open5gs-upfd
systemctl start open5gs-smfd
sleep 2
python3 "$TUN_BUNDLE/guard.py" verify-split
trap - ERR
ip -br -4 addr show dev ogstun_1
ip -br -4 addr show dev ogstun_2
printf 'Split applied. Reconnect both UE PDU sessions and verify ping/traffic.\nBackup and rollback: %s\n' "$TUN_BUNDLE"
