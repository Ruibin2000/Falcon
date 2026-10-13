# Dual UE Subnet Migration

Updated: 2026-10-13. This prepares the operator-requested two-subnet layout for
the shared Spark CU/Open5GS and two laptop modems. The inspected Spark packages
are Open5GS `2.8.0~noble5`. The operator has applied the migration and passed the
core-side service/DNN/address checks. UE2 subsequently passed the new IPv4
PDU/private ping and single-link UL/KPM smoke checkpoints. UE1 has now registered
on DU1 with its new IPv4 PDU/host path/private ping passed; concurrent UL remains pending;
core migration success alone is not dual-link acceptance.

| Role | IMSI | DNN / modem APN | UE address pool | Spark service IP / port |
| --- | --- | --- | --- | --- |
| UE1 / DU1 | `001010000000101` | `internet` | `10.45.0.0/16` | `10.45.0.1:5201` |
| UE2 / DU2 | `001010000000102` | `internet2` | `10.46.0.0/16` | `10.46.0.1:5202` |

Use one UPF and one `ogstun` with both `.1/16` addresses. Both services run on
Spark. DNN selects the address pool; modem cell lock selects DU1/DU2. This provides
separate address spaces and explicit routes through the existing shared core.
Subnet addresses alone do not provide firewall or physical-core isolation.
The new layout needs fresh registration/PDU/UL evidence; preserve old results
as historical evidence. UE2 subsequently passed fresh modem/SIM/cell/SA
readback and a successful lock write/readback, then established `internet2`
bearer 3 / `10.46.0.2/30` / `wwan0` and passed ping 5/5 through table 152 without
changing the Wi-Fi default route. Single-link TCP UL then delivered receiver 15.5 Mbit/s over 60.34 s / sender Retr 1, with 12 complete KPM smoke reports for UE F1AP 67. Full dual-link acceptance remains pending. See the
[registration checkpoint](evidence/2026-10-13_du2_registration/manifest.json)
and [IPv4 path checkpoint](evidence/2026-10-13_du2_ipv4_path/manifest.json).
UE1 subsequently established `internet` bearer 4 / `10.45.0.2/30` / `wwan1`,
pinged its `.1` endpoint with 5/5 replies through table 151, and both role policy
rules were read back while UE2 still returned all five requested echo replies.
See the [dual IPv4 path checkpoint](evidence/2026-10-13_dual_ipv4_paths/manifest.json).
UE1 subsequently passed 60-second TCP UL at receiver 10.5 Mbit/s / sender Retr 0
with pipeline exit 0; see [UE1 UL evidence](evidence/2026-10-13_du1_ul/manifest.json).
Concurrent UL/KPM remains pending.

Offline verification passed: ten configuration preservation/refusal cases,
eight subscriber fixtures covering targeted rename/rollback and refusal cases,
four role-specific policy preflight cases, and syntax checks for 37 Bash blocks.
The preparer also ran successfully against the inspected Spark configuration;
source checksums still matched afterward. No service, interface or subscriber
was changed during those checks. Privileged subscriber inspection could not run
without the operator's sudo password; stage 2 must establish the real records.

The operator subsequently confirmed both real subscribers as `internet / IPv4`,
prepared and reviewed bundle `/tmp/falcon-dual-subnets.Ir8TjqjO`, and supplied Spark
address/routes showing `ogstun` UP / MTU 1400 / `10.45.0.1/16` with no allocation
of `10.46.0.0/16`. UE2 modem 5 / IMEI `863305041980706` then disconnected all
bearers and reported `disabled / detached`. The operator then ran the saved apply
script: both services were active, UE2 read back `internet2 / IPv4`, and both
service addresses/routes were present on `ogstun`, ending with
`Core migration completed`. Read-only inspection independently confirmed the
deployed SMF/UPF/network files match the prepared bundle. The
[retained evidence](evidence/2026-10-13_dual_subnet_migration/manifest.json)
distinguishes operator-reported runtime checks from file inspection. Fresh UE2
Full dual-link UL/KPM, simultaneous UE paths and cold-start persistence remain pending. The saved apply script
passed six tests using mocked privileged/network commands, including failure
stopping and refusal to claim success with an inactive service or wrong DNN.

Open5GS 2.8.0 documents the session `subnet`, `gateway`, `dnn` and UPF `dev` fields
in its [SMF template](https://github.com/open5gs/open5gs/blob/v2.8.0/configs/open5gs/smf.yaml.in)
and [UPF template](https://github.com/open5gs/open5gs/blob/v2.8.0/configs/open5gs/upf.yaml.in).
The migration retains existing non-session settings and the original IPv6 pool,
associates the original pools with `internet`, and adds an IPv4-only `internet2`
pool. No CU/DU/RIC/radio change is needed.

## 1. Spark — prepare and inspect files

The first migration is already applied in the current session. Keep the original
bundle for rollback; resume at stage 5. Stages 1–4 below describe the original
single-pool migration and must not be reapplied to the migrated core.

Keep one Spark Bash terminal for the migration. Preparation is read-only for
the running deployment and creates a private temporary bundle with originals:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
FALCON_REPO=$PWD
SUBNET_RUN=$(mktemp -d /tmp/falcon-dual-subnets.XXXXXXXX)
python3 scripts/dual_fr1/prepare_dual_subnets.py --output-dir "$SUBNET_RUN"
printf 'Migration bundle: %s\n' "$SUBNET_RUN"
diff -u "$SUBNET_RUN/original/smf.yaml" "$SUBNET_RUN/prepared/smf.yaml"
diff -u "$SUBNET_RUN/original/upf.yaml" "$SUBNET_RUN/prepared/upf.yaml"
diff -u "$SUBNET_RUN/original/99-open5gs.network" "$SUBNET_RUN/prepared/99-open5gs.network"
```

`diff` exit 1 means differences were displayed. Require preparer success and
review only the session/address differences. An unexpected pool or configured
`smf.info` stops the preparer for manual review. If SMF discovery is restricted
by `smf.info`, its SST-1 DNN list must also advertise `internet2`.

The resulting **session block in both SMF and UPF** is:

```yaml
  session:
    - subnet: 10.45.0.0/16
      gateway: 10.45.0.1
      dnn: internet
    - subnet: 2001:db8:cafe::/48
      gateway: 2001:db8:cafe::1
      dnn: internet
    - subnet: 10.46.0.0/16
      gateway: 10.46.0.1
      dnn: internet2
```

The network file gains `Address=10.46.0.1/16` under `[Network]`, alongside its
existing addresses. Its persistence depends on the deployment's existing
systemd-networkd setup; verify both addresses again after a cold start.

## 2. Spark — check subscribers and address conflicts

This command reads only DNN/session fields for the two test subscribers:

```bash
sudo docker exec -i open5gs-mongo mongosh --quiet --file /dev/stdin \
  < "$FALCON_REPO/scripts/dual_fr1/ue2_dnn.js"
ip -o -4 addr show
ip -4 route show table all
```

Require exactly one subscriber per IMSI and one SST-1 IPv4 session per role.
UE1 must use `internet`; UE2 must currently use `internet` for the first migration.
The helper refuses ambiguous records or a preassigned static UE2 address. Resolve
a static address explicitly before changing its pool. If a subscriber is absent,
provision it with its existing protected credentials using the
[subscriber procedure](sim_provisioning_and_dual_ue.md#prepare-open5gs-subscribers),
then repeat this check. Do not recreate credentials or reset SQN.

For a first migration, `10.46.0.0/16` must not overlap an existing management,
VPN, container or policy-route allocation. If already deployed, inspect the
current layout instead of repeating the first-migration rollback assumptions.
No NAT change is required for UL to these local Spark service addresses.

## 3. UE laptop — stop old sessions and clean their recorded paths

Stop traffic and close minicom. In each already selected UE terminal, check the
modem identity again. Disconnect an existing PDU, then disable that selected
modem so its next enable performs fresh registration:

```bash
mmcli -m "$MODEM"
sudo mmcli -m "$MODEM" --simple-disconnect
sudo mmcli -m "$MODEM" --disable
```

If no PDU was connected, no disconnect is needed. Use recorded identity, not a
remembered modem index. Clean any old run's addresses/rules/routes using its
ledger and [laptop cleanup step 7](dual_ue_laptop_quick_commands.md#7-cleanup-and-retained-evidence).
The old shared-endpoint layout used `10.45.0.1` for **both** roles. Its old ledger
does not contain `PATH_SERVER`: reconstruct that value as `10.45.0.1` only after
confirming the recorded route destination. Never substitute the new UE2 target
when removing old entries. Do not flush shared routing tables.

## 4. Spark — apply the prepared migration

This stage interrupts PDU service. CU, DUs and RIC can remain running; stop UE
traffic/sessions first. Keep the private bundle for rollback. The apply script
stops on a failed command; on a partial failure, use stage 7 before reattaching.
The saved apply script avoids copying a multiline shell function into a terminal.
It rechecks the exact prepared files, source checksums, subnet availability and
subscriber shape before stopping SMF/UPF. Its sudo operations need the operator's
Spark password. It does not control modems on the separate UE laptop.

```bash
bash "$FALCON_REPO/scripts/dual_fr1/apply_dual_subnets.sh" "$SUBNET_RUN"
```

The subscriber helper renames only UE2's existing SST-1 IPv4 session from
`internet` to `internet2`. It retains QoS/AMBR, authentication fields, SQN and
all other subscribers, including baseline `001010000000001`. It does not create
missing subscribers. The function assumes the existing persistent `ogstun` is
present; if missing, stop and repair its original setup before proceeding.

Verify the result:

```bash
sudo docker exec -i open5gs-mongo mongosh --quiet --file /dev/stdin \
  < "$FALCON_REPO/scripts/dual_fr1/ue2_dnn.js"
systemctl is-active open5gs-upfd
systemctl is-active open5gs-smfd
ip -o -4 addr show dev ogstun
ip -4 route show 10.45.0.0/16
ip -4 route show 10.46.0.0/16
```

Require `UE1: internet / IPv4; UE2: internet2 / IPv4`, both units active,
both `.1/16` addresses and both private routes on `ogstun`. If startup fails,
inspect private service logs; do not share authentication-bearing logs verbatim.

## 5. UE laptop — fresh registration and matching APN

Enable each selected modem, then repeat identity selection, preferences, cell
lock and serving-cell checks in the revised
[laptop commands](dual_ue_laptop_quick_commands.md#ue2-selection). Modem indexes/ports may change.
For each role use a fresh terminal after cleaning its previous state:

```bash
sudo mmcli -m "$MODEM" --enable
```

After successful intended-cell registration, the PDU requests are:

```bash
# Selected UE1 terminal only:
sudo mmcli -m "$MODEM" --simple-connect="apn=internet,ip-type=ipv4"
```

```bash
# Selected UE2 terminal only:
sudo mmcli -m "$MODEM" --simple-connect="apn=internet2,ip-type=ipv4"
```

The Quick Start now sets `APN`, `UE_SUBNET` and `SERVER_IP` per role, checks the
bearer's matching APN, rejects an address outside the role's pool, installs
source-policy routes to that server, and records `PATH_SERVER` for cleanup.
Do not merely change iperf's destination while retaining old route rules.

## 6. Spark + UE laptop — verify each UL path

Run each Spark server in a separate terminal:

```bash
iperf3 -s -B 10.45.0.1 -p 5201
```

```bash
iperf3 -s -B 10.46.0.1 -p 5202
```

Follow Quick Start stages 8–11 for source routing, ping, 60-second UL, concurrent
traffic, path-loss/survivor checks and KPM. Preserve actual UE IPs and cell/DU
identity. Acceptance remains UL-only; underflow count alone remains deferred.
Neither separate addresses nor successful core startup prove dual-link UL.

## 7. Roll back a first migration

Stop traffic, disconnect/disable the two selected modems, and clean the migrated
laptop entries using their recorded `PATH_SERVER` values. On Spark, restore the
exact prepared originals and reverse only the UE2 DNN rename:

```bash
rollback_dual_subnets() {
  sudo systemctl stop open5gs-smfd open5gs-upfd || return 1
  sudo docker exec -i -e SUBNET_ACTION=rollback open5gs-mongo \
    mongosh --quiet --file /dev/stdin \
    < "$FALCON_REPO/scripts/dual_fr1/ue2_dnn.js" || return 1
  sudo install -m 0644 "$SUBNET_RUN/original/smf.yaml" /etc/open5gs/smf.yaml || return 1
  sudo install -m 0644 "$SUBNET_RUN/original/upf.yaml" /etc/open5gs/upf.yaml || return 1
  sudo install -m 0644 "$SUBNET_RUN/original/99-open5gs.network" \
    /etc/systemd/network/99-open5gs.network || return 1
  if ip -o -4 addr show dev ogstun | grep -Fq 'inet 10.46.0.1/16 '; then
    sudo ip -4 addr del 10.46.0.1/16 dev ogstun || return 1
  fi
  sudo systemctl start open5gs-upfd || return 1
  sudo systemctl start open5gs-smfd || return 1
  systemctl is-active --quiet open5gs-upfd || return 1
  systemctl is-active --quiet open5gs-smfd
}
rollback_dual_subnets
```

Only remove `10.46.0.1/16` when it was absent before this migration and belongs
to this run. Keep `10.45.0.1`, other interfaces and management routes. Reenable
and register the intended modem, use `internet` for both old-layout PDU sessions,
and rebuild routes to `10.45.0.1` using freshly discovered bearer identities.
Retain the bundle and migration result; do not claim an automatic rollback
completed when any command failed.
