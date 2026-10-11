# Development Log Instructions

When creating or updating a daily development log in this directory, read and
follow [PROMPT_CONVENTION.md](PROMPT_CONVENTION.md).

Before drafting or saving, identify the target and state whether the operation
will create a new log or update an existing log.

- **Create:** each new log requires a fresh developer-name response through the
  client's input dialog (`request_user_input_async`, or an available equivalent).
  Wait for a non-empty answer. If no dialog tool is available, ask in chat and
  wait. Never reuse a name from a previous creation, Git, the operating system,
  or earlier logs.
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
