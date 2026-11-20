# Workspace Instructions

## Documentation language

- Write all new or maintained documentation in English, even when the user
  communicates in another language. This includes READMEs, runbooks, design
  notes, reports, tables, figure captions, command explanations, example shell
  prompts, and agent instructions.
- When updating a document that contains Chinese prose, rewrite that prose in
  English and update its internal and incoming section links. Preserve command
  behavior, technical values, units, evidence, and historical validation scope.
- Preserve verbatim raw logs, protocol output, captured transcripts, and
  third-party source or fixtures. Do not translate or edit evidence to satisfy
  the documentation language rule.
- Follow the additional instructions in `dev_logs/AGENTS.md` for daily logs.

## Configuration and evidence

- The accepted wired DU2 profile is maintained in
  `configs/ocudu/dual_fr1/du2_b210_n78_20mhz_wired.yml`. Keep the Spark and Laptop
  wired runbooks and entry points consistent with that profile. Documentation
  maintenance must not silently retune the accepted radio parameters.
- Keep the dual-DU, DU1-only, wired DU2, and optional CUDA profiles distinct.
  An obsolete diagnostic candidate is not a replacement for a maintained
  profile. Preserve unrelated existing work when cleaning up an experiment.
  Treat operator-confirmed deployed gains as experiment records; synchronize
  maintained templates to those confirmed values rather than assuming a
  template/deployment difference is an obsolete debug setting.
- Before deleting intermediate exports, verify that the final retained evidence
  contains the required data. Keep final raw evidence, configuration snapshots,
  summaries, and provenance under the ignored `docs/experiments/evidence/`
  archive. Use `docs/experiments/records/` for local maintenance records.
- Do not delete running processes' files, build dependencies, deployed plugins,
  or historical evidence as generic cleanup. Do not publish raw Core security
  material or SIM credentials.

## Operation and validation

- A request for commands means provide commands without executing the live
  experiment. Repository edits, read-only inspection, and offline checks are
  separate from starting or stopping RAN/Core services, accessing Laptop
  hardware, changing runtime gains, or running traffic.
- Validate changed runbook shell syntax and links, scan maintained documents
  for Chinese prose, and run relevant existing offline checks. Configuration
  parsing or simulated tests do not establish live RF or throughput acceptance.
