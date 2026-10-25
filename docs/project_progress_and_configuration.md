# Project Progress and System Configuration

**Reporting update, 2026-10-25:** the current default seven-metric profile now
uses **100 ms** DU scheduler/RLC statistics and DU KPM subscriptions. CU
identity stays at **1000 ms**, Core polling at **1 second**, and freshness at
**3 seconds**. Sub-second RLC throughput retains REAL precision. Snapshot
concurrency work remains deferred by operator request; the existing cache,
cleanup and executor behavior is preserved. The DU binary is rebuilt and native/offline checks
pass. Live 100 ms cadence, loss and radio-load behavior remain to be measured
using the [default Spark startup and section 7 inspection](dual_ue_spark_quick_commands.md). The earlier 1000 ms dual-UE run verified current IP association
and RF delivery; it does not establish 100 ms performance. Laptop connection
commands and recovery policy are unchanged.

**Acceptance scope, 2026-10-24:** cold-start reproduction, full
repeatability/comparative testing and bidirectional link-loss/recovery with
survivor traffic are
[supplemental experiments](development/dual_ue_supplemental_experiments.md).
They are excluded from current Dual UE acceptance criteria and merge
prerequisites. They remain uncompleted experiments, rather than failed or
pending current acceptance gates. The earlier dated scope statements below
are superseded for these three items.

Automation checkpoint, **2026-10-24**: the current UE automatic-reconnect script
optimization stage is complete by operator decision. Retain the current recovery
policy and parameters. The new
[English UE2 / FR3 recovery report](reports/ue2_fr3_recovery_experiment_report_2026-10-24.md)
records two completed TX-gain disturbance/recovery cycles after host NTP
synchronization, with automatic IPv4 adaptation from `.44` to `.45` to `.46`.
Gain restoration to detected PRACH took **22.223 s / 21.076 s** on Spark;
restoration to watcher verification took approximately **24.621 s / 23.141 s**
across the synchronized hosts. The operator-directed closing stage is excluded.
The dated architecture and phase table below remain historical records.

Network update, **2026-10-23**: the applied [Spark TUN split](networking/dual_ue_tun_split.md)
places UE1 `10.45.0.1/16` on `ogstun_1` and UE2 `10.46.0.1/16` on `ogstun_2`,
both MTU 1400, using the existing UPF. Independent checks of Spark configuration,
routes and services passed. Subsequent post-split traffic is recorded in the
[October 23 MPTCP report](reports/mptcp_video_experiment_report_2026-10-23.md),
with fresh UE2 PDU/ping recovery in the October 24 report above. Cold-boot
persistence remains to be measured in the supplemental cold-start experiment;
it does not block current acceptance or merging. The radio and traffic
checkpoints below retain their dates.

Radio/UE checkpoint summary, **2026-10-13**. DU1 migrated from 3750 to **3660 MHz within n78**. Single-UE IPv4 ping, a 30-second TCP uplink (receiver **17.0 Mbit/s**, sender Retr **0**), and **12 complete five-metric KPM reports for UE F1AP ID 5** passed. The operator now prioritizes DU2 and UL-only dual-link acceptance. Underflow remediation is deferred; count/growth alone does not block this UL scope. DU2 is configured/deployed for B210 `328B021` (USB 3) and passes offline checks. Actual DU2 radio startup/F1/E2 passed; UE2 registration/UL, the dual-link baseline and subscriber identity correlation remain pending. See the [DU2 procedure](runbooks/dual_fr1_runbook.md), historical [daily log](../dev_logs/2026-10-12_ruibin.md) and [retained evidence](evidence/2026-10-12_du1_3660mhz/manifest.json).

## Verified single-link architecture as of 2026-10-13

```mermaid
flowchart LR
    Laptop[Linux laptop application] <-->|USB / QMI data interface| UE[RMU500EK / RM500Q-GL]
    UE <-->|NR SA n78: 3660 MHz| B210[USRP B210: 3271233]
    subgraph Spark[NVIDIA DGX Spark]
        DU[OCUDU DU1]
        CU[OCUDU CU: CP / UP]
        AMF[Open5GS AMF]
        SMF[Open5GS SMF]
        UPF[Open5GS UPF]
        TUN[ogstun_1: 10.45.0.1]
        App[Local Spark application]
        RIC[FlexRIC Near-RT RIC]
        XAPP[C KPM xApp]
        DU <-->|F1-C / F1-U| CU
        CU <-->|N2| AMF
        CU <-->|N3 GTP-U| UPF
        SMF <-->|N4 PFCP| UPF
        UPF <-->|Local data-network IP path| TUN
        TUN <--> App
        DU <-->|E2 and UE KPM reports verified| RIC
        RIC <-->|UE KPM reception verified| XAPP
    end
    B210 <-->|USB 3 / UHD| DU
```

The tested application path is **laptop ↔ Spark over private 5G**. Management Wi-Fi (observed Spark address `10.20.44.26` on `wlP9s9`) is separate. Public Internet connectivity, NAT and a replacement laptop default route are outside this baseline. FlexRIC receives actual UE telemetry from DU1; the two-path FR1/FR3, AI and MPTCP design remains in the [README target architecture](../README.md#target-architecture).

## Phase status

| Phase | Scope | Status on 2026-10-13 |
|---|---|---|
| 0 | DGX Spark baseline | Verified |
| 1 | UHD / B210 #1 / USB 3 | Verified |
| 2 | OCUDU build | Verified |
| 3 | Single CU/DU / N2 / F1 / Open5GS | Verified |
| 4 | RM500Q SA registration, authentication, IPv4 PDU, WWAN, local data | Initial-session baseline retained; 3660-MHz private ping and 30-second TCP uplink passed; active IMSI not captured |
| 5 | Second DU / second radio / second UE | SIM/modem preparation complete; DU2 configured for B210 328B021; both B210s discovered over USB 3 on separate controllers; actual DU2 radio/F1/E2 startup passed; UE2 registration and single/dual-link UL pending |
| 6 | Host real-time work | Historical tuning retained; 117 underflows observed on 2026-10-12; remediation deferred and count/growth alone nonblocking for current UL scope |
| 7–8 | FlexRIC / KPM xApp | At 3660 MHz: DU1 E2 Setup and 12 complete UE ID 5 reports passed; subscription/deletion and success marker retained |
| 9–11 | MPTCP / RIC-assisted control / AI steering | Future work |

Follow the [DU2 procedure](runbooks/dual_fr1_runbook.md) to start the shared infrastructure and validate DU2 with its bound B210 `328B021`. Both B210s now pass simultaneous discovery over USB 3 on separate host controllers; recheck after reconnection. Prepare the two matching Open5GS subscribers using the [SIM and Dual-UE Guide](setup/sim_provisioning_and_dual_ue.md). Preserve DU1's working configuration. Test UE1 UL, UE2 UL and both UL concurrently with retained identities/KPM timing; underflow remediation is deferred. Protocol-explicit KPM/application correlation and active steering retain their separate scope. Cold-start/new-laptop reproduction is a supplemental experiment outside current acceptance and merging.

## Platform and prior build evidence

| Component | Record |
|---|---|
| Host | `spark-7c40`, NVIDIA DGX Spark / GB10, aarch64, Ubuntu 24.04.5 LTS |
| Kernel | `7.0.0-1019-nvidia`, PREEMPT_DYNAMIC |
| CPU / memory | 20 cores, one NUMA node, 121 GiB RAM |
| CPU layout | Cortex-A725: 0–4, 10–14; Cortex-X925: 5–9, 15–19 |
| OCUDU | `release_26_04`, `050a2bb`, 26.04.0, `/home/nyu/ocudu` |
| FlexRIC | `br-flexric`, `736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8`, `/home/nyu/flexric`, build directory `build-ocudu` |
| FlexRIC build | GCC 13.3, Debug; `E2AP_V3`, `KPM_V3_00`, `NONE_XAPP`, multilanguage OFF |
| Build | Clang 18.1.3; system GCC 13.3 unchanged |
| Open5GS | Ubuntu arm64 packages `2.8.0~noble5` |
| MongoDB | Docker `mongo:7.0-jammy`, container `open5gs-mongo`, volume `open5gs-mongo-data` |
| UHD / B210 | UHD 4.6.0.0, serial `3271233`, name MyB210, type b200, USB 3 / 5000M |
| UE | Quectel RMU500EK / RM500QGL_VH, firmware `RM500QGLABR13A03M4G`, USB `2c7c:0800` |

CU `build/apps/cu/ocu` and DU `build/apps/du_split_8/odu` exist. Monolithic `gnb_split_8` was built for a smoke check and is not the deployment topology. Earlier `band_helper_test` passed. The earlier 30.72 MS/s, 20-second RX USB benchmark had no drops, overruns, sequence errors or timeouts; it was not an NR throughput test. Current NR sample rate is 23.04 MS/s.

The NVIDIA kernel supports `CONFIG_MPTCP=y`, `CONFIG_MPTCP_IPV6=y` and `net.mptcp.enabled=1`; no MPTCP endpoints or steering are part of this single-link result. FlexRIC and the C xApp were built with GCC 13.3. Python/CUDA AI work remains pending.

## Configuration records

The current standalone configuration is maintained in Falcon and deployed to `/home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml`. It includes radio, cell, F1, E2/KPM, and metrics settings. The preserved `du1_b210_n78_20mhz.yml` and `du1_flexric.yml` files are historical references. Editing this document does not deploy configuration.

### DU1 3660 MHz uplink checkpoint — 2026-10-12

| Item | Recorded value |
| --- | --- |
| Config | [Standalone DU1 file](../configs/ocudu/dual_fr1/du1_b210_n78_3660mhz.yml); deployed copy under `/home/nyu/ocudu/configs/` |
| Carrier / SSB | `644000` / **3660 MHz**; SSB `643680` from actual startup |
| Band / channel / SCS / PCI | n78 / 20 MHz / 30 kHz / 1 |
| B210 / sample rate / gains | Serial `3271233`, USB 3, 23.04 MS/s, TX 70 / RX 35 |
| Identity / F1 | gNB 411, DU 1; DU `127.0.10.2` to CU `127.0.10.1` |
| E2 / metrics | RIC `127.0.0.1:36421`; scheduler/RLC enabled; 1000-ms period |
| UE data path | `10.45.0.2 / wwan0` to Spark `10.45.0.1`; installed IMSI and bearer ID not recorded |
| TCP UL | Sender 17.7 Mbit/s / Retr 0 / 30.03 s; receiver 17.0 Mbit/s / 30.24 s |
| Ping | 5/5 replies, 0% loss; RTT min/avg/max/mdev 33.593/136.571/538.943/201.191 ms |
| KPM | One connected DU node; UE F1AP ID 5; 12 complete five-metric rows; age 508–820 µs |
| RF stability | Pending; 117 underflows observed by 11:39:44 EDT |
| Config SHA-256 | `c40667a31206aa4ca7b8f08d826f7d87320df5280b59ef388dbab34e9f9b326d` for both maintained and deployed copies |

The UE lock is `AT+QNWLOCK="common/5g",1,643680,30,78`. SSB was read from the new DU startup; it was not calculated using the old carrier-to-SSB offset. This checkpoint records migration and uplink functionality, with stability pending. Downlink is outside its acceptance scope. [Evidence manifest](evidence/2026-10-12_du1_3660mhz/manifest.json) retains source revisions and binary/config hashes.

The following DU1 base excerpt and radio table are the **historical 3750-MHz configuration**, retained for comparison.

### DU1: `configs/du1_b210_n78_20mhz.yml`

```yaml
gnb_du_id: 1

f1ap:
  addrs: 127.0.10.1
  bind_addrs: 127.0.10.2

f1u:
  socket:
    - bind_addr: 127.0.10.2

ru_sdr:
  device_driver: uhd
  device_args: type=b200,serial=3271233,num_recv_frames=64,num_send_frames=64
  srate: 23.04
  clock: internal
  clock_ppm: 0.0
  freq_offset: 0
  tx_gain: 80
  rx_gain: 40

cell_cfg:
  dl_arfcn: 650000
  band: 78
  channel_bandwidth_MHz: 20
  common_scs: 30
  plmn: "00101"
  tac: 7
  pci: 1

log:
  filename: /tmp/du.log
  all_level: info
```

TX gain 80 / RX gain 40 is the verified 2026-10-05 traffic baseline; early gain 10/20 experiments are historical. The actual base file inspected on 2026-10-07 has **TX 70 / RX 40**; the E2 overlay changes neither gain. This session validated RAN/E2 startup, subscription and actual UE KPM reception at the current settings, without a new synchronized application throughput benchmark. Preserve the actual file and record its gain for each experiment rather than silently restoring 80. Gain is not calibrated transmit power. PRACH and PUSCH CRC OK with 20–33 dB SINR established RX 40 in the earlier session. MAC/F1 captures remain disabled and no explicit `otw_format` is present.

| Radio parameter | Value |
|---|---|
| Carrier band / ARFCN / frequency | n78 / 650000 / 3750 MHz |
| SSB ARFCN / frequency | 649632 / 3744.48 MHz |
| Channel / common and SSB SCS | 20 MHz / 30 kHz |
| CRBs / subcarriers | 51 / 612 |
| FFT length from sample rate/SCS | 23.04 MS/s ÷ 30 kHz = 768 |
| SSB offset Point A / k_SSB | 0 / 4 |
| PCI / antennas | 1 / 1T1R |

The modem cell lock uses **SSB ARFCN 649632**, not carrier ARFCN 650000. DU startup reports both values. Stopping DU ends NR transmission; PSS/SSS/PBCH/SSB and system information can be transmitted without an attached UE.

### CU: `configs/cu.yml`

```yaml
cu_cp:
  request_pdu_session_timeout: 10
  amf:
    addrs: 127.0.0.5
    bind_addrs: 127.0.0.1
    supported_tracking_areas:
      - tac: 7
        plmn_list:
          - plmn: "00101"
            tai_slice_support_list:
              - sst: 1
  f1ap:
    bind_addrs: 127.0.10.1

cu_up:
  ngu:
    socket:
      - bind_addr: 127.0.0.1
  f1u:
    socket:
      - bind_addr: 127.0.10.1

log:
  filename: /tmp/cu.log
  all_level: info

pcap:
  ngap_enable: false
  ngap_filename: /tmp/cu_ngap.pcap
```

The inspected local CU file explicitly contains `ngu`. The supplied successful excerpt omitted it; runtime inspection showed N3 bound to `127.0.0.1:2152`. No isolated evidence established that adding `ngu` was necessary to fix the session. Preserve the working file and diagnose from the actual sockets.

### DU1 E2 and KPM configuration

The tested overlay is `/home/nyu/ocudu/configs/du1_flexric.yml`, loaded after the existing UHD base file:

```yaml
e2:
  enable_du_e2: true
  addrs: [127.0.0.1]
  bind_addrs: [127.0.0.1]
  port: 36421
  e2sm_kpm_enabled: true

metrics:
  layers:
    enable_sched: true
    enable_rlc: true
  periodicity:
    du_report_period: 1000
```

The existing OCUDU binary already contains E2 support; `ENABLE_EXPORT` controls library export/install and is not an E2 enable switch. No OCUDU rebuild or ZeroMQ change was needed. CU E2 and E2SM-RC control are not enabled by this overlay.

| FlexRIC setting | Current value |
|---|---|
| RIC executable | `/usr/local/bin/flexric/ric/nearRT-RIC` |
| C xApp executable | `/usr/local/bin/flexric/xApp/c/xapp_oran_moni` |
| RIC / xApp configs | `/usr/local/etc/flexric/ric.conf`, `xapp_oran_sm.conf` |
| Service model directory | `/usr/local/lib/flexric/` |
| RIC E2 / xApp E42 | `127.0.0.1:36421` / `127.0.0.1:36422`, SCTP |
| E2 identity reported by RIC | PLMN `001/01`, node ID `411`, type `ngran_gNB_DU`, DU ID `1` |
| KPM function / action / period | RAN function ID `2`, Format 4, 1000 ms |
| DU measurement names | `DRB.RlcSduDelayDl`, `DRB.UEThpDl`, `DRB.UEThpUl`, `RRU.PrbTotDl`, `RRU.PrbTotUl` |

The default xApp config also lists monolithic gNB/CU and RC subscriptions; the RAN-type checks select only the DU KPM block for this node. The `73650812` example runs for about 10 seconds, deletes its subscription and exits normally. An initial actual gNB-DU UE F1AP ID `14` run received all five metrics: selected UL/DL throughput samples were 14163–14675 / 242–253 kbps, DL RLC delay 15.80–17.30 in 0.1 ms units, and UL/DL PRB usage 86%/0%.

After the installed [timestamp repair](troubleshooting/2026-10-07_flexric_latency_fix.md), UE F1AP ID `2` produced 12 `report_age_us` values of **499–717 microseconds**, followed by normal deletion and exit. Its selected UL/DL throughput samples were 11916–11927 / 147–164 kbps, DL RLC delay **1.380–1.440 ms** after conversion, and UL/DL PRB usage **88%/0%**. UE IDs can change. Live timestamp display is now verified; precise age accuracy and synchronized application throughput are not established by these excerpts. See [runtime steps](runbooks/full_reproduction_runbook.md#9a-deploy-the-complete-du1-configuration) and the [dated record](troubleshooting/2026-10-07_flexric_bringup.md) for metric interpretation.

### Open5GS identity, sessions and interfaces

| Configuration | Required baseline |
|---|---|
| `/etc/open5gs/nrf.yaml` | `nrf.serving` MCC `001`, MNC `01` |
| `/etc/open5gs/amf.yaml` | N2 bind `127.0.0.5`; GUAMI/TAI/PLMN `001/01`, TAC 7, SST 1 |
| `/etc/open5gs/smf.yaml` | PFCP `127.0.0.4` → UPF `127.0.0.7`; `internet / 10.45.0.0/16`, `internet2 / 10.46.0.0/16`; MTU 1400 |
| `/etc/open5gs/upf.yaml` | PFCP/GTP-U bind `127.0.0.7`; session devices `ogstun_1` for `internet`, `ogstun_2` for `internet2` |
| Spark TUNs, 2026-10-23 | `ogstun_1 / 10.45.0.1/16`, `ogstun_2 / 10.46.0.1/16`, both MTU 1400 |
| Subscriber | Test IMSI `001010000000001`, SST 1, DNN `internet`, session type **1** |
| Laptop active bearer | IPv4/static; query current address/prefix/MTU and interface |

SMF/UPF files retain IPv6 pool entries, but the experiment uses IPv4 only. The local SMF lacks an explicit enabled `info` DNN block; the successful `internet` session was established through the subscriber/selection configuration. Do not label the lack of that block as a confirmed DNN failure.

| Function category | Units |
|---|---|
| Required/tested local SA | `open5gs-nrfd`, `open5gs-scpd`, `open5gs-udrd`, `open5gs-udmd`, `open5gs-ausfd`, `open5gs-pcfd`, `open5gs-nssfd`, `open5gs-upfd`, `open5gs-smfd`, `open5gs-amfd` |
| Legacy LTE EPC | `open5gs-mmed`, `open5gs-hssd`, `open5gs-pcrfd`, `open5gs-sgwcd`, `open5gs-sgwud` |
| Optional for this experiment | `open5gs-bsfd`, `open5gs-seppd` |
| Administration only | `open5gs-webui` |

MongoDB is separate from systemd Open5GS services, maps localhost `27017` and retains its Docker volume. Native MongoDB 8 failed with the recorded NVIDIA kernel; keep it disabled.

The inspected persistent TUN setup is `/etc/systemd/network/99-open5gs.netdev`
(`Name=ogstun_1`, `Kind=tun`) and `99-open5gs.network` (UE1 IPv4, original IPv6,
routes and MTU 1400), plus `99-open5gs-ue2.netdev` / `99-open5gs-ue2.network`
for `ogstun_2` and UE2 IPv4. The UPF unit requests `systemd-networkd`.
The [archived migration](networking/dual_ue_tun_split.md) records all five deployed
UPF/networkd files and their hashes. A cold reboot has not been tested.

### Provisioned Open Cells SIMs and dual-UE preparation

The existing single-link test subscriber `001010000000001` remains the verified baseline. The two additional cards below have completed personalization and local authentication; their matching Open5GS records and real 5G registration are the next work.

| Intended path | Card | ICCID | IMSI | MSISDN / SPN | Protected local credentials |
|---|---|---|---|---|---|
| UE1 / DU1 | `OC011830` | `89860061100000000830` | `001010000000101` | `00000101` / `OpenCells101` | `~/sim_du1_credentials.txt` |
| UE2 / DU2 | `OC011831` | `89860061100000000831` | `001010000000102` | `00000102` / `OpenCells102` | `~/sim_du2_credentials.txt` |

Both use MCC `001`, MNC `01` and PLMN `00101`, with independent 128-bit K/OPc pairs stored in permission-600 files outside Git. The secrets were written to the corresponding physical card; they are not derived from IMSI or ICCID and cannot normally be read back from the USIM. The corresponding Open5GS record must use that same card's pair.

ACS ACR39U `072f:b100`, PC/SC/libccid and the rebuilt `program_uicc_pcsc` utility successfully read and programmed both cards. Both Milenage tests succeeded at programmer SQN **64** and reported an HSS reference SQN of **96**. Verify the installed Open5GS SQN representation before configuring this value, and avoid unnecessary repeat authentication because it advances the SIM SQN. Setup, exact commands and troubleshooting are in [SIM Provisioning and Dual-UE Preparation](setup/sim_provisioning_and_dual_ue.md).

| Physical modem | Evidence |
|---|---|
| Quectel #1, previously observed IMEI `863305041978437` | SIM1 ready in RM500QGL_VH; SIM2 also passed an initial check in this unit |
| Quectel #2, IMEI `863305041980706` | SIM2 ready in a second physical RM500QGL_VH |

Both cards showed the intended IMSI/ICCID/SPN, preferred PLMN `00101` with LTE + 5G NR, and ready USIM applications/personalization with PIN1 disabled. At the SIM2 check, the new modem was searching with packet service detached; this is not a SIM-readiness failure and does not prove private-cell registration. Its reported 88% signal quality does not establish reception of the target cell. A carrier-profile difference (`Volte_OpenMkt-Commercial-CMCC` versus a previously observed `ROW_Commercial`) is a later registration diagnostic if cell, band and subscriber checks pass; no profile change has been made.

The intended architecture is SIM1 → Quectel #1 → DU1 and SIM2 → Quectel #2 → DU2, with a shared CU and Open5GS. Each UE must obtain its own PDU session and laptop WWAN/IP path before MPTCP combines the transport paths. A shared PLMN does not enforce SIM-to-DU assignment; validate cell selection and the actual serving cell. DU2, simultaneous registration and the two IP paths are not yet verified. Existing DU1 E2/KPM reception remains complete; dual-DU/per-UE FlexRIC collection is the later extension.

### Socket layout

| Interface | Local endpoints |
|---|---|
| N2 / SCTP | CU `127.0.0.1` ↔ AMF `127.0.0.5:38412` |
| F1-C / SCTP | DU `127.0.10.2` ↔ CU `127.0.10.1:38472` |
| F1-U / GTP-U | DU `127.0.10.2:2152` ↔ CU `127.0.10.1:2152` |
| N3 / GTP-U | CU `127.0.0.1:2152` ↔ UPF `127.0.0.7:2152` |
| N4 / PFCP | SMF `127.0.0.4:8805` ↔ UPF `127.0.0.7:8805` |
| E2 / SCTP | DU `127.0.0.1:<ephemeral>` ↔ FlexRIC `127.0.0.1:36421` |
| E42 / SCTP | C xApp ↔ FlexRIC `127.0.0.1:36422` |
| Local application IP | Spark `10.45.0.1` ↔ currently allocated UE `10.45.0.x` |

An SMF GTP-U listener can also exist at `127.0.0.4:2152`; it is distinct from the four recorded user-plane endpoints.

## Successful session and resolved issues

Verified in the reported session: USB 3/UHD; CU/DU startup; N2/F1-C and F1-U/N3 sockets; private n78 SSB scan; PRACH/RAR; PUSCH CRC OK and strong SINR; NR5G-only / SA-only / private cell lock; SA registration/authentication; attached packet service; subscriber/DNN; IPv4 PDU/IP allocation; connected bearer; manual WWAN configuration; private application traffic.

The active bearer example was `wwan0`, `10.45.0.2/30`, gateway `10.45.0.1`, MTU 1400. Modem/bearer IDs, QMI/AT port numbers and UE IP can change and must be queried. An EPS initial bearer display of `ipv4v6` is not evidence about the active IPv4 PDU bearer.

The first 10-second TCP uplink reported sender 7.50 MBytes / 6.29 Mbit/s / Retr 0, receiver 6.50 MBytes / 5.09 Mbit/s, instantaneous approximately 3.1–9.4 Mbit/s. This proves functional user traffic, not optimized throughput or sustained stability. These are historical 3750-MHz results. The 2026-10-12 3660-MHz uplink checkpoint above supersedes them for current operation; reverse ping, downlink, UDP, and video are outside the current uplink-only scope.

Confirmed repairs: NRF `999/70` → `001/01`; missing subscriber provisioned; private SA cell selection/lock; subscriber type 3 → 1 after IPv4v6 rejection; host performance improvements; actual static WWAN settings applied. See the [chronological troubleshooting record](troubleshooting/2026-10-05_sa_bringup.md) for evidence and ruled-out hypotheses.

The **2026-10-07 FlexRIC session** verified all ten SA services active, CU N2 connected, DU F1 connected, E2 Setup accepted and KPM function ID 2 registered. After the codec update, the xApp completed subscription and deletion. A subsequent run received repeated actual gNB-DU UE ID `14` reports containing all five metrics and exited with `Test xApp run SUCCESSFULLY`. Traffic direction, application rate and duration were not recorded alongside these KPM excerpts, so they do not replace the 2026-10-05 application benchmark. Separate offline tests with synthetic messages checked new FlexRIC Format 4 subscriptions against the existing OCUDU decoder and OCUDU Format 3 indications against the new FlexRIC decoder.

A later installed-monitor run verified the repaired timestamp display with actual UE ID `2`, 12 report-age values of 499–717 microseconds, all five measurement names and normal subscription deletion/exit. Application sender/receiver results and precise report cadence remain unrecorded for this run.

## Host performance and remaining work

`ocudu_performance` was applied with Y/Y/Y: 20 CPU governors set to performance, DRM KMS polling disabled, four network-buffer settings set to 33554432. CU/DU run with sudo in the reproduction procedure. A historical sampled post-tuning check saw underflow 0, late 1. The 2026-10-12 run later showed recurring underflow growth, so that earlier sample does not establish current stability. The script's network-buffer settings target Ethernet USRPs; the B210 improvement was not isolated to that setting.

Kernel replacement, PREEMPT_RT, boot parameters, CPU isolation, IRQ pinning and hugepage changes were not part of this repair. Earlier privilege warnings alone were non-blocking; recurring RF real-time failures required host tuning. Check runtime settings after reboot and monitor sustained error growth.

Next dual-link sequence: add/verify both matching Open5GS records (SST 1, `internet`, IPv4 type 1 and checked SQN representation) → prepare distinct DU/cell/radio identities and CU + DU1 + DU2 → confirm each modem's intended cell and registration → independent PDU sessions, WWAN interfaces and IP paths → MPTCP → extend verified DU1 FlexRIC collection to per-DU/per-UE telemetry → AI predictor/steering → blockage/QoE experiments.

The historical single-link checkpoint is uplink only: the 30-second TCP transfer and five-metric delivery passed. Current Dual UE functional verification retains subscriber/bearer identity, independent IP paths, UL/KPM timing and concurrent traffic, with underflow remediation deferred. Cold-start, full repeatability/comparative UDP and bidirectional disturbance testing are supplemental experiments, not current acceptance or merge criteria. Application DL and mixed-direction tests remain outside the original UL scope. SIM preparation alone does not validate the dual RAN.

Follow the [Full Reproduction Runbook](runbooks/full_reproduction_runbook.md), or its [Spark](single_ue/spark_quick_commands.md) and [UE laptop](single_ue/ue_laptop_quick_commands.md) command summaries. Shutdown order is traffic/xApp → PDU → laptop WWAN → DU → FlexRIC → CU → 5GC → optional MongoDB. Check runtime state before operation; keep SIM secrets and raw INFO logs out of Git.
