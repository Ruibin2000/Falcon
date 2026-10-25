# DU RF Measurement Contract Review — October 21, 2026

Plan 1, Step 3. Static candidate review is complete under the reviewer-deferred
concurrency scope. The corrected admission translation unit passed a syntax-only
compile using the user-approved existing CMake recipe. Full builds, automated
regressions, and Step 6 acceptance are not run.

## Scope and revisions

| Repository | Branch and inspected HEAD | Changes |
| --- | --- | --- |
| Falcon | `E2SM-KPM`, starting at `e8ddfa74eb72491508c06c259918abaa29ed961b` | Recorded the reviewer decision, updated Step 3 progress and the deferred test row, and regenerated the cumulative RF patch. |
| OCUDU | `E2SM-KPM`, `4cffc0479f9620f668a7ac79aeb314b2e31525e4` | Read-only source review; all five RF targets and `apps/du/du.cpp` remain unchanged at HEAD. |
| FlexRIC | `falcon-xapp`, `10b8ec79d0f011902d329b2ed37f33f8b101b591` | Read-only applicability/status checks; timestamp repair remains committed and unchanged. |

The [reviewer decision](2026-10-19_du_rf_metrics_patch_review_and_snapshot_design.md#decision)
defers snapshot synchronization, generation/source-trace correlation, and the
snapshot-concurrency acceptance row. Neither design A nor design B is selected.
No mutex, generation, cleanup relocation, or E2-receive executor change was
implemented. The remaining [measurement contract](../../plans/e2sm-kpm-du-rf-metrics.md#measurement-contract)
still applies. RSRQ remains a local `n/a` capability notice only.

## Candidate identity and scratch correction

Artifact: `patches/ocudu/050a2bb-du-rf-metrics.patch`.

| Version | SHA-256 |
| --- | --- |
| October 19 input | `8ce25f800d9f1b875d3610aa77bb37b686139a5e0b845d20a7d2bfe9db281f44` |
| October 21 reviewed candidate | `eb5527d1aec0e88853bc15c966d7a663506256def77eb811c34c59367753f992` |

Review found one admission gap beyond the previously reviewed Style 4 path.
`process_action_definition_format3()` has a separate condition loop. Requests
with no measurement-label condition bypassed metric-specific validation;
duplicate `NO_LABEL` conditions passed individually. Cell-scoped RF requests
could also bypass the RF restriction when no label was checked
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_impl.cpp:153`). The production packer
advertises UE metrics in Style 3, so this path is reachable
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_asn1_packer.cpp:122`).

The only correction to the original candidate adds an RF-only Format 3 guard
in `lib/e2/e2sm/e2sm_kpm/e2sm_kpm_impl.cpp`: reject cell scope and require exactly
one condition of type `meas_label`. The existing provider then validates that
label as true, unexpanded `NO_LABEL`. Additional UE-selection test conditions
retain their existing handling; they are not measurement labels. Style 3
collection extracts only measurement-label entries from the condition list
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:320`).

The patch still targets exactly the original five production files. The other
four patched files are byte-identical to the original candidate. No native
tests, application source, executor code, ASN.1 schema, or unrelated metric
behavior was added to this cumulative patch. The regenerated patch was applied
only to scratch copies, with all five outputs compared byte for byte against
the corrected candidate.

## Remaining contract review

`SCRATCH` citations refer to `candidate/` in the retained evidence directory;
`OCUDU` citations refer to the unmodified effective baseline above.

| Requirement | Static finding and evidence |
| --- | --- |
| Requested UE mapping | The RF getter translates each requested CU UE F1AP ID, rejects an invalid index, and searches the snapshot by `ue_index`; it uses neither a vector offset nor the first UE. `SCRATCH:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:409`. |
| Request order/cardinality | Each requested UE starts with `noValue` and appends one record. Wrong UE types, missing mappings, and absent snapshots preserve position. Same getter at lines 405-428; production missing-mapping behavior at `OCUDU:lib/f1ap/du/f1ap_du_impl.cpp:619`. |
| REAL, finite zero, missing/non-finite values | Finite scheduler floats are promoted to REAL without integer conversion. NaN/infinity remain `noValue`; finite zero is valid. Same getter at lines 418-422. |
| SNR validity and scheduler semantics | SNR additionally requires `nof_pusch_snr_reports > 0`. The snapshot field defaults to zero and copies the existing scheduler count. Existing means, absent-RSRP sentinel, failed-CRC sample accumulation, and reset behavior are retained. See the patch and `OCUDU:lib/scheduler/logging/scheduler_metrics_handler.cpp:153`. |
| Label and scope admission/collection | RF provider admission requires UE scope, no cell scope, and true unexpanded `NO_LABEL`. Collection requires exactly one label. The existing shared action-list guard covers Styles 1/2/4/5; the scratch correction closes the separate Style 3 gap. |
| Names and advertisement | Dummy RSRP/RSRQ registrations and the incorrect RSRQ getter are replaced by the two exact vendor names at UE scope. The production supported-level lists feed the RAN-function packer. Capability decoding remains a required Step 5/6 regression, not a result of this static review. |

## Validation and evidence

Persistent evidence:
`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step3-review-20261021-6e3yqixn/`.
It retains baseline/scratch copies, input/reviewed patches, command transcripts,
exit statuses, and `review-summary.json`. Scratch preparation used
`/tmp/falcon-plan1-step3-20261021-6e3yqixn/`; the persistent copy is the handoff
evidence.

- Passed: `git -C /home/nyu/ocudu apply --check /home/nyu/Desktop/Falcon_repo/Falcon/patches/ocudu/050a2bb-du-rf-metrics.patch`.
- Passed: the existing FlexRIC cumulative patch's read-only `git apply --check`.
- Passed: strict patch whitespace checks and independent scratch application;
  all five resulting source files matched the corrected candidate byte for byte.
- Passed: source-target comparisons against HEAD, unchanged OCUDU/FlexRIC
  status, and final `git diff --check`.
- Passed: `cell_scope` is a local variable in
  `process_action_definition_format3()` and `logger` is an
  `ocudulog::basic_logger&` member of `e2sm_kpm_impl`.
- Passed: one `nice -n 19 /usr/bin/clang++-18` syntax-only compile of the corrected
  scratch `e2sm_kpm_impl.cpp`, with exit 0 and empty stdout/stderr. The requested
  `build/compile_commands.json` was absent. The user explicitly approved using
  the existing `build.make` recipe and `flags.make` instead. Compiler, macros,
  include paths, and compilation flags were preserved; object/dependency output
  options were removed and `-fsyntax-only` was added. Unchanged same-directory
  headers were copied into the isolated syntax stage for quoted includes.
  No file was written to the OCUDU checkout or build directory.
- Passed: `git status --short` confirmed the review document at
  `docs/e2sm-kpm/2026-10-21_du_rf_metrics_contract_review.md`; no stray `home/`
  directory existed inside Falcon. Exact commands, scope evidence, process
  checks, outputs, and `summary.json` are retained in
  `syntax-check-5gsxrmd5/` under the persistent evidence directory above.
- Resolved formatting check: initial `git diff --check` exited 2 because the
  new patch hunk included an unchanged blank context line with one space.
  Omitting that context line and adjusting the hunk range preserved every
  applied source byte; the final whitespace and applicability checks passed.
- Full builds and automated tests: **Not run**. No service, hardware, traffic, or
  deployment operation was performed. No patch was applied to either checkout.

The first five Step 3 implementation boxes record completed static review under
the revised scope. The two deferred boxes and the snapshot-concurrency row are
not passes. Steps 7-11 and the October 19 daily log remain unchanged. Steps 4-6
remain pending their own review, runner proposals, manifest, and execution.

## Required follow-up coverage

Retain all 13 original standalone cases and add production capability decoding,
conversion/admission coverage, and the planned native cases in Step 5. Include
Style 3 cases for both RF names: missing/duplicate labels, test-condition-only
requests, cell scope, expanded labels, and one valid `NO_LABEL` with optional
supported UE-selection conditions. Also add explicit failed-CRC RF averaging
and count/reset coverage, and removal of a translator mapping while an old
scheduler snapshot remains. These are test requirements, not executed results.

The decoded monitor trace remains useful for wire/output verification, but no
generation-based or concurrent-snapshot guarantee is claimed. Unchanged
generation-dependent requirements in later plan steps remain unresolved until
review before deployment authorization. The Plan 2 Stage A/hardware-slot gate
still applies, and work must stop before Step 7.
