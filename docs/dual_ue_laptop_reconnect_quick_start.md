# Dual UE Laptop Automatic Reconnect — Quick Start

Updated: 2026-10-24. Developer: Ruibin.

Run these watchers on the **UE laptop** during an experiment. Each one prepares
its selected UE, verifies connectivity, then keeps monitoring and recovering that
UE until Ctrl+C shuts it down. For one startup/self-check followed by a passive,
low-resource wait until Ctrl+C (no ongoing probes), use [laptop one-shot startup and self-check](dual_ue_automation.md).

<a id="before-starting"></a>

## 1. Before every start: check the cell lock

On the laptop, manually check each UE's serving cell and restore its cell lock
if needed. **Modem/SIM verification, enable/registration, PDU setup, network
configuration and ping are handled by the automation in section 2.**

### Select the current modem by IMEI

Use a separate **Bash terminal for each UE**. Run this function definition in
each terminal, then run that role's block below. It sets `$MODEM` from the current
IMEI match, so a changed modem index is handled without guessing. A missing or
duplicate match stops before the cell query. This selection only reads modem
identity; the automation performs the remaining self-checks.

```bash
select_ue_modem() {
  local expected_imei="$1" listing path info imei
  local -a paths=() matches=()
  MODEM=''
  listing=$(mmcli -L) || return 1
  mapfile -t paths < <(printf '%s\n' "$listing" |
    sed -n 's|.*\(/org/freedesktop/ModemManager1/Modem/[0-9][0-9]*\).*|\1|p' | sort -u)
  for path in "${paths[@]}"; do
    info=$(mmcli -m "$path" -K) || return 1
    imei=$(printf '%s\n' "$info" | awk '
      /^[[:space:]]*modem[.]generic[.]equipment-identifier[[:space:]]*:/ {
        sub(/^[^:]*:[[:space:]]*/, ""); sub(/[[:space:]]*$/, ""); print; exit
      }')
    [[ "$imei" = "$expected_imei" ]] && matches+=("$path")
  done
  if [[ ${#matches[@]} -ne 1 ]]; then
    printf 'FAIL: IMEI %s matched %s modems; stop here.\n' \
      "$expected_imei" "${#matches[@]}"
    return 1
  fi
  MODEM=${matches[0]}
  printf 'Selected modem: %s (IMEI %s)\n' "$MODEM" "$expected_imei"
}
```

### Check the serving cell

**UE1 / FR1 — IMEI `863305041978437`:**

```bash
if select_ue_modem 863305041978437; then
  mmcli -L
  mmcli -m "$MODEM"
  sudo mmcli -m "$MODEM" --get-cell-info
fi
```

**UE2 / FR3 — IMEI `863305041980706`:**

```bash
if select_ue_modem 863305041980706; then
  mmcli -L
  mmcli -m "$MODEM"
  sudo mmcli -m "$MODEM" --get-cell-info
fi
```

Check the NR record marked `serving: yes` against these targets:

| Role | PCI | NCI (hex) | SSB NR-ARFCN / SCS / band |
| --- | --- | --- | --- |
| UE1 / FR1 | `1` | `66C000` | `643680` / 30 kHz / n78 |
| UE2 / FR3 | `2` | `66C001` | `639648` / 30 kHz / n78 |

Both radios use n78. A matching serving cell lets you continue to section 2.
GetCellInfo shows the current serving cell; the stored lock is read back with
`AT+QNWLOCK="common/5g"` below. If cell evidence is missing or mismatching,
check/restore the selected role's lock through its AT port. After verifying
the port mapping, the watcher can also [restore the lock automatically after
radio failures](#automatic-cell-lock-and-registration-after-radio-failure).

### Restore the lock when needed

#### AT port mapping and preparation

Open the AT port in the **same laptop terminal** where this UE's `$MODEM` was
selected above. If its launcher/watcher is running, stop it with Ctrl+C, wait for
the shutdown result, then repeat modem selection before opening the serial port.
Keep ModemManager running.

The laptop's **2026-10-24 operator-provided serial listing** gives these ports
for the recorded UE1 USB `4-4` / UE2 USB `4-3` wiring:

| Role | `AT_PORT` (preferred by-path) | Current tty device |
| --- | --- | --- |
| UE1 / FR1 | `/dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.2-port0` | `/dev/ttyUSB2` |
| UE2 / FR3 | `/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0` | `/dev/ttyUSB6` |

The by-path values follow the physical USB sockets. If the wiring changes,
match the selected modem's physical device to `ls -l /dev/serial/by-path/` again.
The `ttyUSB` numbers can change even when the sockets stay the same.

#### UE1 / FR1

Open **UE1's AT port** in the laptop terminal where its `$MODEM` was selected:

```bash
mmcli -m "$MODEM"
AT_PORT=/dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.2-port0
ls -l "$AT_PORT" && sudo minicom -D "$AT_PORT" -b 115200
```

In **this minicom session**, send `AT+CGSN` first and require IMEI
`863305041978437`. Stop on a mismatch. Then send UE1's commands one at a time:

```text
AT+QNWPREFCFG="mode_pref",NR5G
AT+QNWPREFCFG="mode_pref"
AT+QNWPREFCFG="nr5g_disable_mode",2
AT+QNWPREFCFG="nr5g_disable_mode"
AT+QNWPREFCFG="nr5g_band"
AT+QNWLOCK="common/5g",1,643680,30,78
AT+QNWLOCK="common/5g"
AT+QENG="servingcell"
AT+C5GREG?
```

Read back UE1's lock tuple and actual serving cell. Exit this minicom session
with **Ctrl+A, then X** before starting UE1's automation.

#### UE2 / FR3

Open **UE2's AT port** in the laptop terminal where its `$MODEM` was selected:

```bash
mmcli -m "$MODEM"
AT_PORT=/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0
ls -l "$AT_PORT" && sudo minicom -D "$AT_PORT" -b 115200
```

In **this minicom session**, send `AT+CGSN` first and require IMEI
`863305041980706`. Stop on a mismatch. Then send UE2's commands one at a time:

```text
AT+QNWPREFCFG="mode_pref",NR5G
AT+QNWPREFCFG="mode_pref"
AT+QNWPREFCFG="nr5g_disable_mode",2
AT+QNWPREFCFG="nr5g_disable_mode"
AT+QNWPREFCFG="nr5g_band"
AT+QNWLOCK="common/5g",2,639648,30,78
AT+QNWLOCK="common/5g"
AT+QENG="servingcell"
AT+C5GREG?
```

Read back UE2's lock tuple and actual serving cell. Exit this minicom session
with **Ctrl+A, then X** before starting UE2's automation.

Port-selection details remain in the full manual for
[UE1](dual_ue_laptop_quick_commands.md#12-verify-the-at-port-and-restore-the-du1-lock)
and [UE2](dual_ue_laptop_quick_commands.md#22-verify-the-at-port-and-restore-the-du2-lock).
After completing the selected role's block, continue to section 2. If the modem
is disabled after the previous Ctrl+C shutdown, the automation handles enabling
it and waiting for registration.

## 2. Automation scripts

The script performs the modem/SIM, enable/registration, serving-cell, PDU,
interface/routing and ping self-checks. Start Spark's core, CU and both DUs first
using [Spark quick commands](dual_ue_spark_quick_commands.md). Keep ModemManager
running and close minicom before launching the script.

### Laptop dependencies (install once)

```bash
sudo apt install modemmanager iproute2 iputils-ping python3 minicom
sudo systemctl enable --now ModemManager
```

### Expected roles

| Item | UE1 / FR1 | UE2 / FR3 |
| --- | --- | --- |
| Modem IMEI | `863305041978437` | `863305041980706` |
| Active SIM IMSI | `001010000000101` | `001010000000102` |
| APN | `internet` | `internet2` |
| UE pool | `10.45.0.0/16` | `10.46.0.0/16` |
| Spark service IP | `10.45.0.1` on `ogstun_1` | `10.46.0.1` on `ogstun_2` |
| Video preference | Backup | Primary |
| Policy table | `151` | `152` |
| Serving PCI | `1` | `2` |
| Serving NCI, hex | `66C000` | `66C001` |
| SSB NR-ARFCN / SCS | `643680` / 30 kHz | `639648` / 30 kHz |
| Carrier NR-ARFCN | `644000` | `640000` |
| Independent reset block | priority `20151` | priority `20152` |

FR1 and FR3 are the existing demo path labels; **both current DUs use n78**.
The common PLMN is `00101`, TAC is `7`, and access must be NR SA. The scripts
discover current modem/SIM/bearer object paths and the actual IPv4 address,
prefix, MTU and interface on each run. Historical modem indices, `ttyUSB`
numbers, `wwan` names and UE addresses are not reused.

The entry points are [`reconnect_ue1.sh`](../scripts/dual_fr1/reconnect_ue1.sh)
(**UE1 / FR1**) and [`reconnect_ue2.sh`](../scripts/dual_fr1/reconnect_ue2.sh)
(**UE2 / FR3**). They use [`reconnect_ue.py`](../scripts/dual_fr1/reconnect_ue.py),
[`connect_ue.py`](../scripts/dual_fr1/connect_ue.py) and
[`reset_ue_network.py`](../scripts/dual_fr1/reset_ue_network.py): **five files**.

### Copy or update the five files

Run in **Bash on the laptop**. Stop active launchers/watchers before updating the shared
Python helpers, then repeat this block whenever the Spark scripts change:

```bash
(
  set -euo pipefail
  mkdir -p ~/falcon-ue-connect

  ssh -T nyu@10.20.44.26 \
    'tar -C /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1 -czf - reconnect_ue1.sh reconnect_ue2.sh reconnect_ue.py connect_ue.py reset_ue_network.py' |
    tar -xzf - -C ~/falcon-ue-connect

  ls -l ~/falcon-ue-connect/{reconnect_ue1.sh,reconnect_ue2.sh,reconnect_ue.py,connect_ue.py,reset_ue_network.py}
)
```

This uses **one SSH connection** to Spark, normally with one `nyu` password prompt.
The archive is streamed directly; there is no intermediate archive or temporary
extraction directory to delete. Repeating the transfer overwrites the five named
files; it does not delete other files already in `~/falcon-ue-connect`. The
one-shot guide uses the same directory and shared helpers, but copies its own
four-file set. Both entry-point sets together comprise seven distinct files.

Spark's recorded management address is `10.20.44.26`; the laptop's is
`10.20.73.246`. Pulling from the laptop uses Spark's SSH listener and does not
require an SSH server on the laptop. If the address changes, confirm Spark's
current management IP before transferring. A later `[sudo] password for david:`
prompt authorizes local laptop operations; it is separate from Spark SSH login.

### Start the watchers

Run **on the laptop**, one terminal for each role. Each watcher connects/verifies
its UE on startup, monitors the working path, and retries when a later check fails.
It stays running after successful recovery. The other UE and management Wi-Fi
are preserved. These commands use the copied folder from the transfer above:

```bash
# Terminal 1: UE1 / FR1
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --interval 1 --verbose 1
```

```bash
# Terminal 2: UE2 / FR3
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 1 --verbose 1
```

### Independent UE operation and host network locking

Each launcher/watcher keeps its own role lock for its lifetime, so a second
process for the **same UE** is rejected. UE1 and UE2 can run at the same time.
Their modem queries, registration waits, PDU connect/disconnect, bearer deletion,
modem disable and ping run outside the shared network lock.

The watcher remembers its verified modem path and device identifier in memory.
Routine checks and recovery query only that modem, its SIM and its bearers,
while still checking IMEI/IMSI on every use. Initial discovery, or discovery after
an object disappears/is replaced or its WWAN mapping changes, enumerates
available modems by IMEI and may read both. A query timeout on an existing object does not trigger a scan of the
other UE. ModemManager and the USB/kernel services are still shared dependencies;
this is isolation of the scripts' operations, not a separate ModemManager daemon.

The shared lock covers only kernel network updates and consistent host-state
reads. Read-only host checks can overlap; address/route/rule/MTU/UP changes are
exclusive. Host ownership also checks the WWAN's physical USB device against
this modem's current identity through sysfs. Each update compares peer and
management state immediately before and after its own writes. Across radio waits and ping, legitimate peer-UE
changes are allowed and management state remains checked. A failed check is
reported rather than accepted as success. Wi-Fi fallback guards remain installed.

`Waiting for a host network update to finish ...` now means waiting for one of
these host transactions; a slow radio query does not hold that lock. Healthy
checks record UTC start/completion markers and elapsed time in `run.log`; level 3
also shows them in the terminal. Normal external-command timeouts still apply.

**Stop both old launchers/watchers before updating**, copy the complete file set
from this guide's transfer section, and restart both. An already-running Python
process keeps its loaded version. Manual commands and NetworkManager do not
participate in these locks; finish/stop the selected role before manual configuration.

### Retry and health-check interval

`--interval` defaults to **1 second** and accepts positive fractional seconds.
It is the wait **after a check or completed connection attempt**, before the next
check/attempt. Registration, ModemManager commands and ping take additional time;
this is not a guaranteed one-second recovery or a new overlapping process every
second. An attempt waits up to five seconds for registration by default
(`--registration-timeout 90` extends that wait); individual external commands have
a 75-second timeout. Healthy checks and recovery both verify source-bound and
ordinary routes and use **one ping in each mode**, rather than the one-shot
launcher's five. Healthy checks read modem/cell/bearer/host state and send ping;
they do not modify the modem, addresses or routes. **Healthy monitoring and failed
retries share this same interval; there is no separate health-check timer.**
Each healthy round sends one source-bound and one ordinary ping per UE to its
Spark service. A failed earlier check ends the round before those pings complete.

### Output levels

| Watcher option | Terminal output |
| --- | --- |
| `--verbose 1` (default) | Attempt number and `SUCCESS` / `FAIL` only. |
| `--verbose 2` | Each attempt's step labels, `[OK]` / `[FAIL]`, result, actionable error and evidence directory. |
| `--verbose 3` | Level 2 plus executed query/change commands, validated identity/cell/bearer details, command output and raw ping results; healthy checks are shown too. |

All three levels save the same detailed `run.log`; raw bearer authentication
properties are not dumped. Healthy monitoring is silent at levels 1 and 2.
**Silent means no terminal output: the status checks, ping traffic and file logging
still happen.** It does not mean passive monitoring without network traffic.
Registration snapshots (state, 3GPP registration/packet state, PLMN, access
technology and elapsed wait) are saved in the detailed log and shown at level 3;
see [registration diagnosis](dual_ue_automation.md#waiting-at-modem-registration)
if the watcher cannot get past that step.
Verbosity changes terminal detail, not the checks or recovery actions. The older
`connect_ue*.sh` one-shot scripts retain their boolean `--verbose` flag; the
**new `reconnect_ue*.sh` watchers require the numeric level**.

Illustrative minimal output, not a new hardware result:

```text
UE2 / FR3 attempt 1 ... FAIL
UE2 / FR3 attempt 2 ... FAIL
UE2 / FR3 attempt 3 ... SUCCESS
```

For steps or full output, or a different retry delay:

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 2 --verbose 2
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 0.5 --verbose 3
```

### Stop or switch to manual operations

Run only **one launcher or watcher per role**; duplicate ownership is rejected.
UE1 and UE2 run their radio/PDU work and ping independently. They coordinate
only kernel host-state checks and updates as described above. An attempt is
counted when it starts; waiting inside its host-update step remains part of
that attempt.

**Ctrl+C now shuts down this UE**, rather than merely stopping monitoring.
SIGTERM has the same cleanup behavior. The script cancels its work/wait,
verifies this role's current identity and uses the shutdown helper logic:
disconnect PDU, clear role IPv4/routes/rules, bring WWAN DOWN / MTU 1500,
delete bearers and disable modem. Only the host updates/verification take
the shared network lock; modem operations remain independent. The independent
Wi-Fi fallback block stays installed; the other UE and management Wi-Fi are preserved.

Wait for `UE1 shutdown: SUCCESS` / `UE2 shutdown: SUCCESS` before manual
configuration or restarting that role. Host cleanup can wait for the other
role's kernel network transaction. Repeated Ctrl+C/SIGTERM cannot re-enter or
interrupt cleanup;
a failed cleanup prints `FAIL` plus the reason, even at verbosity 1. The outcome
is saved in `summary.json`. A later startup can enable/reconnect the disabled UE.
Stopping the watcher interrupts that UE's traffic path, including video using it.

Default operation has no attempt limit: it monitors healthy paths and retries
faults until Ctrl+C. Optional `--once`/`--max-attempts` retain their bounded normal
exit behavior; a normal `--once` success leaves the UE connected. No service,
boot job or background daemon is installed automatically.

### Automatic recovery

Recovery proceeds as follows:

1. Verify the selected modem/SIM and current serving cell; rediscover by IMEI
   when its object disappears/is replaced or its WWAN mapping changes. Missing registration or
   unproved/mismatching cells fail that attempt and continue polling. By default,
   level 2/3 explains the manual checks and no radio configuration is written.
   With `--auto-cell-lock --at-port ...`, the watcher performs the guarded radio
   recovery below, then retries full verification on the next attempt. A wrong
   cell never bypasses verification to dial a PDU or rebuild host networking.
2. Connect a disconnected PDU, or reuse a valid connected one. A **suspended**
   connected static bearer on the expected APN triggers a guarded disconnect and
   redial. Host ownership, policy resources, IMEI/IMSI and serving cell must pass
   before any forced disconnect. Foreign APNs, multiple active bearers, malformed
   allocations or foreign host resources fail without automatic deletion/redial.
3. If the expected PDU remains connected but ping fails for **three consecutive
   connection attempts**, force a disconnect on the **next attempt**, then redial.
   `--redial-after 3` sets this threshold. A fresh IP/bearer allocation is rebuilt
   without forcing a disconnect for failures on the old allocation. Route/cell/
   identity errors are not counted as failed ping attempts.
4. Forced disconnect requests have a **30-second minimum gap**, including rejected
   disconnects and suspended-PDU recovery (`--redial-cooldown 30`). Other checks,
   reuse, host repair and ordinary connection of a disconnected PDU continue
   between retries. The cooldown limits redials when the server itself is down;
   a failed ping does not establish that the PDU is broken.
5. Read the current bearer IP/prefix/interface/MTU, rebuild stale role addresses and
   source/destination policy rules, retain the independent Wi-Fi fallback block,
   then verify both ping modes and final state. A failed disconnect never proceeds
   into host reset/reconnect in that attempt. Resume healthy monitoring only after
   complete verification. The scripts do not restart ModemManager or the other UE.

### Automatic cell lock and registration after radio failure

Enable this option on the **laptop**, after copying the updated five-file set
above and closing minicom. Stop old watchers before updating shared helpers.
Use one terminal per UE, with the verified by-path port from section 1:

```bash
# Terminal 1: UE1 / FR1 — USB 4-4, recorded AT port ttyUSB2
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --interval 3 --verbose 2 \
  --auto-cell-lock --cell-lock-cooldown 30 \
  --at-port /dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.2-port0
```

```bash
# Terminal 2: UE2 / FR3 — USB 4-3, recorded AT port ttyUSB6
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 3 --verbose 2 \
  --auto-cell-lock --cell-lock-cooldown 30 \
  --at-port /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0
```

The option requires `--at-port`; it does not guess a tty number. Registration
failure or missing/mismatching serving-cell evidence triggers radio recovery.
Identity/SIM errors, ping failures and host route errors do not directly trigger
AT configuration. The default remains read-only radio checking when this option
is absent; `--at-port` alone still only enables the read-only cell fallback.

Each eligible recovery does the following:

1. Recheck this modem's IMEI, active SIM IMSI, active-bearer APN and dedicated
   WWAN ownership. Check host resources under a short shared read lock. Reject
   foreign resources, a wrong USB serial device or an occupied port.
2. Exclusively open the AT port and verify `AT+CGSN` and `AT+CIMI` before any
   configuration. Read the NR settings; restore `mode_pref=NR5G` and
   `nr5g_disable_mode=2` only when different, verifying each readback. Read
   `nr5g_band`; if n78 is excluded, set it to `78` and verify the readback.
3. Read the saved lock, reapply this role's lock, and require an exact readback:

   | Role | Lock command |
   | --- | --- |
   | UE1 / FR1 | `AT+QNWLOCK="common/5g",1,643680,30,78` |
   | UE2 / FR3 | `AT+QNWLOCK="common/5g",2,639648,30,78` |

4. Record `AT+QENG="servingcell"` and `AT+C5GREG?`, then restore serial settings
   and close the port. Enable the modem if needed. If ModemManager still does
   not report registered NR SA on `00101`, request registration using
   `mmcli -m <current-selected-modem> --3gpp-register-in-operator=00101`.
5. Mark the current attempt `FAIL`: applying a lock is not proof of connectivity.
   On the next attempt, require the usual registration, exact serving cell,
   PDU, current-IP routing, both pings and final checks before `SUCCESS`.

The first radio failure can trigger recovery immediately. Subsequent radio
recoveries have a **30-second minimum gap after the previous recovery ends**,
including failed/rejected writes or registration requests. During that gap,
normal checks/retries continue and can reconnect as soon as the radio is ready.
`--cell-lock-cooldown` accepts positive seconds; for example `1` permits a fresh
lock on each eligible failed attempt once a second has elapsed. Keeping `30`
gives network selection time to settle and avoids repeated saved-setting writes.
`--interval` still controls the delay after a completed attempt/check; it is not
the timeout of AT or registration work. AT commands allow five seconds each;
the registration request uses the normal 75-second external-command limit.

Serial/registration work never holds the shared host-network lock. UE1 and UE2
retain separate ownership and cooldown state. Healthy checks never write AT
configuration. No CFUN reset or ModemManager restart is performed. Ctrl+C still
closes the serial context and runs the selected UE's normal shutdown cleanup.
A rejected write/readback leaves the attempt failed; earlier successful writes
may already have taken effect and are recorded in `attempts.jsonl`.

Lowering DU TX gain can leave too little downlink signal for cell acquisition
or registration. Restoring a lock does not restore RF coverage. If registration
continues to fail with the expected lock, restore adequate DU gain/coverage and
check CU/DU/core status. No live recovery after a gain change has been validated
for this new option; validation so far uses simulated modems and pseudo-terminals.

The NR preference query/write formats and `nr5g_disable_mode=2` (disable NSA)
come from the [Quectel RG50xQ/RM5xxQ AT manual](https://www.quectel.com/content/uploads/2024/05/Quectel_RG50xQRM5xxQ_Series_AT_Commands_Manual_V1.2.pdf).
The lock readback format also matches the retained
[UE2 operator evidence](evidence/2026-10-13_du2_registration/operator_at_readback.txt).
The registration option is provided by [ModemManager's 3GPP CLI](https://github.com/linux-mobile-broadband/ModemManager/blob/main/cli/mmcli-modem-3gpp.c).

### Optional parameters

Without `--auto-cell-lock`, `--at-port` uses the same owned-port, read-only serving-cell fallback described in
[the one-shot guide](dual_ue_automation.md#serving-cell-mismatch-or-unavailable-getcellinfo).
Use the option on a watcher as follows, replacing the serial link with this UE's
verified AT port:

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --verbose 2 \
  --at-port /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0
```

Stop the affected watcher before opening minicom or changing serial settings;
close minicom before restarting it. Optional bounded operation:

```bash
# Retry until the first successful verification, then exit.
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --once --verbose 2
# At most five actual connection attempts; exit 1 if the last attempt failed.
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --once --max-attempts 5 --verbose 3
```

The attempt counter increases throughout a watcher invocation, including recovery
after later outages. Healthy checks do not increment it. `--max-attempts` bounds
connection attempts, not monitoring duration. Normal operation has no attempt
limit. Only the initial `sudo` authorization is needed for a running watcher.

### Logs and exit status

Evidence goes into a private `/tmp/falcon-ueN-reconnect-<unique-suffix>` directory,
or under `--output-root /existing/directory`. Level 1 omits the directory from the
terminal; locate it in a second terminal with:

```bash
sudo ls -td /tmp/falcon-ue1-reconnect-* /tmp/falcon-ue2-reconnect-*
```

`run.log` retains detailed attempts and health checks, including UTC health-check
start/completion markers and elapsed times; `attempts.jsonl` records
each attempt's UTC times, outcome, failed stage, current IP, ping output and
forced-redial reason when applicable. `summary.json` is written on exit and
records the last verified state **before shutdown** (not a post-exit measurement)
and the nested `shutdown` completion/error. With automatic cell locking enabled,
`attempts.jsonl` also records `radio_recovery`: the original radio error,
commands/writes attempted, previous/verified lock, diagnostic QENG/C5GREG output,
registration request and `applied` / `failed` / `cooldown` / `interrupted` result.
`applied` means the radio settings were applied; only the full connection checks
can produce connection `SUCCESS`. `attempts.jsonl` marks a cancelled
in-progress attempt as `interrupted`. Logs accumulate
for the invocation; retain the evidence you need and remove old run directories
after stopping the watcher. Signal exit codes are 130 (Ctrl+C) / 143 (SIGTERM),
after the selected-UE shutdown attempt. Cleanup failure remains visible in output
and the summary; successful cleanup requires zero bearers and modem disabled.

These watchers repair the PDU and laptop network, and can restore radio settings
with `--auto-cell-lock`. A running MPX client then follows
host IP changes as described [below](#which-ip-bindings-change-and-how-mpx-follows-them).
They do not start MPX or restart applications bound explicitly to an old IP.
Offline simulated checks pass; **physical obstruction/recovery and MPTCP traffic
acceptance with these new watchers remain pending**.

### Video during monitoring and recovery

Healthy monitoring reads state and sends the two small ping probes; it does not
change the PDU, IP, routes or MPTCP configuration. Its video-performance overhead
has not been measured on the physical testbed. A **forced PDU disconnect/redial**
temporarily interrupts that UE's path. The other UE is preserved; uninterrupted
video during recovery still depends on the remaining path and player buffer and
needs live acceptance testing.

The current watcher uses modem/bearer/host checks and ping results. **It does not
check whether video/MPTCP data is still flowing before forcing a ping-triggered
redial.** Consecutive ping failures can therefore cause a redial even while an
application remains usable. Use the threshold and cooldown above when assessing
an experiment; no video-aware redial protection is claimed.

### Which IP bindings change, and how MPX follows them

A running **laptop MPX client** with the testbed configuration and
`mptcp.pm: userspace` follows IP changes within the configured pools:

1. The reconnect watcher installs the current bearer IP and host routes.
2. MPX's link monitor notices the address change and rebinds the control path;
   the server learns the new peer address.
3. MPX requests MPTCP subflows for the new address pair and cleans up old pairs.
   It retains the FR1-backup / FR3-primary policy. Normal failback to FR3 has a
   five-second stable-UP wait; a recovered FR1 can remain idle as a backup.

Normally no manual UE-IP edit or `mpxd` restart is needed. The watcher does not
start MPX. Start Spark's video demo server first, then the laptop's video demo
client after its UE paths pass verification. To inspect the running demo, run
this in the **laptop's `falcon-app-template` checkout**, not `falcon-ue-connect`:

```bash
sudo bash demo/ue.sh status
sudo ss -Mni
```

Confirm the recovered FR1/FR3 path has the new IP and is UP, then confirm an
established new-address subflow and traffic counters where payload is expected.
An UP heartbeat alone is not data-plane proof; FR1 payload can remain zero while
FR3 carries the video. The screenshot's retained experiment already showed FR3
changing from `10.46.0.3` to `10.46.0.4` in the same MPX session with data received
on the new subflow. The new reconnect watchers still need their own live test.

<details>
<summary>Configuration audit, IP bindings and retained experiment evidence</summary>


The inspected MPX testbed configuration already follows UE address changes.
Its client `configs/testbed/ue.yaml` matches `link-1 / FR1` to
`10.45.0.0/16` and `link-2 / FR3` to `10.46.0.0/16`, with
`mptcp.pm: userspace`. The server uses `mptcp.pm: kernel` and listens on the
fixed Spark addresses `10.45.0.1` and `10.46.0.1`. Both current radios are
n78; FR1/FR3 remain the demo labels.

| Binding or state | Handling after a UE address changes |
| --- | --- |
| Laptop WWAN IPv4/prefix/MTU | The connection script reads the current bearer and installs its values. |
| Role-table route source and source policy rules | The connection script rebuilds table 151/152 and its source/destination rules when stale. |
| Manual shell variables such as `UE_IP` / `PATH_IP`, `ping -I` and plain `iperf3 -B` | Refresh those values and restart traffic commands bound to the old IP. The dual-UL launcher rediscovers current addresses when started. |
| MPX client link matching | Keeps the two pool/subnet matches; no specific UE host IP is configured there. |
| MPX UDP control sockets | The client link monitor detects address/interface changes and the session rebinds the affected socket. The server learns the new peer address from control traffic. |
| MPX MPTCP subflows | With the client userspace PM active, reconciliation replaces address pairs that are no longer current and requests subflows for the new pair. |
| Spark service addresses in client/server YAML | Stay `10.45.0.1` / `10.46.0.1`; UE reallocation does not change these server addresses. |
| Demo application/forwarder | Uses a local Unix socket and logical peer UID; the inspected demo has no fixed UE host-IP binding. |

The MPX client monitors link/IPv4-address netlink events with a 100-ms debounce
and a five-second fallback rescan. The session updates control bindings and
the userspace PM reconciles subflows; failed subflow creation is retried at
three-second intervals. These are internal timers, not a guaranteed recovery
time. MPX operates after the modem/PDU and host routes are usable; it does not
dial or repair the modem.

There is also historical live evidence from the screenshot's experiment:
the same session `3d293a88328ef4b45294ee09cd7d3d28` changed its FR3 peer from
`10.46.0.3` to `10.46.0.4`. The retained server log recorded `peer moved` at
**2026-10-23 19:30:26.906 EDT**, followed by path UP at `19:30:27.046`.
Raw MPTCP telemetry showed an established subflow to `.4` at
`19:30:32.221660` and positive received bytes at `19:30:32.622597`.
See the [configuration/recovery audit](evidence/2026-10-24_ue_recovery_mptcp/audit.json)
and [original experiment report](reports/mptcp_video_experiment_report_2026-10-23.md).
This establishes address adaptation in that retained experiment; the new
disconnect/reconnect helper sequence still needs its own live acceptance run.

At the **2026-10-24** inspection, neither Spark nor the operator's laptop
was running `mpxd`. Spark had no TCP 9001 listener. Both kernels had MPTCP
enabled with `path_manager=kernel` / `pm_type=0`. The laptop's only kernel
endpoint was `10.20.73.246 id 1 subflow dev wlp0s20f3`; Spark also had a
management Wi-Fi `subflow` endpoint in addition to its two service addresses.
These observations describe a stopped demo: automatic MPX address tracking
requires a running client. Actual subflow addresses determine which network
carried traffic; a configured endpoint alone does not prove data transfer.

Start the existing demo in the usual order, Spark's `demo/server.sh up` from
the `falcon-app-template` checkout first, then the laptop's `demo/ue.sh up`
after its UE paths pass ping. The launchers copy the selected testbed YAML
into `out/demo/mpxd.yaml` by default (`RUN` and `CONFIG` can override this).
Check the running process's `--config` path when diagnosing an overridden
setup. On the laptop, the client userspace PM normally yields
`path_manager=userspace` / `pm_type=1` while that `mpxd` runs; kernel PM on
Spark is expected. See the [Linux path-manager documentation](https://docs.kernel.org/networking/mptcp-sysctl.html)
for these kernel settings. MPX restores its previous PM setting on normal exit.

Read-only checks on the **laptop**, from its `mpx-transport` checkout:

```bash
ps -C mpxd -o pid=,args=
sudo sysctl net.mptcp.enabled net.mptcp.path_manager net.mptcp.pm_type
sudo ip mptcp endpoint show
sudo python3 tools/mpx_status.py /tmp/mpx-ue.sock
sudo ss -Mni
```

After PDU recovery, require the affected path to show its new local address
and recover to UP, and verify the actual MPTCP subflow/byte counters under
traffic. FR1 is configured as a backup, so its payload rate can remain zero
while FR3 is healthy. A heartbeat UP result by itself is not data-plane proof.
Run `sudo bash demo/ue.sh status` from `falcon-app-template` for the same
MPX path view when using the demo launcher. Retain each recovery's PDU/IP,
path-change, subflow and traffic evidence separately.

</details>
