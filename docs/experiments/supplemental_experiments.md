# Dual UE Supplemental Experiments

Updated: 2026-10-30. Developer: Ruibin.

Use the [current radio design](../project_design_and_progress.md): DU1 at
3660 MHz / 20 MHz OTA and DU2 at 9250 MHz / 40 MHz OTA through Pi-Radio,
with a 3600-MHz logical n78 interface. DU2's ongoing configuration uses the
modified FR3 hardware and tuned TX 60 / RX 10. The October 29 connection
checkpoint used direct radio without Pi-Radio and remains historical. Keep
RF mode, gains and bandwidths explicit in comparisons. The two cells have
different capacities (51 / 106 PRBs), so equal raw throughput is not an
acceptance expectation. Earlier dual-20-MHz results retain their original scope.

Cold-start reproduction, full repeatability/comparative testing and bidirectional
link-loss/recovery are follow-up experimental requirements. By operator decision,
they are excluded from acceptance criteria and merge prerequisites for the
current Dual UE development scope. Track their results separately from the
verified functional baseline. No completion is claimed by moving them here.

| Experiment | Status | Effect on current acceptance and merging |
| --- | --- | --- |
| Cold-start reproduction | To be performed | Nonblocking |
| Full repeatability and comparative testing | To be performed | Nonblocking |
| Bidirectional link-loss and recovery with survivor traffic | To be performed | Nonblocking |

## 1 Cold Start Reproduction

Restart Spark, the Laptop and the modems, then restore both links using the
documented startup procedure. Record whether the configuration survives restart
and which preparation steps are required.

- Record source/configuration revisions, service readiness, `ogstun_1` and
  `ogstun_2` addresses/MTUs, and the startup order.
- Select each modem by IMEI and verify its SIM and actual serving cell. A cell
  lock may need restoration after a power cycle; retain the query/readback.
- Record fresh PDU/bearer/IP/WWAN state, routing tables, Wi-Fi fallback guards,
  source-bound and ordinary ping, and both links' traffic/KPM observations.
- Save startup logs, summaries and timings as a new experiment. Existing warm
  startup and recovery results do not establish cold-start reproducibility.

## 2 Full Repeatability and Comparative Testing

Hold gains, antenna positions/attenuation, software and configuration fixed.
Compare each link alone, with the other DU transmitting idle, and with both links
carrying UL traffic. The original experimental recipe is three 60-second trials
per case; finalize the offered loads and comparison targets before a future run.

- Record receiver goodput, TCP retransmissions, controlled-rate UDP loss/jitter,
  SA/PDU continuity, serving cells and the actual IP/interface allocations.
- Compare the same offered load across the isolated and concurrent cases.
  The earlier recipe used at most 70% of measured solo capacity for UDP; its
  numerical comparison targets are not current development acceptance criteria.
- Retain available PHY/modem quality, CRC/BLER, USB/radio error counts, process
  status and host load. Keep unavailable observations explicit.
- Include planned RIC/DU restart reproductions and fresh identity/KPM collection.
  Wait for normal subscription cleanup and use the documented startup order;
  automatic RIC reconnection/late-DU joining is not assumed.
- Keep each repetition's configuration, offered load, timestamps and raw results
  so a later report can compare trials without selecting only favorable runs.

## 3 Bidirectional Link Loss and Recovery

Disturb UE2 / FR3 while UE1 / FR1 continues a recorded traffic stream; restore
UE2 and then repeat with the roles reversed. Record both the disturbed path and
the survivor throughout each cycle.

- Timestamp the disturbance and restoration, including any DU gain changes.
- Record survivor throughput/ping/KPM and whether its PDU/IP changes.
- Record the disturbed UE's registration, serving-cell selection, PDU release/
  reuse, current allocation and routing rebuild. Update changed F1/NGAP IDs and
  check fresh identity/KPM attribution after recovery.
- Where a host route/bearer is deliberately removed, record route lookups and
  counters/captures showing the affected traffic cannot fall back to management
  Wi-Fi or the other modem. Retain ordinary and source-bound ping results.
- If measuring MPTCP/video continuity, also retain transport/subflow and player
  traces from that same run. Radio/PDU recovery alone does not measure video QoE.

Two UE2 recovery cycles are already documented in the
[October 24 report](reports/ue2_fr3_recovery_experiment_report_2026-10-24.md).
The complete symmetric disturbance/survivor experiment remains to be performed.
The earlier [bidirectional idle/resume trial](reports/ue_identity_dual_ue_live_2026-10-21.md)
retains its measured identity-association scope.

Use the [Spark commands](../spark_quick_commands.md),
[manual Laptop commands](../operations/manual_laptop_startup.md) and
[automatic reconnect guide](../laptop_reconnect_quick_start.md).
Stop experiment traffic and finish xApp cleanup, complete both UE shutdowns,
then stop the DUs, CU and core. Preserve each run's evidence before clearing
temporary directories or restarting the hosts.
