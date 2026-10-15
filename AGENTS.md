# Repository Instructions

## Scope

The source code and documentation rules below apply to work on the `E2SM-KPM`
branch in the paired repositories:

- Falcon: `/home/nyu/Desktop/Falcon_repo/Falcon`
- ocudu: `/home/nyu/ocudu`

Check the current branch and working-tree changes in each repository before
editing it. Preserve unrelated user changes.

This root file consolidates the repository and development log instructions.
The daily development log instructions apply to all log creation and update
requests, regardless of branch.

## Source Code and Existing Documentation

- Source code, tests, scripts, build files, and runtime configuration may be
  changed as needed for the requested implementation.
- Preserve all explanatory documents that exist when a task begins. Do not
  edit, delete, rename, move, or reformat existing README files, technical
  documentation, runbooks, plans, or changelogs in either repository.
- Changes to behavior, corrections, and additional explanations belong in new
  documents. Do not update an existing document or its index to link them.
- Development log reports may be created and updated under the rules below.
  Agent instruction files may be changed when the user explicitly requests
  instruction changes. These exceptions do not authorize
  changes to other explanatory documents or logging conventions.

## New Technical Documentation

- Store new technical documentation for both repositories only in Falcon,
  under `docs/e2sm-kpm/`. Do not create technical documentation in ocudu.
- Use a new descriptive filename such as `YYYY-MM-DD_<topic>.md`. If that path
  already exists, choose a distinct suffix instead of overwriting it. A document
  created during the current task may be refined before the task is finished.
- Write documentation in US English. Identify the affected repository, branch,
  source paths, implementation changes, usage, validation, and known limitations.
- Link to existing documentation as context while leaving its contents intact.

## Development Logs

- Record implementation changes in Falcon's `dev_logs/`, including work in
  ocudu. Identify each repository and its affected paths separately.
- Create or update development log reports after implementation and validation;
  include links to any new technical documents and the actual validation results.
- Existing development reports may be updated while preserving their identity
  and history. Do not use an existing README, technical document, or upstream
  `CHANGELOG` as the development log.

## Daily Development Log Instructions

When creating or updating a daily development log in `dev_logs/`, read and
follow [dev_logs/PROMPT_CONVENTION.md](dev_logs/PROMPT_CONVENTION.md) for the
full workflow, report template, naming rules, and evidence requirements.

Before drafting or saving, identify the target and state whether the operation
will create a new log or update an existing log.

- **Create:** each new log requires a fresh developer-name response through the
  client's input dialog (`request_user_input_async`, or an available equivalent).
  Ask exactly: "What developer name should appear in this daily development log?"
  Use free-text input with no suggested names and wait for a non-empty answer.
  If no dialog tool is available, ask in chat and wait. Never reuse a name from
  a previous creation, Git, the operating system, or earlier logs.
- **Update:** read the developer name from the existing target log and preserve
  it. Do not request the name again. If the target is ambiguous, ask which log
  to update; do not ask the user to re-enter their name.

Record `Created at`, `Last updated at`, `Last operation`, and the save history.
Use New York time (`America/New_York`) and the 24-hour clock (hours `00`–`23`)
for reporting dates and save timestamps. Display save timestamps as
`HH : MM: SS Mon D, YYYY EDT/EST`, for example `00 : 25: 41 Oct 11, 2026 EDT`.
Use the applicable EDT or EST abbreviation for that instant; never use AM/PM.
An explicit display-format migration preserves recorded instants and history.
Preserve `Created at` on updates; use `Not recorded` for missing historical
creation times.

Write all log content in English and use the required template and naming rules.
Instruction maintenance does not itself require a new daily log or a
developer-name prompt.
