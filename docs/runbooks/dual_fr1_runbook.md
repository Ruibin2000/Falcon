# DU2 Bring-up and Dual-FR1 UL Acceptance

Network update, 2026-10-23: Spark now uses `ogstun_1 / 10.45.0.1/16` for UE1
and `ogstun_2 / 10.46.0.1/16` for UE2, both MTU 1400, sharing the same UPF.
The [TUN split guide](../networking/dual_ue_tun_split.md) records the applied migration,
archived scripts and rollback. Spark checks and subsequent post-split
MPTCP traffic/UE2 recovery passed; see the October 23/24 reports. The measurements
below are historical pre-split checkpoints.

**Acceptance revision, 2026-10-24:** cold-start, full repeatability/comparative
and bidirectional disturbance/survivor tests are
[supplemental experiments](../development/dual_ue_supplemental_experiments.md),
not current Dual UE acceptance criteria or merge prerequisites.

Updated: 2026-10-23. The radio checkpoints below follow the October 13
[Plan 3](../../plans/dual-ue-du-fr1-channels.md) scope.
The current operator priority is DU2 implementation and UL-only acceptance.
Underflow remediation is deferred; record counts without using count/growth
alone as a pass/fail gate. UL failures and lost SA/PDU sessions still fail.

For the compact end-to-end operator flow, use the
[Dual UE laptop commands](../dual_ue_laptop_quick_commands.md) and
[Dual UE Spark commands](../dual_ue_spark_quick_commands.md). The operator completed the requested
[two-subnet migration](../networking/dual_ue_subnets.md): core service/DNN/address checks passed
for UE2 `internet2` / Spark `10.46.0.1`. UE2 subsequently established IPv4 bearer 3 /
`10.46.0.2/30` / `wwan0`, passed ping 5/5 over table 152 with the Wi-Fi default
preserved, and completed 60-second TCP UL at receiver 15.5 Mbit/s / sender Retr 1.
The KPM smoke run delivered 12 complete reports for UE F1AP 67 with numeric UL
metrics and successful subscription/deletion/completion. See the
[UL checkpoint](../evidence/2026-10-13_du2_ul/manifest.json); full dual-link acceptance
remains pending.
DU1 subsequently joined with F1/E2 complete. Both new SIMs registered on their
intended cells and both policy paths/private pings passed; new UE1 UL delivered
receiver 10.5 Mbit/s / Retr 0 / pipeline exit 0 with UE2 test traffic idle. The
DU-tagged diagnostic xApp found both E2 nodes and subscribed/deleted twice with
exit 0, but received zero UE callback blocks in that earlier probe; see
[UE1 UL](../evidence/2026-10-13_du1_ul/manifest.json) and
[two-DU subscription evidence](../evidence/2026-10-13_dual_kpm_subscriptions/manifest.json).
The later concurrent TCP UL run delivered receiver **UE1 13.8 / UE2 17.3
Mbit/s**, both sender Retr 0 and process exits 0. The latest Spark capture
received **123 callbacks per DU**, including **63/61 complete UL-active
five-metric rows**, with both subscription/delete pairs and normal exit.
Manually simultaneous clock readbacks put Spark about **199.27 seconds ahead
of Laptop**; the corrected run window contains approximately **62/61 complete
UL-active rows**. See [retained dual UL/KPM analysis](../evidence/2026-10-13_dual_kpm_reports/manifest.json).
Concurrent UL functionality and real two-DU KPM are now observed; full identity
correlation and precise timing retain their separate scope. Repeated/UDP
comparisons, cold-start and bidirectional disturbance/survivor experiments are
follow-up work outside current acceptance and merging. The earlier FlexRIC deletion-failure abort path remains unfixed.
For daily operation, start both DUs and both server endpoints before the
laptop's ordered UE1 and UE2 sequences. Keep both DUs active during these role
traffic tests and concurrent UL/KPM.
This runbook retains checkpoint
details and the full Plan 3 acceptance context.

## Preparation status

DU1's 3660-MHz UL result remains the verified reference. DU2 configuration is
prepared for actual B210 `328B021` and parses with the installed OCUDU DU binary.
The two configuration files are copied under `/home/nyu/ocudu/configs/` and the
offline checker passes. After reconnection on 2026-10-13, UHD and USB sysfs
identified `328B021` over USB 3 (5000 Mb/s). A later reconnection and firmware
load produced two successive discovery results containing both radios:
DU1 `3271233` at `2-1.3` / controller `NVDA8000:00`, and DU2 `328B021` at
`6-1.1` / controller `NVDA8000:02`, both USB 3 / 5000 Mb/s. Live DU2
startup subsequently confirmed B210 328B021 / USB 3 / 3600 MHz / PCI 2 /
SSB 639648, F1/E2 completion and RIC gNB 411 / DU ID 2 / KPM function ID 2.
MongoDB, ten SA services, CU and RIC were started for this run, while DU1 stayed
stopped. UE2 subsequently passed identity/cell/SA, the new IPv4 PDU/private ping,
and the single-link UL/KPM smoke checkpoint above. Both DUs and both private UE
paths were subsequently observed, followed by the concurrent UL / two-DU KPM
checkpoint above. Full acceptance remains pending. See the
[live startup evidence](../evidence/2026-10-13_du2_startup/manifest.json).
The [preparation evidence](../evidence/2026-10-13_du2_preparation/manifest.json)
retains configuration hashes, parse results, collision tests and the band-helper
derivation. A successful preparation check is not live acceptance.

| Item | DU1 | DU2 |
| --- | --- | --- |
| Carrier / NR-ARFCN | 3660 MHz / 644000 | 3600 MHz / 640000 |
| Band / bandwidth / common SCS | n78 / 20 MHz / 30 kHz | n78 / 20 MHz / 30 kHz |
| Radio serial / USB path | 3271233 / 2-1.3 / NVDA8000:00 | 328B021 / 6-1.1 / NVDA8000:02 |
| gNB / width / DU ID | 411 / 22 / 1 | 411 / 22 / 2 |
| PCI / sector / expected NCI | 1 / 0 / 6733824 | 2 / 1 / 6733825 |
| F1-C / F1-U local bind | 127.0.10.2 | 127.0.10.3 |
| E2 local bind / shared destination | 127.0.0.1 / 127.0.0.1:36421 | 127.0.10.3 / 127.0.0.1:36421 |
| SSB lock | 643680 from accepted startup | 639648 confirmed in startup and UE2 lock/serving-cell readback |
| Intended new subscriber | 001010000000101 | 001010000000102 |

DU2 preserves the initial sample rate 23.04 MS/s, internal clock, TX 70/RX 35,
and scheduler/RLC reporting at 1000 ms. Record actual gains/attenuation and the
operating conditions for each run. The existing CU defaults to gNB 411/22 and
six-DU capacity; no CU capacity or core-address change is required.

The offline RAN helper uses 51 PRBs, 30-kHz common/SSB SCS, SS0 index 0 and
maximum CORESET0 duration 2. It derives DU2 SSB 639648, offsetToPointA 0,
kSSB 20 and CORESET0 index 0. The same helper reproduces DU1 SSB 643680.
Recompute after changing the carrier/cell parameters or OCUDU version; use the
actual live startup/readback as the modem-lock confirmation.

## Bind the second radio and validate configuration

On **Spark**, confirm no running DU owns the radios before discovery. If a DU is
running, coordinate its shutdown rather than probing its radio concurrently.

```bash
pgrep -a -x odu
uhd_find_devices --args type=b200
```

Retain both physical serials. The maintained
[DU2 radio configuration](../../configs/ocudu/dual_fr1/du2_b210_n78_20mhz.yml)
already binds `328B021`, different from DU1 `3271233`. If changing the radio,
replace this serial with the independently discovered replacement identity.
Keep the [E2/KPM overlay](../../configs/ocudu/dual_fr1/du2_flexric.yml) as the second
configuration file. Never start a configuration that still has the placeholder.

After reconnecting, these boards initially appeared as Cypress WestBridge with
temporary serial `0000000004BE` at 480 Mb/s. UHD loaded firmware and they
re-enumerated with their distinct actual serials at 5000 Mb/s. Wait for discovery
to finish and confirm both actual identities before starting either DU. This
observation does not prove that earlier hub failures were solely caused by
firmware; USB descriptor timeouts were also observed. Keep the verified separate
controller arrangement and test concurrent streaming during UL acceptance.

```bash
set -euo pipefail
export FALCON_REPO=/home/nyu/Desktop/Falcon_repo/Falcon
export OCUDU_SOURCE=/home/nyu/ocudu
export DUAL_FR1_EVIDENCE
DUAL_FR1_EVIDENCE=$(mktemp -d /tmp/falcon-dual-fr1.XXXXXXXX)

python3 "$FALCON_REPO/scripts/dual_fr1/check_config.py"
cp "$FALCON_REPO/configs/ocudu/dual_fr1/du2_b210_n78_20mhz.yml" \
  "$OCUDU_SOURCE/configs/du2_b210_n78_20mhz.yml"
cp "$FALCON_REPO/configs/ocudu/dual_fr1/du2_flexric.yml" \
  "$OCUDU_SOURCE/configs/du2_flexric.yml"
python3 "$FALCON_REPO/scripts/dual_fr1/check_config.py" \
  --du1 "$OCUDU_SOURCE/configs/du1_b210_n78_3660mhz.yml" \
  --du2 "$OCUDU_SOURCE/configs/du2_b210_n78_20mhz.yml" \
  --du2-e2 "$OCUDU_SOURCE/configs/du2_flexric.yml"
"$OCUDU_SOURCE/build/apps/du_split_8/odu" \
  -c "$OCUDU_SOURCE/configs/du2_b210_n78_20mhz.yml" \
  -c "$OCUDU_SOURCE/configs/du2_flexric.yml" \
  --dryrun log --filename "$DUAL_FR1_EVIDENCE/du2.log"
sha256sum "$OCUDU_SOURCE/configs/du2_b210_n78_20mhz.yml" \
  "$OCUDU_SOURCE/configs/du2_flexric.yml"
```

Proceed only after both checker invocations and parsing return zero. The checker
checks offline identities/topology, including NCI, full nominal channel intervals,
and missing/placeholder serials. Parsing does not validate connected radios or full RF
semantics. Neither check establishes operating authorization, measured RF
conditions, installed subscribers, or live traffic. Retain those existing Plan 3
prerequisites separately, covering both full channels.

## Verify DU2 first

1. Follow the [Spark procedure](../single_ue/spark_quick_commands.md) to prepare core services,
   host settings, CU and the existing FlexRIC RIC. For the initial UE2 test,
   keep DU1 stopped to remove ambiguity in cell selection.
2. Start DU2 in its own **Spark** terminal. Export the same evidence directory
   from the prior terminal; do not create a second directory accidentally.

   ```bash
   cd /home/nyu/ocudu
   bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/run_du_console.sh \
     "${DUAL_FR1_EVIDENCE:?Use the prepared run directory}/du2_startup.log" \
     sudo stdbuf -oL -eL build/apps/du_split_8/odu \
     -c configs/du2_b210_n78_20mhz.yml \
     -c configs/du2_flexric.yml \
     log --filename "${DUAL_FR1_EVIDENCE:?Use the prepared run directory}/du2.log"
   ```

   After startup, enter `;h;` in this terminal and require help output. The
   launcher records the console while preserving interactive input. See
   [console and runtime RX gain](../dual_ue_spark_quick_commands.md#5d-console-input-and-temporary-rx-gain).

3. Retain actual startup: second serial, USB 3, PCI 2, carrier 640000 / 3600 MHz,
   observed `dl_ssb_arfcn`, and successful F1/E2. Confirm CU sees DU ID 2 / NCI
   6733825 and RIC sees gNB 411 / DU 2. A count of two historical setup lines
   does not establish two simultaneous DUs.
4. On the **UE laptop**, select the second RM500Q by current IMEI
   `863305041980706` and verify SIM IMSI `001010000000102`. Prepare its matching
   subscriber using the [SIM guide](../setup/sim_provisioning_and_dual_ue.md), with its own
   protected credentials, SST 1, UE1 DNN `internet` / UE2 DNN `internet2` after
   subnet migration, IPv4 type 1 and verified SQN
   representation. Do not replace the established subscriber or reuse SIM1 keys.
5. Use the [UE procedure](../single_ue/ue_laptop_quick_commands.md) on that modem's actual AT
   port. Lock PCI 2 using **DU2's observed SSB**, common SCS 30 and n78. Retain
   serving-cell readback, SA registration, IPv4 bearer/IP/WWAN and CU/DU UE IDs.
   DU1 SSB 643680 and carrier ARFCN 640000 are not DU2 SSB-lock substitutes.
6. Test private ping and UE2 UL on server port 5202. Use a dedicated UE2 source
   address and verify its route. Retain the result before enabling both links.

## Dual-link UL acceptance

Before simultaneous tests, complete Plan 3's guarded source-policy routing.
The existing single-WWAN helper must not be run twice: it changes one shared
main-table route. The dual-route helper and dual-DU monitor diagnostics remain
pending deliverables; their completion is required for the full dual baseline.

Start separate **Spark** servers in separate terminals:

```bash
iperf3 -s -B 10.45.0.1 -p 5201
```

```bash
iperf3 -s -B 10.46.0.1 -p 5202
```

On the **UE laptop**, in each modem's own terminal with its discovered source IP:

```bash
ip -4 route get 10.45.0.1 from "${UE1_IP:?Read the actual UE1 bearer}"
iperf3 -c 10.45.0.1 -p 5201 -B "$UE1_IP" -t 60 -i 1 --get-server-output -J
```

```bash
ip -4 route get 10.46.0.1 from "${UE2_IP:?Read the actual UE2 bearer}"
iperf3 -c 10.46.0.1 -p 5202 -B "$UE2_IP" -t 60 -i 1 --get-server-output -J
```

Save outputs with exact wall-clock windows and link identity. Current
functional verification covers UE1-only UL, UE2-only UL and concurrent UL with
working SA/PDU sessions and correct serving cells. The repeated comparison
matrix, controlled-load UDP measurements and their numerical targets belong to
[future supplemental experiments](../development/dual_ue_supplemental_experiments.md),
not current acceptance or merging. Application DL and mixed-direction trials
remain outside the original UL target.

Keep the existing five-metric KPM subscription. During active UL windows, require
at least 30 real rows per link with correct full DU/UE identity, numeric
`DRB.UEThpUl` / `RRU.PrbTotUl`, and successful subscription/deletion/normal exit.
Retain DL values/noValue as observations. Compare UL metric behavior with that
link's traffic without equating RLC bitrate to application receiver goodput.
Cold-start and repeated restart/reattachment trials, with fresh attribution/UL
observations, are recorded as supplemental experiments.

Underflow growth alone is nonblocking. Lost links, failed transfers, wrong-cell
association, crossed/fallback IP paths, missing UL metrics or failed lifecycle
checks still keep the corresponding gate pending. Report the outcome as dual
UL functionality/coexistence accepted with underflow remediation deferred.

For shutdown or rollback, use Plan 3 Step 12: stop traffic, let subscriptions
delete normally, disconnect the selected bearer, remove only run-owned laptop
configuration, and stop the recorded DU process. Preserve DU1's working profile.
