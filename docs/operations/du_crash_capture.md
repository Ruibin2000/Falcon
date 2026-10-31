# Capture a DU1 or DU2 runtime crash

The [current radio profiles](../project_design_and_progress.md) are DU1
3660 MHz OTA / 20 MHz / TX 70 / RX 35 and DU2 9250 MHz OTA / 40 MHz /
TX 60 / RX 10 through Pi-Radio. DU2 retains a 3600-MHz logical n78 interface;
its gain values were tuned for the modified FR3 hardware. Retain the RF arrangement with
the configuration snapshots so that a historical crash is not attributed to
a later bandwidth, gain or converter setup.

Both DUs can use temporary GDB capture during the six-minute reconnect
stability test. Select the optional commands in
[Spark sections 5a/5b](../spark_quick_commands.md#5a-spark-du1-terminal)
in place of their normal startup commands. Start each DU in its own interactive
terminal with the existing Core/RIC/CU running. Each selected old DU must have
exited before its replacement starts. These launchers start a new process;
they do not attach to or stop an existing DU.

**Spark DU1 terminal:**

```bash
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/debug_du1.sh
```

**Spark DU2 terminal:**

```bash
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/debug_du2.sh
```

Enter sudo's password if requested. Wait for each radio/F1/E2 startup and
`==== DU started ===`. Keep both terminals open. Then verify both Laptop
reconnect watchers report `SUCCESS` and run
[Spark section 7b](../spark_quick_commands.md#7b-six-minute-reconnect-stability-with-alternating-and-concurrent-ul).
No DU rebuild is needed. The existing binary is
`/home/nyu/ocudu/build-integrated/apps/du_split_8/odu` for both roles.

| Role | Source configuration | Printed evidence directory |
| --- | --- | --- |
| DU1 / FR1 | `configs/du1_b210_n78_3660mhz.yml` (includes its E2 settings), radio `3271233` | `/tmp/falcon-du1-crash.XXXXXXXX` |
| DU2 / FR3 | `configs/du2_b210_n78_40mhz.yml` plus `configs/du2_flexric.yml`, radio `328B021` | `/tmp/falcon-du2-crash.XXXXXXXX` |

The fixed-role wrappers share `debug_du.sh` and `capture_du_crash.gdb`.
Configuration snapshots, logs and debugger output remain separate per DU and
per invocation. They reuse the console launcher, preserving interactive DU
commands and console/gain timestamps. Neither script changes system core
settings or starts/restarts other testbed services.

On SIGSEGV/SIGABRT/SIGBUS/SIGILL/SIGFPE, GDB stops the affected DU, writes every
thread's bounded backtrace and the faulting thread's registers/instruction,
then terminates that stopped inferior and returns a nonzero status. A normal
exit records `status=exited`. Ctrl+C is passed to the DU's normal signal handler.
No process is automatically restarted.

| File in each debug directory | Purpose |
| --- | --- |
| `backtrace.txt` | UTC timestamp, role and stopped-thread stacks/registers/instruction, or a labelled normal exit |
| `status.json` | DU role, stop signal or exit code, timestamp and mapped-binary hash when available |
| `startup.log`, `startup.log.timing` | Console and timing from the existing terminal launcher |
| `du.log` | That DU's application log |
| `du1.yml` or `du2.yml` | Effective role-specific base configuration snapshot |
| `e2.yml` | DU2's additional E2 overlay; DU1 uses its base configuration |
| `binary.sha256`, `capture.gdb` | Binary reference and debugger commands used for the run |

`status.json` and `backtrace.txt` are written after that debugger stops/exits.
Their absence while the DU is healthy and still running is expected. A healthy
completed xApp capture does not stop either DU. Once all captures/traffic are
finished, use the normal shutdown order before ending DU terminals.

Keep **both** DU debug directories, the Spark xApp capture, Laptop traffic
results and both reconnect logs. After a debugger finishes, inspect its output
in another Spark terminal:

```bash
read -r -p 'Paste the completed DU1 or DU2 debug directory: ' DU_CRASH_READ
cat "$DU_CRASH_READ/status.json"
tail -n 100 "$DU_CRASH_READ/backtrace.txt"
```

The existing Release binary is not stripped and can supply function names,
but lacks full DWARF line/local-variable information. Begin with that exact
binary to preserve the tested optimization settings. A separate debug-symbol
build is a later option if the captured frames cannot locate the fault.
GDB changes execution timing: label the trial as using GDB on both DUs, and
retain radio timing warnings. A run without recurrence does not establish
that the prior fault is fixed. This capture does not implement the deferred
snapshot-concurrency changes.

The motivating October 25 expanded-profile run was
`/tmp/falcon-identity-dual.RyxoFplT`: Apport recorded DU2 SIGSEGV at 17:58:57 EDT,
followed by a RIC assertion at 17:59:04 and an xApp timeout assertion at 17:59:10.
Apport discarded those non-package executables' core reports. The fault's
function-level cause and recurrence frequency remain unestablished.

For offline preparation without starting GDB, sudo, a DU or a radio:

```bash
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/debug_du1.sh --prepare-only
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/debug_du2.sh --prepare-only
```
