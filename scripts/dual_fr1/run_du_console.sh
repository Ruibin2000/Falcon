#!/usr/bin/env bash
# Keep sudo and the DU on a full terminal while recording console output.
# Usage: bash run_du_console.sh STARTUP_LOG COMMAND [ARG ...]
set -euo pipefail

if (( $# < 2 )); then
  printf 'Usage: bash %s STARTUP_LOG COMMAND [ARG ...]\n' "$0" >&2
  exit 2
fi
if [[ ! -t 0 || ! -t 1 || ! -t 2 ]]; then
  printf 'Run this launcher directly in an interactive terminal; it records its own console log.\n' >&2
  exit 2
fi
if ! command -v script >/dev/null 2>&1; then
  printf 'Missing util-linux script command.\n' >&2
  exit 1
fi

DU_CONSOLE_LOG=$1
shift

# script -c invokes a shell. Quote each original argument and select Bash to
# interpret printf %%q, including paths/arguments with spaces or newlines.
printf -v DU_CONSOLE_COMMAND '%q ' "$@"
export SHELL=/bin/bash

# Log output only: sudo's hidden password input must not be recorded.
# --return propagates the DU exit status; --flush keeps the transcript current.
exec script --quiet --flush --return --log-out "$DU_CONSOLE_LOG" \
  --command "exec $DU_CONSOLE_COMMAND"
