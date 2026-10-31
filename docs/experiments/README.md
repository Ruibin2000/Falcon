# Experiment Reports and Evidence

Use [Project Design and Progress](../project_design_and_progress.md) for current
status and the root quick guides for current commands. This directory retains
dated results with their original RF configuration and validation scope.

## Local Archive Policy

Experiment reports, evidence, run records and relocation manifests in this
directory are local files excluded by the repository `.gitignore`. Only this
index and `supplemental_experiments.md` are versioned. Artifact links in these
documents work when the corresponding local archive is present; the artifacts
are not delivered by a fresh clone.

Keep new run output here or in a root `artifacts/`, `captures/`, `evidence/`,
`logs/`, `outputs/`, `results/`, `runs/` or `tmp/` directory, which are also
ignored. The quick guides normally create run directories under `/tmp`,
outside the repository. Logs and packet captures (`*.log`, `*.log.*`,
`*.pcap`, `*.pcapng`) are ignored throughout the repository.

Maintained configuration, source code, synthetic test fixtures, curated
interface examples and development logs remain versioned. Automated tests do
not require this archive. Captured-input benchmarks require an explicit local
`--source-events` path.

Previously tracked experiment files have been removed from the Git index while
preserving the local archive. The next commit will remove them from the current
repository tree; this does not remove files from earlier Git history.

| Location | Contents |
| --- | --- |
| `reports/` | Readable experiment and implementation reports |
| `evidence/` | Captured logs, message archives, configuration snapshots, CSVs, plots and analysis helpers |
| `records/kpm/` | Dated RF/KPM source reviews, build/verification records and semantics trace |
| `records/bringup/` | Original SA/FlexRIC troubleshooting and timestamp repair |
| `records/networking/` | Historical two-subnet migration; current networking is in operations |
| [Supplemental experiments](supplemental_experiments.md) | Cold-start, repeatability and symmetric disturbance methods |

## Main Results

| Date | Report | Recorded scope |
| --- | --- | --- |
| October 13 | [Dual UL and KPM](reports/dual_ue_ul_experiment_report_2026-10-13.md) | Two direct n78 links, concurrent uplink and DU attribution |
| October 21 | [UE1 association](reports/ue_identity_single_ue1_live_2026-10-21.md), [dual association](reports/ue_identity_dual_ue_live_2026-10-21.md) | CU/DU/Core IP matching and idle/resume |
| October 23 | [MPTCP video](reports/mptcp_video_experiment_report_2026-10-23.md) | Primary/backup behavior on the earlier direct-radio setup |
| October 24 | [UE2 recovery](reports/ue2_fr3_recovery_experiment_report_2026-10-24.md) | Two measured gain disturbance/recovery cycles |
| October 25 | [100-ms reporting](reports/dual_ue_100ms_validation_report_2026-10-25.md), [27 metrics](reports/dual_ue_27kpm_stability_report_2026-10-25.md) | Direct-radio acquisition, explicit scope and full raw metrics |
| October 26 | [120-second delivery](reports/du27_app_subscription_live_2026-10-26.md), [six-minute delivery](reports/du27_app_subscription_6min_live_2026-10-26.md) | One independent subscriber; 2,400 / 7,200 reports received and written |

## Reading and Reproduction

The report links its matching evidence directory and analysis command. Preserve
raw logs, archives and recorded values. Historical manifests retain captured
source hashes and original source locations; these are provenance, not current
deployment settings. The reports and evidence moved together, preserving their
relative layout. The October 13 analysis helper now resolves its own directory;
its manifest records the previous analyzer hash and this portability change.
Three other helpers use the updated repository depth. The
[relocation record](documentation_relocation.json) preserves their original
and current hashes; recorded experiment inputs and outcomes are unchanged.

The old `FR3` label in the October 13–26 experiments denoted a direct n78 demo
path. Current DU2 uses 9.25-GHz OTA, 40 MHz and TX/RX 60/10 after hardware
modification. Earlier throughput/delivery results do not establish current FR3
end-to-end connectivity or sustained performance. New runs retain their own evidence.
