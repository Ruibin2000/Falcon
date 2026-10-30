# Dual UE Spark TUN Split

Updated: 2026-10-24. The operator applied this migration on `spark-7c40`
(Open5GS `2.8.0~noble5`) on October 23. Independent read-only checks confirmed
the deployed configuration, addresses, return routes and active SMF/UPF services.
Subsequent post-split traffic passed in the
[October 23 MPTCP video trial](../reports/mptcp_video_experiment_report_2026-10-23.md);
fresh UE2 PDU/IP recovery and both ping modes passed in the
[October 24 recovery trial](../reports/ue2_fr3_recovery_experiment_report_2026-10-24.md).
Cold-boot persistence remains untested and is tracked as a
[supplemental experiment](../development/dual_ue_supplemental_experiments.md),
not a prerequisite for current acceptance or merging.

## Current layout

The [current radio design](../dual_link_radio_design.md) uses DU1 at
3660 MHz / 20 MHz and DU2 at a 3600-MHz n78 interface / 40 MHz, with a
designed Pi-Radio 9250-MHz OTA path. The October 29 direct-radio test has no
converters. The radio bandwidth/conversion changes retain the DNN, subnet,
TUN and policy-table assignments below; always rediscover the allocated UE IP.

| Role | DNN / APN | UE IPv4 pool | Spark interface | Spark service endpoint |
| --- | --- | --- | --- | --- |
| UE1 / DU1 | `internet` | `10.45.0.0/16` | `ogstun_1` | `10.45.0.1:5201` |
| UE2 / DU2 | `internet2` | `10.46.0.0/16` | `ogstun_2` | `10.46.0.1:5202` |

Both TUN interfaces are UP with MTU 1400 and share the existing UPF. The
original `ogstun` was renamed to `ogstun_1`; `ogstun_2` was created and received
`10.46.0.1/16`. IPv6 `2001:db8:cafe::1/48` remains on `ogstun_1`. The old
interface name `ogstun` no longer exists.

Laptop WWAN names and bearer allocations must still be rediscovered each run.
Spark service IPs, DNNs, subscriber records, SMF and CU/DU/RIC configuration,
and iperf IP/port bindings were retained. Applications or captures that bind
a Spark interface must now select `ogstun_1` or `ogstun_2`. The two Linux
interfaces still share the CU, UPF and Spark resources.

## Persistent configuration

| Deployed file | Role after migration |
| --- | --- |
| `/etc/open5gs/upf.yaml` | `upf.session[].dev` selects each pool's TUN |
| `/etc/systemd/network/99-open5gs.netdev` | Defines `ogstun_1`, `Kind=tun` |
| `/etc/systemd/network/99-open5gs.network` | Matches `ogstun_1`; UE1 IPv4, original IPv6, MTU 1400 |
| `/etc/systemd/network/99-open5gs-ue2.netdev` | Defines `ogstun_2`, `Kind=tun` |
| `/etc/systemd/network/99-open5gs-ue2.network` | Matches `ogstun_2`; UE2 IPv4, MTU 1400 |

The active UPF session block is:

```yaml
  session:
    - subnet: 10.45.0.0/16
      gateway: 10.45.0.1
      dnn: internet
      dev: ogstun_1
    - subnet: 2001:db8:cafe::/48
      gateway: 2001:db8:cafe::1
      dnn: internet
      dev: ogstun_1
    - subnet: 10.46.0.0/16
      gateway: 10.46.0.1
      dnn: internet2
      dev: ogstun_2
```

These files provide the persistent setup; recovery after a cold reboot has
not been tested. Do not restart management networking to inspect it.

## Routine Spark checks

```bash
for tun in ogstun_1 ogstun_2; do
  ip -o link show dev "$tun"
  ip -o -4 addr show dev "$tun"
done
ip -4 route show 10.45.0.0/16
ip -4 route show 10.46.0.0/16
systemctl is-active open5gs-upfd open5gs-smfd systemd-networkd
```

Require the address/interface pairs above, UP flags, MTU 1400,
`10.45.0.0/16` through `ogstun_1`, `10.46.0.0/16` through `ogstun_2`, and active
services. A return-route lookup alone does not establish UE connectivity.

Repeat each role's complete [laptop sequence](../dual_ue_laptop_quick_commands.md)
to rebuild its actual bearer/WWAN/policy path, then verify source-bound ping
and individual/concurrent traffic against the paired
[Spark servers](../dual_ue_spark_quick_commands.md). Use newly read UE addresses;
the `.2` destinations in the retained route probes are routing checks only.

## Archived migration and reproduction

The [archive](../../scripts/dual_fr1/archive/falcon-dual-tun-c8f9f749/README.md)
preserves the exact bundle prepared in `/tmp/falcon-dual-tun-c8f9f749`:

- [apply.sh](../../scripts/dual_fr1/archive/falcon-dual-tun-c8f9f749/apply.sh): preflight checks, durable backup, migration and verification; attempts rollback on a migration-step failure.
- [guard.py](../../scripts/dual_fr1/archive/falcon-dual-tun-c8f9f749/guard.py): hashes, interface/address ownership, return routes, services, deployed files and management-route checks.
- [rollback.sh](../../scripts/dual_fr1/archive/falcon-dual-tun-c8f9f749/rollback.sh): restores the captured shared-`ogstun` state.
- `original/`, `prepared/`, `manifest.json`, `source.json`, `baseline.json` and `archive.sha256`: original/prepared configurations, intended layout and checksums.

Check archive integrity and shell syntax without changing deployment state:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/archive/falcon-dual-tun-c8f9f749
sha256sum -c archive.sha256
bash -n apply.sh rollback.sh
```

This snapshot applies only to the captured host/configuration. The apply
script requires matching original hashes, both addresses on `ogstun`, no
conflicting TUNs and active services. It refuses an existing backup destination.
**Spark is already migrated; do not reapply this bundle.**

For reproduction from the captured pre-migration state, stop MPX/iperf traffic
on both hosts. In each selected laptop UE terminal, verify the actual modem,
disconnect its PDU and disable it using the
[laptop procedure](../dual_ue_laptop_quick_commands.md). USB removal and Spark
shutdown are unnecessary; CU/DU/RIC can remain running. The historical apply
command, using the archived copy, is:

```bash
sudo bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/archive/falcon-dual-tun-c8f9f749/apply.sh
```

The script copies its bundle to `/var/backups/falcon-dual-tun-c8f9f749`, then
stops/restarts SMF and UPF. Re-enable both modems and repeat their complete
bearer and host-route setup afterward.

## Rollback

Stop traffic and disconnect/disable both selected modems first. Use the durable
backup created by the successful operator-run migration:

```bash
sudo bash /var/backups/falcon-dual-tun-c8f9f749/rollback.sh
```

Rollback restores the original UPF/networkd files, removes the new UE2
networkd files and `ogstun_2`, renames `ogstun_1` back to `ogstun`, and places
both `.1/16` addresses there. It retains both DNNs and pools; it does not undo
the October 13 subscriber/subnet migration. The guard refuses to overwrite
controlled files changed independently. Live rollback and the automatic
failure-recovery branch have not been exercised.

## Evidence and remaining validation

The [manifest](../evidence/2026-10-23_dual_tun_split/manifest.json) separates
[operator output](../evidence/2026-10-23_dual_tun_split/operator_stdout.txt), the
independent [runtime snapshot](../evidence/2026-10-23_dual_tun_split/runtime_snapshot.json)
and [archived guard verification](../evidence/2026-10-23_dual_tun_split/archive_verify_stdout.txt).
The [archive validation record](../evidence/2026-10-23_dual_tun_split/archive_validation.json)
records checksum, script syntax, documentation shell syntax and link checks.
All five deployed files match the archived prepared hashes; SMF configuration,
management default routing and IPv4 policy rules match the captured baseline.
The operator's final output line was truncated. The complete durable backup
path was independently observed; its root-only contents were not independently
read.

Post-split MPTCP traffic and fresh UE2 PDU/IP/ping recovery are recorded in
the October 23/24 reports linked above. Cold-boot persistence remains a
supplemental experiment; live rollback remains untested. October 13 and
October 21 measurements describe the shared-`ogstun` deployment and remain
historical.
