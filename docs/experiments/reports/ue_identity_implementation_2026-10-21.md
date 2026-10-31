# Standalone UE identity xApp: first implementation milestone

> Publication: This report and its selected figures are versioned. Detailed
> captures, logs and per-sample data remain in the local evidence archive.
> References marked `local archive` and captured-data reanalysis commands
> require that archive separately. See the [publication policy](../README.md#local-archive-policy).

> Historical scope: this record retains its dated implementation, test
> configuration and results. The [current two-link design](../../project_design_and_progress.md)
> defines DU1 3660 MHz / 20 MHz, DU2 3600-MHz n78 interface / 40 MHz, and
> the designed Pi-Radio 9250-MHz OTA path. Those later radio changes are
> outside this record's validation.

Developer: Ruibin Chen. Date: October 21, 2026, America/New_York.

Both Falcon and OCUDU are on `Dual-UE`. The first local implementation is built
and passes offline verification. Plan 4 remains open: strict serving-DU proof
and full lifecycle/recovery acceptance remain open. No RAN/Core/RIC services
were restarted or candidate artifacts deployed during the initial local
milestone. Subsequent operator-started live trials pass experimental
single/dual-UE association and UL; see the
[dual-UE live report](ue_identity_dual_ue_live_2026-10-21.md).

| Repository | Implementation baseline |
| --- | --- |
| Falcon | `6dcde7ec1f97861cd8f3e9b4b2cc23208682d2ef` |
| OCUDU | `c9d695dfaba8e894bae8c9d95aa1b7e6437c7fc1` |
| FlexRIC SDK | `10b8ec79d0f011902d329b2ed37f33f8b101b591`, existing local build objects |

Changes are uncommitted working-tree changes. The retained
[OCUDU patch](../../../patches/ocudu/c9d695df-ue-identity-cu.patch) captures this
milestone against its exact baseline, including the new public identity header.
Do not apply it again to the already-modified OCUDU working tree. The
artifact manifest (local archive: `../evidence/2026-10-21_ue_identity/manifest.json`) records
candidate hashes and configuration/source provenance.

## Implemented changes

OCUDU now exposes read-only NGAP/F1 identity getters and joins them with actual
serving DU information in an owned CU-CP metrics snapshot. Collection runs on
the CU control executor and defaults off. Incomplete, disconnected, releasing
or reconfiguring contexts are withheld. NGAP tracks whether GUAMI has actually
been supplied; missing identity never becomes zero-valued identity. Shared
CU measurement snapshots are protected between metrics and E2 executors.

The CU KPM provider implements per-UE standard `UEID-GNB`, connected-UE matching
and an admitted-DRB SST equality filter, with a real vendor RRC-state gauge.
State expiry and no-value behavior are explicit. Full gNB UEID equality was
required for repeated collection: the earlier utility compared DU UEIDs only.
The new comparison includes GUAMI, F1/E1 lists and optional fields via canonical
ASN.1 encoding. Existing DU KPM remains intact.

Falcon adds an independent C FlexRIC collector and Python coordinator. SDK data
is copied to owned, bounded serialized queues before callbacks return; HTTP
runs in a separate polling thread. Canonical identifiers, endpoint/GUAMI scope,
pagination completeness, session selection, expiry, conflict/reuse and loss
handling feed a separately versioned diagnostic NDJSON schema. Original base5
values, units, zero/no-value and incomplete flags are preserved. SUPI is an
internal Core join key and is not required in downstream output.

Independent codec verification exposed a FlexRIC decoder assertion on legal
positive 40-bit AMF IDs with a sixth sign octet. A
[minimal patch](../../../patches/flexric/ue_identity_amf_40bit.patch) and isolated
plugin builder are retained in Falcon. The builder reads existing SDK objects
and relinks a candidate plugin outside the SDK tree; installed artifacts are
unchanged. Candidate RIC and xApp configs both select this plugin, because RIC
also decodes indications. These configs target the KPM-only testbed. Existing
timestamp conversion is preserved. Existing SDK objects
still produce executable-stack linker warnings.

Root README, accepted DU monitor/build scripts, Plan 2, CU-UP packet handling,
DU PHY/MAC/RLC behavior, and Core sources/policies were not modified.

## Retained local verification

| Check | Result / evidence |
| --- | --- |
| Candidate CU and five native targets | Build passes; build log (local archive: `../evidence/2026-10-21_ue_identity/build_ocudu.log`) |
| Independent collector/plugin | Build passes; build log (local archive: `../evidence/2026-10-21_ue_identity/build_xapp.log`) |
| KPM native suite | 7 pass, including 3 new CU identity tests; log (local archive: `../evidence/2026-10-21_ue_identity/kpm_native.log`) |
| CU periodic metrics suite | 1 pass; log (local archive: `../evidence/2026-10-21_ue_identity/cu_metrics_native.log`) |
| NGAP suite | 87 pass, including owned snapshot/40-bit ID/setup/release checks; log (local archive: `../evidence/2026-10-21_ue_identity/ngap_native.log`) |
| F1AP CU suite | 30 pass, including unequal CU/DU F1 IDs and withdrawal at release-start; log (local archive: `../evidence/2026-10-21_ue_identity/f1ap_native.log`) |
| Python suite | 30 pass, zero skips; log (local archive: `../evidence/2026-10-21_ue_identity/python.log`) |
| Config parsing/autoderivation | Candidate overlay with real CU config passes `--dryrun`; log (local archive: `../evidence/2026-10-21_ue_identity/cu_dryrun.log`) |
| Working-tree whitespace | `git diff --check` passes in both repositories |

The Python suite covers strict versus explicit experimental mode, independent
OCUDU-to-FlexRIC decoding, large and zero IDs, dual UE and 64 simultaneous
synthetic contexts, asynchronous arrival/rates, old headers, monotonic expiry,
Core errors, incomplete pages, bad session state, multiple sessions, missing
versus explicit unavailable CU state, same F1 ID across DUs, known reuse and
bounded-queue loss. These fixtures are not live RAN/Core measurements.

The [synthetic codec bytes](../../../tests/ue_identity/fixtures/cu_codec.json) were
generated by OCUDU's native encoder. The isolated FlexRIC decoder retains
AMF IDs `549755813888` / `549755813889`, GUAMI 001/01 + 2/1/0, F1 IDs 1007/1008,
and real state 1. The fixture NTP header becomes Unix `100000000` microseconds.
The decoder-only command supplies a synthetic E2 node identity.

The [synthetic replay](../../../tests/ue_identity/fixtures/dual_replay.ndjson)
produces four DU rows in each mode. Strict output always has null IPs;
experimental final rows map DU1/F1 1007 to `10.45.0.10` and DU2/F1 2007 to
`10.46.0.10`. Retained strict output (local archive: `../evidence/2026-10-21_ue_identity/replay_strict.ndjson`)
and experimental output (local archive: `../evidence/2026-10-21_ue_identity/replay_observed.ndjson`)
are labelled by filename and schema. These addresses are fixture values.

The actual read-only Core probe returned **connection refused** at
`127.0.0.5:9090/ue-info`; the probe exits before SMF when AMF fails. No real
SMF response or endpoint schema/pagination/state/GUAMI association was verified.
The installed AMF/SMF package is `2.8.0~noble5`; endpoint strings in its binaries
do not establish runtime API availability.

## Open gates and design boundary

The CU local snapshot contains serving DU ID, but standard `UEID-GNB` does not
carry that explicit per-UE DU association or a shared lifecycle generation.
Local F1 allocation is per DU. Therefore default strict mode deliberately emits
unresolved/null IP, even with an otherwise complete observed relation.
`--observed-unique` is a separate lab mode with
`assurance: observed_unique_current_context`. Its uniqueness checks cannot
exclude unobserved conflicts, source restart or exact full-key reuse. Known
conflicts/reuse and ingress loss latch uncertainty; no traffic or timing
heuristic upgrades it to a proved match.

The remaining transport design must compare an explicit scoped E2 extension
or private lifecycle report against the standard-field gap. No CU allocator
redesign, private ID packed into a standard field, or additional wire model
has been introduced in this milestone. The default protects later consumers
from treating an observational join as a proved serving-DU binding.

Early DU samples are emitted unresolved immediately; pending/backfill and a
complete lifecycle stream are not implemented. Filtered row absence does not
mean release. Explicit unavailable/non-connected CU state withdraws that
candidate. Silence expires confidence; identifier history is not silently
evicted to permit uncertain reuse.

Next acceptance work is to verify real Core API behavior, retain actual CU E2
Setup/function definition/subscription/indications/deletion, establish explicit
DU/lifecycle evidence, then trace modem truth through single/dual UE traffic,
reattachment, source loss/restart and performance checks. Plan 4's live gates
remain unchecked. Plan 2 and actual MPX/MPTCP integration remain deferred.

Build, replay, live launch, output schema and rollback commands are in the
[standalone runbook](../../reference/ue_identity_xapp.md).

## Live continuation after Core startup

The earlier connection refusal occurred before the operator started Core; it
does not demonstrate an infoAPI defect. The operator then reported all ten SA
Core services active and ogstun UP with MTU 1400, both service addresses and
routes. Actual read-only AMF/SMF queries now return HTTP 200 with empty UE lists.
The new app's real `--probe-core` run returns status ok, zero AMF UEs, zero SMF
UEs and zero eligible radio contexts. Retained
live probe evidence (local archive: `../evidence/2026-10-21_ue_identity_live/01_core_empty_probe.json`)
establishes empty-response API availability/adapter compatibility only.
Nonempty identity fields and the full single/dual-UE mapping remain pending;
offline test counts above are not live acceptance evidence.

After UE1 access, populated live responses identify SUPI
`imsi-001010000000101`, AMF UE NGAP ID 6, RAN UE NGAP ID 5, gNB 411 and NCI
6733824. SMF reports active PDU Session 1, DNN internet and IPv4 `10.45.0.2`.
The actual CU log records that NGAP context's initial-context/PDU setup and
DU1/F1 CU UE ID 5. Retained
Core snapshot (local archive: `../evidence/2026-10-21_ue_identity_live/05_core_ue1_snapshot.json`)
and CU excerpts (local archive: `../evidence/2026-10-21_ue_identity_live/05_cu_ue1_identity_excerpt.log`)
support this observation. Laptop bearer/route/ping truth and actual CU/DU UE
indications remain separate pending checks. A DU1-only runtime configuration
and optional decoded-input capture were added for the staged live xApp trial.

The operator then supplied Laptop bearer 1 with connected, non-suspended
internet/IPv4, `10.45.0.2/30`, gateway `10.45.0.1`, interface wwan0 and MTU
1400. The source-bound route selects wwan0/table 151, and ping to the Spark
service address receives 5/5 replies. This independently agrees with SMF's IP.
The operator-provided path evidence (local archive: `../evidence/2026-10-21_ue_identity_live/06_laptop_ue1_path.json`)
establishes this single-UE path check; it does not establish throughput or E2
UE-report/mapping acceptance.

The subsequent 60-second real xApp trial received 57 CU and 58 DU1 indications
and 60 Core snapshots. It emitted one initial unresolved row followed by 57
consecutive experimental matches for 10.45.0.2; both subscriptions were deleted
normally. The [single-UE live report](ue_identity_single_ue1_live_2026-10-21.md)
retains the actual identity chain and input/output hashes. Throughput/PRB stayed
zero, so sustained-load response remains the next check. This milestone does
not close strict DU/lifecycle or dual-UE acceptance.

The following sustained-UL trial records receiver goodput 13.8 Mbit/s and
iperf exit 0. Actual xApp inputs contain 117 CU and 118 DU1 indications plus
120 Core snapshots; 117 rows match UE1 IP, including 60 consecutive rows with
positive UL throughput. UL KPM peaks at 20.97 Mbit/s and UL PRB at 86%.
Both subscriptions are deleted normally and the xApp exits 0. The updated
[live report](ue_identity_single_ue1_live_2026-10-21.md) retains these results,
decoded inputs/output and the actual server log. Precise cross-host clock
alignment, strict serving-DU proof and full dual-UE/recovery/performance gates
remain pending. The operator reports the second B210 is not connected yet.

The operator subsequently connects B210 328B021, loads its standard UHD
firmware and starts DU2. Both radios enumerate at 5000 Mb/s on separate USB
controllers. DU2's PCI 2 / SSB 639648 / F1 / E2 startup passes. The subsequent
real dual-UE trial records three node subscriptions, 223 DU outputs and 221
correct observed matches, with one initial unresolved row per DU. All 223
metric payloads and all 221 matched Core/CU/DU/cell chains pass a retained
independent input audit. Both Laptop concurrent UL clients exit 0 with receiver
13.2/11.9 Mbit/s and Retr 1 each. Three subscription deletions and normal SDK
stop pass. The [dual-UE report](ue_identity_dual_ue_live_2026-10-21.md) retains
actual TXT, raw decoded events, NDJSON, Laptop operator truth and hashes.
Strict DU/lifecycle, recovery, cross-host clock alignment and repeated
performance comparison remain pending. Root README and Plan 2 stay unchanged.
