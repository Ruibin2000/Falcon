# Daily Development Log Prompt Convention

## Purpose

Create consistent, evidence-based daily development reports for this repository.
All reports must be written in English, even when the request is in another language.
This file defines instructions for the assistant; it does not implement a standalone UI.

## Required Workflow

1. Determine the reporting date from the user's request. Otherwise, use the
   current date in New York (`America/New_York`). A daily log covers that New York
   calendar day. Use the 24-hour clock for report times; do not assume the
   execution host's date or timezone.
2. **Resolve the target and operation before drafting.** Inspect existing logs
   and use the user's requested file, date, or conversation context to identify
   whether this will create a new report or update an existing one. State the
   operation and target path to the user before saving. For an update, preserve
   the reporting date and developer already recorded in the target. If several
   existing logs could be the target, ask which file to update. If an explicitly
   requested update has no matching report, explain this and ask whether to
   create one instead; do not silently create a new report.
3. **Confirm the developer's name for each new report only.** For a creation,
   open an input dialog using `request_user_input_async` or the client's
   equivalent tool with this exact question: "What developer name should appear in this daily development log?"
   Use free-text input with no suggested names. Wait for a non-empty answer and
   trim leading and trailing whitespace. If the answer is empty, ask again.
   Each new report requires its own response, even if a name was supplied for a
   previous report in the same conversation. Do not infer or reuse identity from
   Git configuration, the system username, earlier logs, or commit authors.
   If the client has no input dialog tool, ask the same question in chat and wait.
   Cancellation means no new report is written. For an update, read and preserve
   the existing report's developer name without opening a name dialog. Missing
   legacy names remain `Not recorded` unless the user supplies a correction.
4. Review the available conversation, relevant changes, commit history, test
   results, and referenced artifacts. Attribute work to the reporting day only
   when supported by evidence. Uncommitted changes do not prove when or by whom
   work was performed. Include explicitly reported work as user-reported evidence.
5. Summarize outcomes, implementation, validation, unresolved issues, and next
   steps using the template below. Distinguish completed changes from verified
   behavior and planned work. Do not invent commands, measurements, results,
   authorship, or completion claims. Mark missing facts as `Not recorded` and
   unperformed validation as `Not run`.
6. Immediately before saving, obtain the current time from the available clock
   tool or system clock and convert it to New York time (`America/New_York`). Populate the
   save metadata and history according to the rules below. Never substitute
   midnight, the reporting date, or file modification time for a missing save time.
7. Save the report in `dev_logs/` using the naming rules below. On updates,
   preserve valid earlier entries, reconcile duplicates, and clearly correct
   superseded results. Preserve the original creation timestamp and save history.
8. Report whether the file was **created** or **updated**, its path, its save
   timestamp, and any material evidence gaps.

## File Naming and Updates

- Filename: `YYYY-MM-DD_<developer-slug>.md`.
- Example: `2026-10-10_alex-chen.md`.
- Derive the slug from the supplied name: lowercase it, replace runs of spaces
  or characters other than ASCII letters and digits with a hyphen, and trim
  leading and trailing hyphens. If the result is empty, ask for a short ASCII
  identifier. Keep the original developer name in the report.
- Use one report per date and developer. If a filename already belongs to a
  different developer because of a slug collision, request a distinct identifier
  before writing. Never overwrite another developer's report.
- If a proposed new report resolves to the same date and developer as an existing
  report, explain that it already exists and ask whether to update that report.
  Do not silently replace it or create a duplicate. An update uses the existing
  path; do not rename it or infer a different developer.
- Do not modify this convention file or `AGENTS.md` while generating daily logs.

## Save Metadata and History

- `Date` identifies the day being reported. Save timestamps identify when the
  file was created or updated; they may fall on a different calendar day.
- Record save timestamps in New York time (`America/New_York`) using the
  **24-hour clock** (hours `00`–`23`); never use AM/PM.
- Display save timestamps as `HH : MM: SS Mon D, YYYY EDT/EST`, for example
  `00 : 25: 41 Oct 11, 2026 EDT`. Use two digits for hours, minutes, and seconds,
  an English three-letter month abbreviation, and the day without a leading zero.
  Keep the spacing shown in the example: a space on each side of the first colon
  and a space after the second colon.
- Convert the actual instant using `America/New_York` and display `EDT` during
  daylight saving time or `EST` during standard time. Do not hardcode one
  abbreviation for the whole year or display an ISO timestamp/numeric offset
  in the save metadata or history.
- When explicitly migrating only the timestamp display format, preserve the
  recorded instants and existing history. This presentation change does not
  create a new save-history event. Content or other metadata updates continue
  to record their actual save time under the rules below.
- **Create:** set `Created at` and `Last updated at` to the same actual save
  timestamp, set `Last operation` to `Created`, and add the initial `Created`
  history row.
- **Update:** preserve `Created at` verbatim, refresh `Last updated at` to the
  actual save timestamp, set `Last operation` to `Updated`, and append an
  `Updated` history row describing what changed. Preserve previous history rows.
- For a legacy log with no recorded creation timestamp, set `Created at` to
  `Not recorded`. Do not reconstruct it from the reporting date, filesystem
  timestamps, or recollection. A metadata migration is an update, not a creation;
  initialize its history with the unknown original creation and today's actual
  update. Do not invent entries for other past saves.
- Name prompts apply to new daily reports, not to changes to this convention
  or metadata updates of existing reports.

## Writing and Evidence Rules

- Keep every section in the template, in the specified order. Use `None` for
  sections with no applicable entries; reserve `Not recorded` for missing evidence.
- Use concise, concrete English and past tense for completed work.
- Use blank lines for spacing; do not add empty Markdown tables.
- Reference repository files using paths relative to the report, for example
  `[README.md](../README.md)`. Include commit hashes when available and relevant.
- Record exact validation commands when known, their outcomes, and meaningful
  measurements with units. Use `Passed`, `Failed`, `Not run`, or `Not recorded`
  as validation results. Do not rerun hardware experiments or change deployment
  state merely to prepare a log.
- Distinguish repository changes, local build checks, and deployment or hardware
  validation. A successful build does not establish end-to-end operation.
- Include only relevant sanitized evidence. Never copy credentials, private
  keys, SIM authentication secrets, tokens, or sensitive raw logs into a report.
- Make next steps actionable and ordered by priority. Do not assign an owner or
  deadline unless one was provided.

## Required Report Template

```markdown
# Daily Development Log — YYYY-MM-DD

| Field | Value |
| --- | --- |
| Developer | <developer name as supplied> |
| Date | YYYY-MM-DD |
| Timezone | America/New_York |
| Created at | <original creation timestamp, or Not recorded for a legacy log> |
| Last updated at | <actual timestamp of this save> |
| Last operation | <Created / Updated> |
| Project | Falcon |
| Branch | <branch or Not recorded> |
| Relevant commits | <hashes, None, or Not recorded> |

**Save history**

| Saved at | Operation | Changes |
| --- | --- | --- |
| <creation timestamp or Not recorded> | Created | <initial report, or original creation time not recorded> |
| <update timestamp, if applicable> | Updated | <changes made in this update> |

## 1. Daily Summary

<A short paragraph describing the day's objective, main outcomes, and current status.>

## 2. Completed Work

| Task | Changes and outcome | Evidence |
| --- | --- | --- |
| <task> | <what changed and what was achieved> | <file link, commit, or user report> |

## 3. Technical Details and Decisions

- <Significant implementation detail or decision, its reason, and relevant configuration.>

## 4. Validation and Results

| Check | Command or method | Result | Evidence and limitations |
| --- | --- | --- | --- |
| <check> | <exact command or method; Not recorded if unknown> | <Passed / Failed / Not run / Not recorded> | <observed output, measurements with units, and scope> |

## 5. Issues, Blockers, and Risks

| Issue | Impact | Current status and next action |
| --- | --- | --- |
| <issue> | <effect on progress or behavior> | <known cause, attempted fix, or remaining investigation> |

## 6. Next Steps

1. <Highest-priority concrete action and intended verification.>
2. <Next action, if applicable.>

## 7. References and Artifacts

- <Links to relevant code, patches, documentation, sanitized logs, or commits.>
```

Replace placeholders with supported facts. When a table has no applicable rows,
replace the table with `None`; when evidence is unavailable, use `Not recorded`.
Do not leave placeholder rows in saved reports. A newly created report includes
only its `Created` history row; add `Updated` rows when updates actually occur.

## Reusable User Prompts

### Create a New Log

> Create a new daily development log for today using
> `dev_logs/PROMPT_CONVENTION.md`. Confirm my developer name in a new input dialog
> and wait for my response. Review today's available work and evidence, write
> the report in English using every required section, and save it in `dev_logs/`
> with creation/update timestamps and a `Created` history entry. State that the
> report was created and give its path and save time. Clearly mark missing
> evidence and validation that was not run.

### Update an Existing Log

> Update `dev_logs/YYYY-MM-DD_<developer-slug>.md` using
> `dev_logs/PROMPT_CONVENTION.md` and the new progress below. Keep the existing
> developer name without asking for it again, preserve the reporting date and
> creation timestamp, refresh the last-update timestamp, and append an `Updated`
> history entry. State that the report was updated and give its path and save time.
