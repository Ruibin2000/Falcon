# PUSCH RF Metric Names

The DU advertises and reports `PUSCH.RSRP.dBFS` and `PUSCH.SNR.dB` after
this change. Subscriptions, decoded JSON keys, and formatted xApp output use
these exact names. The previous `FALCON.` prefix is removed from both RF
measurements. This is a wire contract change, replacing the earlier temporary
display alias.

Both measurements remain custom UE-level KPM measurements. RSRP remains
uplink PUSCH DM-RS power in software dBFS. SNR retains its existing
`ul_sinr_dB` source and dB unit. Averaging, sample availability, REAL and
`no_value` handling, UE identifiers, and the 1000 ms reporting period are
unchanged.

## Implementation

OCUDU branch `E2SM-KPM` changes the registered names in
`lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp`, the Format 1 and
Format 3 admission checks in `e2sm_kpm_impl.cpp`, and the native provider test
constants. Existing advertisement tests require the new names.

Falcon branch `E2SM-KPM` updates both RF subscription profiles, the cumulative
and RSRP-only OCUDU/FlexRIC patches, the native-test patch, and the matching
offline test and validator expectations. Existing negative tests also verify
that the retired prefixed names are absent from the RAN function description
and rejected by provider and subscription admission.

The FlexRIC checkout and installed codecs are unchanged. A new standalone
monitor was compiled from the updated Falcon patch. The generic identity
collector decodes the new names without a C source change. Its current
temporary Python view has matching unit entries and no display alias:
`/tmp/falcon-main-rf-xapp-43zlmkgp`.

Existing reports and captured experiment logs retain their original names.
Historical patch hashes and old fixtures describe their original versions;
use the new fixtures for the renamed contract. No daily development log was
created, as requested.

## Validation

All of the following passed locally:

- Rebuilt OCUDU targets `odu`, `odu_split_8`, and
  `e2sm_kpm_meas_provider_metrics_test` using `cmake --build` with two jobs.
- All 11 native provider tests and all 39 Python runner regression tests.
- All 17 cumulative RF provider tests and all 9 RSRP-only provider tests,
  including subscriptions encoded by the actual FlexRIC builder; final runs
  had no skipped tests.
- Both FlexRIC callback harnesses and the seven- and six-metric subscription
  round trips. New OCUDU APER fixtures and subscription bytes contain the
  unprefixed names and no `FALCON.PUSCH.` names.
- Identity collector decoding and JSON/TXT replay preserve the new names,
  units, negative REAL values, valid zero, and `no_value`. The replay assigns
  synthetic DU context for formatting and does not verify live IP binding.
- All five changed integration patches apply to their recorded baseline
  revisions, and both repositories pass `git diff --check`.

Commands, XML results, fixtures, callback output, and hashes are retained in
`/tmp/pusch-metric-rename-b9_qb3a7`. The new Split 8 binary is
`/home/nyu/ocudu/build/apps/du_split_8/odu`, SHA-256
`71233648d71dc78268935470665090b5680e12dfd7b05aeb181331e6a2baa92e`.
Live reception after this rename has not been tested.

## Current UE1 Test Startup

Stop the old xApp and DU1 through their original terminals, then restart DU1
with the rebuilt binary and the same working radio configuration:

```bash
bash /tmp/falcon-ue1-rf-live-o6yel1v9/run_component.sh du1
```

After DU1 completes F1-C and E2AP setup, run the current identity xApp view in
another Spark terminal:

```bash
bash /tmp/falcon-main-rf-xapp-43zlmkgp/run.sh
```

The running old DU continues to use its old names until restarted. A new-name
subscription requires the rebuilt DU. The current identity view still has no
CU identity feed, so unresolved IP binding remains expected. CU, RIC, and UE
connection scripts have no metric-name implementation changes. The alternative
`run_component.sh xapp` entry now uses the rebuilt standalone monitor; run one
xApp entry at a time for this test.

Context: [RF measurement semantics](../notes/e2sm_kpm_du_rf_metrics_semantics.md)
and [the original build and operator handoff](2026-10-23_du_rf_metrics_step7_build_and_step8_handoff.md).
