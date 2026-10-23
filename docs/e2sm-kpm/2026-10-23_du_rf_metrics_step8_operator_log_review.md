# DU RF Metrics Step 8 Operator Log Review

Date: October 23, 2026 (`America/New_York`). Startup and the seven-name
subscription are verified. Step 8 remains **Partial** because the live Setup
definition's advertised measurement list has not been captured/decoded.
Step 9 RF values and sustained reception are not accepted.

Context: [Plan 1](../../plans/e2sm-kpm-du-rf-metrics.md) and the
[Step 7 build / operator handoff](2026-10-23_du_rf_metrics_step7_build_and_step8_handoff.md).

## Repository and execution scope

At review time, Falcon was on `E2SM-KPM` at
`c0a199002b47ccb6374ab14ffd291bd0b86620ba`. The earlier handoff and plan
reporting edits were uncommitted; subsequent reporting commits are separate.
OCUDU remained on `E2SM-KPM` at
`4cffc0479f9620f668a7ac79aeb314b2e31525e4` with the same ten unstaged RF/native
files. FlexRIC remains strictly read-only on `falcon-xapp` at `10b8ec79`.
No source correction, build, install, service control, radio action, traffic
generation, commit or push was performed during this log review.

The operator supplied five directories under
`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/live/`:

| Capture | Recorded start, EDT | Observed result |
| --- | --- | --- |
| `core-0CQcbrD9` | 15:04:14 | Ten SA units individually active; `5GC active: 10/10`; command/logger exits 0/0 at 15:04:17. |
| `cu-iUm1uhD0` | 15:05:01 | N2 completed, F1 listener active, CU startup banner. Existing CU banner commit is `c9d695dfab`. |
| `ric-Cn13Prwc` | 15:05:30 | Setup from node 411, gNB-DU ID 1, printed PLMN `1.1`; RAN function 2 accepted. |
| `du-6K5ZKbc6` | 15:05:57 | PCI 1, 20 MHz, ARFCN 644000 / n78 / 3660 MHz, SSB 643680; F1 and E2 connected. |
| `xapp-hFZJFSCw` | 15:09:28 | Correct staged executable/config/trace switch; Format 4, 1000 ms, seven exact requested names; subscription successful. |

Core/CU readiness here does not establish UE registration or subscriber-data
correctness. CU, RIC, DU and xApp captures had no `finished-at.txt` or `status.txt`
at inspection; their exit codes are **Not recorded**. Neither missing status
files nor the tool environment's no-match `pgrep` results establish the current
host-service state. The agent did not act on the running services.
Before any further build, obtain host-visible process-check evidence from the
operator; the isolated tool environment's no-match results alone do not prove
that the real-time DU is idle.

## Retained snapshot and verified evidence

The bounded snapshot was recorded at **15:15:22 EDT** under:

`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step8-live-review-20261023-ltlwu4i6/`.

`review-summary.json` and `snapshots/<capture-name>/` retain copied bytes,
SHA-256, sizes and source timestamps. Original captures are preserved. Counts
refer to this snapshot, not a final session total. Application-log timestamp
strings have no timezone suffix; their raw `19:...` values are retained without
adding an assumed offset.

| Claim | Snapshot evidence |
| --- | --- |
| Core readiness | Core `output.log:2–12`, `status.txt`. |
| CU N2 and F1 startup | CU `output.log:4–6`. |
| Actual carrier and DU startup | DU `output.log:27–31`. |
| Live E2 Setup completed | DU `du-application.log:295–303`; RIC `output.log:20–21`. |
| Exact seven-name admission with `NO_LABEL` | DU `du-application.log:358–359`. |
| Actual xApp subscription accepted | xApp `output.log:35–37`; function 2 / request ID 1 / node 411. |

The xApp command used `FALCON_KPM_RF_TRACE=1`, the new evidence-local
`monitor-live/xapp_oran_moni`, and Falcon's `configs/flexric/xapp_du_rf_metrics.conf`.
Its output confirms `/usr/local/lib/flexric/` and loading `libkpm_sm.so`.
The seven admitted names match the five baseline names plus
`FALCON.PUSCH.RSRP.dBFS` and `FALCON.PUSCH.SNR.dB`. Admission does not prove
that any of those measurements has actually been returned.

## Missing evidence and RF warnings

- The snapshot contains **zero RF_TRACE rows**, no decoded UE/measurement/header
  observations, and no original-five metric values. No cadence, REAL/noValue,
  per-UE association or RF accuracy claim is established. The operator then
  confirmed that the UE is not attached or has no established data session.
  Zero rows under that condition do not establish an RF implementation failure.
- The operator confirmed there is no full Setup definition, PCAP or capability
  decoding file. The ordinary RIC acceptance line and DU function-ID/OID lines
  do not list advertised measurement names. The configuration and admitted-name
  list cannot substitute for the independent live advertisement evidence.
- The 16,384-byte DU application snapshot contains **52 complete underflow** and
  **18 complete late** warning lines, plus one truncated final warning line.
  Underflows already appear before subscription admission in the same log.
  These observations do not establish a new regression or its cause; RF
  stability remains unaccepted. No tuning or setting change was attempted.
- No actual subscription deletion, signal handling or normal xApp exit was
  observed. `monitoring until SIGINT/SIGTERM` is a waiting message. The earlier
  synthetic capture-helper test is not actual SDK lifecycle evidence.
- Step 9's two-decimal DU comparison remains blocked on a qualifying existing
  high-precision per-UE window output. No consumer or diagnostic hook was added
  or enabled. The reviewer-deferred concurrency limitation is unchanged.

Operator answers are retained in `operator-clarifications.json` in the review
directory. All three Step 8 operational/configuration checkboxes are supported;
the advertised-name exit criterion remains separately pending.

## Proposed minimal advertisement capture

The existing DU supports the following standard CLI options:

```bash
pcap --e2ap_enable true --e2ap_du_filename "$FALCON_RUN/e2ap.pcap"
```

Source: OCUDU
`apps/units/flexible_o_du/o_du_high/e2/o_du_high_e2_config_cli11_schema.cpp:12–22`.
The existing factory writes E2AP PDUs when enabled
(`apps/units/flexible_o_du/o_du_high/o_du_high_unit_pcap_factory.h:66–69`);
`lib/pcap/dlt_pcap_impl.cpp:96–98` labels the exported-PDU capture as `e2ap`.
This uses the existing capture facility and requires no code patch or install.

The proposed options, combined with the same 3660-MHz configuration and log
override, passed **parse-only `--dryrun`, exit 0**, at 15:17:57 EDT. Neither a
PCAP nor application-log file was created. Exact command/output/status are in
`proposed-pcap-cli.*` under the review directory. Capture is **not enabled in
the current DU**, and no restart was performed.

Because the existing Setup already happened, a fresh capture must begin with a
new operator-controlled DU startup. Prepare a fresh capture directory, then
use this command only after agreeing the restart and allowing the current xApp
to delete its subscription:

```bash
falcon_capture "$FALCON_RUN" sudo stdbuf -oL -eL \
  /home/nyu/ocudu/build/apps/du_split_8/odu \
  -c /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml \
  pcap --e2ap_enable true --e2ap_du_filename "$FALCON_RUN/e2ap.pcap" \
  log --filename "$FALCON_RUN/du-application.log"
```

Retain and decode the captured Setup definition before marking the final Step 8
gate complete. Capture/decoding has not run. The agent is waiting for the
operator's decision; it will not restart services or enable capture itself.
