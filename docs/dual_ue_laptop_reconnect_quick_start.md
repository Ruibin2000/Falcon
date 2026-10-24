# Dual UE Laptop Automatic Reconnect — Quick Start

Updated: 2026-10-24. Developer: Ruibin.

Run these watchers on the **UE laptop** during an experiment. Each one prepares
its selected UE, verifies connectivity, then keeps monitoring and recovering that
UE until Ctrl+C shuts it down. For one startup/self-check followed by a passive,
low-resource wait until Ctrl+C (no ongoing probes), use [laptop one-shot startup and self-check](dual_ue_automation.md).
This guide uses **`reconnect_ue1.sh` / `reconnect_ue2.sh`**. The separate
**`connect_ue1.sh` / `connect_ue2.sh`** entry points perform one-shot startup
and a passive wait. Both modes share a per-UE lock, so only one can own a given
UE at a time.

**2026-10-24 checkpoint:** the current script optimization stage is complete.
Keep the recovery policy and defaults below. A new recovery test will use fresh
logs after host clock synchronization, followed by an English experiment report.

<a id="before-starting"></a>

## 1. Before starting

Start Spark's core, CU and both DUs using
[Spark quick commands](dual_ue_spark_quick_commands.md). Keep ModemManager running
on the laptop and close minicom before starting a watcher.

**No manual modem selection, serving-cell query or AT lock sequence is required
before each start.** Each `reconnect_ue*.sh` entry script enables
`--auto-cell-lock` and supplies its UE's AT port internally. The script selects the modem by IMEI, verifies its SIM,
immediately verifies/restores its serial cell lock, enables it and requests
registration if needed, then continues through PDU, network and ping verification.
Later radio failures follow the observation and recovery procedure below.

### AT port mapping

The laptop's **2026-10-24 operator-provided serial listing** gives these ports
for the recorded UE1 USB `4-4` / UE2 USB `4-3` wiring:

| Role | Built-in AT port (by-path) | Recorded tty device |
| --- | --- | --- |
| UE1 / FR1 | `/dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.2-port0` | `/dev/ttyUSB2` |
| UE2 / FR3 | `/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0` | `/dev/ttyUSB6` |

The by-path values follow the physical USB sockets. If the wiring changes,
update `UE_AT_PORT` in the selected `reconnect_ue*.sh` script using its current
physical USB mapping, or override it with `--at-port` on that invocation.
`ttyUSB` numbers can change even when the sockets stay the same. The script
verifies USB ownership and serial IMEI/IMSI before writing any configuration.

## 2. Automation scripts

The script performs the modem/SIM, enable/registration, serving-cell, PDU,
interface/routing and ping self-checks. Start Spark's core, CU and both DUs first
using [Spark quick commands](dual_ue_spark_quick_commands.md). Keep ModemManager
running and close minicom before launching the script.

### Laptop dependencies (install once)

```bash
sudo apt install modemmanager iproute2 iputils-ping python3
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
are preserved. These commands use the copied folder from the transfer above
and enable automatic cell-lock/registration recovery for the port mapping in
section 1. No manual AT commands are needed before launching them:

```bash
# Terminal 1: UE1 / FR1
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --interval 1 --verbose 1
```
```bash
# Terminal 1: UE1 / FR1
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --interval 1 --verbose 2
```
```bash
# Terminal 1: UE1 / FR1
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --interval 3 --verbose 1
```

```bash
# Terminal 2: UE2 / FR3
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 1 --verbose 1
```
```bash
# Terminal 2: UE2 / FR3
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 1 --verbose 2
```
```bash
# Terminal 2: UE2 / FR3
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 3 --verbose 1
```

The command line shows only the retry interval and output level. The role entry
scripts supply the AT port and automatic cell locking; neither needs repeating
in the command. The Python defaults remain: retry interval 1 second, verbosity 1,
registration-client timeout 5 seconds, PDU-disconnect client timeout 2 seconds,
radio grace 10 seconds and recovery cooldown 30 seconds. Add `--verbose 2` for
step output (as above), or use `--verbose 1` for minimal output and `--verbose 3`
for full details. No timeout option is needed for
the short PDU-disconnect limit.

### Initial serial cell lock and registration

With the entry scripts' built-in `--auto-cell-lock --at-port ...`, **each new watcher invocation immediately
prepares its selected UE's radio during step 2**, after modem/SIM discovery and
before normal registration/PDU checks. It does not wait for the 10-second grace
window on this initial preparation.

The script exclusively opens the verified AT port, checks serial IMEI/IMSI,
reads/restores NR SA preferences and the role's cell lock, and requires the exact
lock readback. A correct saved lock is reused. It then reads serving-cell and
registration diagnostics, closes the serial port, enables the modem if needed,
and starts one background PLMN `00101` registration request when registration
is not already proven. The client wait defaults to **5 seconds**. A correctly
registered target cell and working PDU are preserved without a duplicate request.
The same ownership and stale-PDU guards used for later recovery apply here.

Serial/lock preparation must succeed before proceeding to normal connection
checks. If it fails, the watcher reports `FAIL` and retries subject to the normal
cooldown; it cannot skip the serial check just because ModemManager reports a
registered cell. Once preparation succeeds, later attempts and healthy checks
do not repeat it. A pending registration request does not block those checks.
Only successful registration, serving-cell, PDU, route and ping verification
produces connection `SUCCESS`.

At `--verbose 2`, `Startup radio ...` and `Startup radio [OK] ...` describe this
preparation; the latter is not a connection-success result. Level 1 still shows
only attempt numbers/results. Direct calls to `reconnect_ue.py` without
`--auto-cell-lock` retain read-only radio checks; the `reconnect_ue*.sh` entry
scripts always enable automatic cell locking. The separate one-shot
`connect_ue*.sh` entry scripts retain their existing behavior.

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
second. By default, each attempt reads registration state once without a
built-in sleep (`--registration-timeout 0`). An explicit nonzero value adds that
many seconds of state polling inside each attempt and will slow the loop.
Other modem queries, initial enable, AT operations, PDU setup and ping still
have their own execution time; the one-second interval is not a hard deadline
for the complete round. Most external commands retain a 75-second process
limit. **PDU disconnects in the launchers/watchers use `--timeout=2` and a
3-second process watchdog**, including recovery and Ctrl+C shutdown. The
disconnect request still runs synchronously, but no longer uses the previous
long client wait. The detailed log records `PDU disconnect client elapsed=...`
on success or failure. A background registration child instead uses a **5-second mmcli D-Bus
wait** by default and a **10-second process watchdog** (client wait plus 5).
`--registration-request-timeout N` accepts 1..70 seconds and changes both limits.
An explicit value overrides the default: replace `--registration-request-timeout 20`
in an older launch command with `--registration-request-timeout 5`, or omit it.
The parent does not synchronously wait for this child's registration reply.
Healthy checks and recovery both verify source-bound and
ordinary routes and use **one ping in each mode**, rather than the one-shot
launcher's five. Healthy checks read modem/cell/bearer/host state and send ping;
they do not modify the modem, addresses or routes. **Healthy monitoring and failed
retries share this same interval; there is no separate health-check timer.**
Each healthy round sends one source-bound and one ordinary ping per UE to its
Spark service. A failed earlier check ends the round before those pings complete.

### Observe before requesting registration

After initial serial preparation, when radio checks fail, the watcher gives the modem **10 seconds** to
recover on its own (`--registration-grace 10`). It keeps checking current state
at the configured loop interval. During this window it does not force a PDU
disconnect, rewrite cell-lock settings or issue a registration request. Initial
enable of a disabled modem remains part of ordinary startup.

If the registered target cell returns, normal PDU/host/ping verification resumes
immediately. A PDU-only fault with a valid registration/cell follows the normal
PDU-repair path without waiting for this radio grace window.

If radio checks still fail after the window, the watcher performs the guarded
radio preparation below and can start **one background registration client for
this UE**. The attempt returns `FAIL` while connectivity is unverified; later
attempts continue checking rather than waiting inside that client. If modem/cell
state becomes ready, those attempts immediately continue PDU, route and ping
verification even if the registration client has not returned yet. A pending
client prevents another lock/registration recovery for that UE.

| Option | Default | Meaning |
| --- | --- | --- |
| `--interval` | `1` second | Delay after each completed check/attempt. |
| `--registration-grace` | `10` seconds | Observe later radio failures before forced recovery; startup prepares the radio immediately; `0` skips this window. |
| `--registration-timeout` | `0` seconds | Extra state polling inside each attempt; default is one snapshot. |
| `--registration-request-timeout` | `5` seconds | Background mmcli D-Bus wait; process watchdog adds 5 seconds. |
| PDU disconnect, built in | `2` seconds | mmcli client timeout; 3-second process watchdog. No extra launch argument. |
| `--cell-lock-cooldown` | `30` seconds | Minimum gap before another radio recovery after the previous preparation/request finishes. |

A client timeout does not prove that ModemManager stopped its backend task.
After a timeout/busy response the watcher conservatively observes until at least
65 seconds from that request's start before issuing another request; the normal
cooldown also applies. These gates only suppress repeated recovery requests.
Connection checks continue, and a verified connection can succeed during either
window. No CFUN reset or global ModemManager restart is introduced.

A timed-out PDU-disconnect client likewise does not prove that the modem
finished disconnecting. The watcher continues checking modem/bearer state;
`connecting` or `disconnecting` prevents another PDU connect/disconnect or radio
reconfiguration. It does not clear the host path or start a replacement PDU
after a failed disconnect in that attempt. Recovery resumes once the current
state is suitable, with the usual ownership checks and cooldowns.

The watcher now retains a per-UE **pending PDU release** after issuing a
disconnect, including when the client returns an error or times out. A return
to `registered` alone does not make the old connected bearer/IP usable: while
that release remains unconfirmed, the attempt stops before route/ping testing
of the old allocation. This avoids the observed extra failed ping after radio
reconnection.

Once no connected bearer remains and the modem is no longer transitioning,
the watcher clears that UE's old host path, connects the PDU and reads its
current IP in the same attempt. Ordinary connection after a confirmed release
does not wait for the forced-disconnect cooldown. If a different, fully validated
bearer/IP allocation has already appeared, it verifies/rebuilds that allocation
instead of disconnecting it again. If the old connected allocation persists,
another guarded disconnect is allowed after the existing redial cooldown;
the watcher does not ping the old IP while waiting. Ownership, APN and peer/Wi-Fi
protections remain in effect.

The core may assign the **same IP** to a new connection. Fresh PDU/allocation
verification is required; a numerically different address is not required.

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
SIGTERM has the same cleanup behavior. The script first terminates/reaps any
owned registration client (with a kill fallback), then cancels its work/wait,
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
   unproved/mismatching cells fail that attempt and continue polling.
   The entry scripts supply `--auto-cell-lock --at-port ...`, so the watcher performs the guarded radio
   recovery below, then retries full verification on the next attempt. A wrong
   cell never bypasses verification to dial a PDU or rebuild host networking.
2. Finish any pending release before connecting a PDU or reusing an allocation;
   skip old-IP ping checks while an earlier disconnect remains unconfirmed.
   Otherwise connect a disconnected PDU, or reuse a valid connected one. A **suspended**
   connected static bearer on the expected APN triggers a guarded disconnect and
   redial. Host ownership, policy resources, IMEI/IMSI and serving cell must pass
   before a ping/suspended-PDU forced disconnect. Radio-loss recovery has the
   separate configuration checks described below. Radio loss with matching saved
   settings preserves the connected PDU until radio recovery and current-IP
   verification. Foreign APNs, multiple active bearers, malformed
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

The entry scripts used by the [startup commands above](#start-the-watchers)
enable `--auto-cell-lock` for each UE using its built-in by-path AT port.
Copy the complete updated five-file set
before starting; stop old watchers before updating shared helpers. The first
attempt immediately performs the guarded serial lock/registration preparation
described [above](#initial-serial-cell-lock-and-registration). Later persistent
radio failures trigger recovery after the observation window; a separate manual
lock step is unnecessary.

The option requires `--at-port`; it does not guess a tty number. Registration
failure or missing/mismatching serving-cell evidence triggers radio recovery.
Identity/SIM errors, ping failures and host route errors do not directly trigger
AT configuration. A direct `reconnect_ue.py` call without `--auto-cell-lock`
remains read-only for radio settings; `--at-port` alone only enables the
read-only cell fallback. The role-specific shell entry scripts supply both options.

The initial preparation runs immediately. For later radio failures, after the
grace window and with no pending registration client, backend observation or
cooldown gate, each eligible radio recovery does the following:

1. Recheck this modem's IMEI, active SIM IMSI, active-bearer APN and dedicated
   WWAN ownership. Check host resources under a short shared read lock. Reject
   foreign resources, a wrong USB serial device or an occupied port.
2. Exclusively open the AT port and verify `AT+CGSN` and `AT+CIMI`. Read the saved
   lock first, then the NR preferences and live QENG/C5GREG diagnostics. If an
   expected connected bearer remains and the settings match, keep the PDU even
   when MM reports `searching/detached` or AT reports `SEARCH`. Record
   `waiting_radio` and continue checking registration/cell state. No forced
   disconnect or registration request is issued against that active PDU.
3. Handle a proven settings mismatch separately. Read-only inspection records
   the required change before any write. If the live target cell is already
   registered, attempt the missing setting/lock without tearing down its PDU.
   Otherwise release only this UE's owned stale PDU before modifying radio
   settings, after rechecking identity, SIM, APN, allocation, host ownership and
   radio loss. The redial cooldown and pending-release guard still apply. A failed
   disconnect stops before setting writes, host reset or registration. With no
   active bearer, restore `mode_pref=NR5G`, `nr5g_disable_mode=2`, and n78 support
   only where necessary, verifying each readback.
4. Reuse an exact saved lock without a duplicate write; otherwise
   apply this role's lock and require an exact readback:

   | Role | Lock command |
   | --- | --- |
   | UE1 / FR1 | `AT+QNWLOCK="common/5g",1,643680,30,78` |
   | UE2 / FR3 | `AT+QNWLOCK="common/5g",2,639648,30,78` |

   If a lock write returns `+CME ERROR: 902`, read the lock again and retain both
   the error and readback in evidence. Continue only if that independent readback
   exactly matches this UE's target. A `0` or other tuple remains a failure.
5. Record `AT+QENG="servingcell"` and `AT+C5GREG?`, restore serial settings and
   close the port. Once radio registration recovers, reread the current bearer/IP
   and verify its data path. An existing PDU may resume with its original IP;
   a replacement allocation is rebuilt using its current IP. Radio recovery alone
   does not justify reusing a cached allocation or force a new IP. A suspended
   bearer or sustained ping failure can trigger the guarded redial described
   above, after serving-cell verification. With no active PDU, enable the modem
   if needed and launch one background registration
   client using `mmcli -m <current-selected-modem> --3gpp-register-in-operator=00101 --timeout=5`.
   ModemManager may reject registration while it still considers the modem
   connected; preserve a correctly configured active PDU while waiting for natural
   radio recovery. A generic `connected`
   state alone is not accepted as registration: the startup check also requires
   3GPP `home` or `roaming` before accepting PLMN and NR SA access.
6. For a later radio failure, mark the current attempt `FAIL`: applying a lock is not proof of connectivity.
   On the next attempt, require the usual registration, exact serving cell,
   PDU, current-IP routing, both pings and final checks before `SUCCESS`.
   Initial preparation instead continues these checks in the same attempt when
   possible; a pending/unready registration still leaves that attempt failed.

The first later radio failure begins the observation window. After guarded radio
preparation, a pending background request prevents duplicate radio recovery.
When a request ends, or preparation fails before a request starts, subsequent
radio recoveries have a **30-second minimum gap** by default. Checks and verified
PDU recovery continue during the grace, pending-request, cooldown and possible
backend-observation phases. A correct saved lock is reused regardless of these
intervals. `--cell-lock-cooldown` accepts positive seconds; reducing it does not
cancel a pending request or skip the backend-observation guard.

The default registration client wait is **5 seconds**, with a **10-second
process watchdog**; adjust the client wait using `--registration-request-timeout`.
The child writes to private files, so output cannot fill a pipe and block its
exit. Level 2 shows the observing/pending/completed phases; level 3 also prints
commands and the collected child output. Level 1 still prints only connection
attempt numbers/results (plus required shutdown/cleanup failures). A `FAIL`
during observation or a pending request means that round did not verify a
connection; it does not mean the background request has already failed.

If MM reports `disconnecting`, level 2 explicitly shows **waiting for this UE's
PDU release** and the elapsed time since this watcher requested the disconnect.
No duplicate disconnect, serial reconfiguration or forced registration is
issued while that operation remains in progress. A 2-second disconnect client
timeout does not cancel the modem/backend operation. A `connecting` modem is
likewise observed until its current operation finishes.

The one-shot startup helper now sleeps at most **0.25 seconds** between
registration polls; the reconnect loop still uses the requested `--interval`
and defaults to a zero extra registration-state wait. Healthy monitoring has no
new fast poll. Spark's base CU config and identity overlay now use
`cu_cp.request_pdu_session_timeout: 10` seconds, effective at the next CU start.
This avoids the earlier 3-second PDU-request window competing with laptop
registration checks. Changing the file does not alter the running CU.

Serial/registration work never holds the shared host-network lock. UE1 and UE2
retain separate ownership and cooldown state. Healthy checks never write AT
configuration. No CFUN reset or ModemManager restart is performed. Ctrl+C still
closes the serial context and runs the selected UE's normal shutdown cleanup.
An unverified write/readback leaves the attempt failed; earlier successful
writes may already have taken effect and are recorded in `attempts.jsonl`.

Lowering DU TX gain can leave too little downlink signal for cell acquisition
or registration. Restoring a lock does not restore RF coverage. If registration
continues to fail with the expected lock, restore adequate DU gain/coverage and
check CU/DU/core status. A later operator-reported connection self-check recovery
is recorded below; the exact radio/PDU recovery branch after a gain change still
needs retained detailed evidence.

The NR preference query/write formats and `nr5g_disable_mode=2` (disable NSA)
come from the [Quectel RG50xQ/RM5xxQ AT manual](https://www.quectel.com/content/uploads/2024/05/Quectel_RG50xQRM5xxQ_Series_AT_Commands_Manual_V1.2.pdf).
The lock readback format also matches the retained
[UE2 operator evidence](evidence/2026-10-13_du2_registration/operator_at_readback.txt).
The registration option is provided by [ModemManager's 3GPP CLI](https://github.com/linux-mobile-broadband/ModemManager/blob/main/cli/mmcli-modem-3gpp.c).
The [mmcli entry point](https://github.com/linux-mobile-broadband/ModemManager/blob/main/cli/mmcli.c)
defaults to a 30-second operation timeout; the watcher overrides it specifically
for this registration request.
Its [registration handler](https://github.com/linux-mobile-broadband/ModemManager/blob/main/src/mm-iface-modem-3gpp.c)
rejects operations while the modem is connected/connecting/disconnecting and
performs fresh registration checks before deciding whether to register again.

### CME 902 after a DU gain drop

The operator's 2026-10-24 trace started with a successful UE2 connection, then
failed recovery after a DU2 TX-gain experiment (`10` dB, later restored to `60`
dB in the DU terminal). The UE trace recorded both:

```text
state=connected 3gpp=searching packet=detached PLMN=-- access=--
+QNWLOCK: "common/5g",0
+CME ERROR: 902
```

The lock readback was `0` on both captured recovery attempts; this was not a
duplicate write of an already-correct lock. The original recovery aborted at the
rejected write before requesting registration, and retained the stale bearer
until Ctrl+C shutdown. The countdown messages were the configured cooldown.
The trace ended with successful selected-UE shutdown, not successful recovery.

The earlier fix released a verified stale PDU before attempting lock/registration.
The current flow first inspects the saved lock/preferences and live AT state:
matching settings preserve the active PDU while radio recovers; only a proven
configuration mismatch can enter that radio-repair disconnect branch. Restored
radio service is followed by current bearer/IP and traffic verification, with
suspended/ping-failure recovery handled separately. Copy the updated five files and restart the
watcher using the commands above. These cases pass offline regression tests;
the modem's precise reason for 902 and which recovery branch resolves it on the
testbed remain unverified. If 902 persists and the lock still reads `0`, retain `run.log` and
`attempts.jsonl`; the script will keep reporting failure rather than dialing
with an unverified cell lock. No CFUN reset or ModemManager restart is added.

### Registration times out with a correct saved lock

The subsequent 2026-10-24 operator run read back the correct UE2 lock
`2,639648,30,78`, with NR5G mode, NSA disabled, and n78 included. It still reported
`QENG=SEARCH`, `C5GREG=0,0`, and MM `enabled/idle/detached`. The registration CLI
returned `Timeout was reached`; the next attempt began about 36 seconds after
the first. This is consistent with the old command's default 30-second mmcli
wait plus the five-second initial state check and other queries. The 75-second
outer watchdog did not override that shorter inner timeout.

An intermediate implementation explicitly used a 70-second synchronous wait.
The current implementation prepares the serial lock/registration immediately
on startup. Later radio failures first get a 10-second observation window.
Any required registration client runs in the background with **`--timeout=5`
by default**. Use
`--registration-request-timeout N` (1..70 seconds) to adjust that client limit;
`--registration-timeout` now defaults to `0` for a single state snapshot per
attempt. Registration events retain the requested limits, elapsed time and
result/error independently of the connection-attempt results. A returned request
still requires all connection checks before `SUCCESS`.

A correct saved lock proves the configuration tuple, not reception of the
target cell. If SEARCH persists, investigate the radio path and DU health.
Spark's DU2 startup transcript later confirmed `tx_gain 0 70` (the YAML baseline)
after the earlier 60 dB setting. The DU2 log during the supplied registration
window also contained RF `underflow` and `late` warnings. Their causal link to
this modem's failed cell acquisition has not been established. Increasing the
client wait does not repair a missing/unusable radio signal or DU scheduling
failures. Live acceptance of the deferred/background 5-second request flow
remains pending.

### Operator-reported connection recovery

Later on 2026-10-24, the operator supplied this UE2 watcher output at
`--interval 1 --verbose 1`, with automatic cell locking enabled:

```text
UE2 / FR3 attempt 1 ... SUCCESS
UE2 / FR3 attempt 2 ... FAIL
UE2 / FR3 attempt 3 ... FAIL
UE2 / FR3 attempt 4 ... FAIL
UE2 / FR3 attempt 5 ... FAIL
UE2 / FR3 attempt 6 ... FAIL
UE2 / FR3 attempt 7 ... FAIL
UE2 / FR3 attempt 8 ... SUCCESS
```

This is an operator-reported successful recovery of the script's connection
self-checks: it was initially healthy, retried failed checks, and passed again
on attempt 8. A watcher `SUCCESS` requires registration, serving cell, PDU/host
configuration, routes, both ping modes and final verification.

Minimal output does not establish the failure trigger, elapsed recovery time,
whether the modem re-registered/redialled or changed IP, or whether MPX/video
traffic recovered. Retain this run's `run.log` and `attempts.jsonl` for those
details. The output does not identify the installed timeout implementation, so
it is not acceptance evidence for the deferred/background registration flow.

### Optional parameters

For read-only radio diagnosis, invoke the Python helper directly, without
`--auto-cell-lock`. Its `--at-port` uses the same owned-port, read-only serving-cell fallback described in
[the one-shot guide](dual_ue_automation.md#serving-cell-mismatch-or-unavailable-getcellinfo).
Use the option on a watcher as follows, replacing the serial link with this UE's
verified AT port:

```bash
sudo python3 -B ~/falcon-ue-connect/reconnect_ue.py --ue 2 --verbose 2 \
  --at-port /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0
```

For manual diagnosis only, stop the affected watcher and wait for its shutdown
result before opening minicom or changing serial settings; close minicom before
restarting it. Manual modem selection, port opening and AT commands are in the
[UE1 / FR1 procedure](dual_ue_laptop_quick_commands.md#12-verify-the-at-port-and-restore-the-du1-lock)
and [UE2 / FR3 procedure](dual_ue_laptop_quick_commands.md#22-verify-the-at-port-and-restore-the-du2-lock).
Install `minicom` separately if needed for that diagnosis. Optional bounded operation:

```bash
# Retry until the first successful verification, then exit.
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --once --interval 1 --verbose 2
# At most five actual connection attempts; exit 1 if the last attempt failed.
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --once --max-attempts 5 --interval 1 --verbose 3
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
forced-redial reason when applicable. `registration_events.jsonl` separately records background request start,
completion and cancellation, with modem/device identity, PID, time limits,
elapsed time, raw result/error and private stdout/stderr file paths. An attempt's
`registration_request` is a snapshot; use the event file for the later outcome.
A failed client request can coexist with successful connection checks if the
modem recovers independently. `summary.json` is written on exit and records the
last registration event, initial `startup_radio` preparation outcome, and the
PDU-disconnect client timeout, along with the
remaining `pending_pdu_release` state and the
last verified state **before shutdown** (not a post-exit measurement)
and the nested `shutdown` completion/error. With automatic cell locking enabled,
`attempts.jsonl` also records `radio_recovery`: the `startup` / `radio_failure`
trigger, original radio error,
commands/writes attempted, previous/verified lock, diagnostic QENG/C5GREG output,
lock reuse/write/error details, live serial registration, stale-PDU disconnect,
registration-request snapshots and `observing` / `registration_pending` /
`backend_observation` / `waiting_radio` / `waiting_pdu_release` /
`waiting_pdu_connect` / `applied` / `failed` / `cooldown` / `interrupted` results.
`pdu_preserved` records a correctly configured active PDU being retained during
radio/state recovery; `required_write` records a proven configuration difference.
`applied` means the radio settings were applied; only the full connection checks
can produce connection `SUCCESS`. A `startup_radio` status of `completed` likewise
means preparation succeeded, not that registration or connectivity was proven.
Each affected attempt also records `pending_pdu_release`: the prior bearer/IP,
request identity/time and `requested` / `waiting` / `retry_due` / `released` /
`allocation_replaced` outcome. This is separate from connection `SUCCESS`.
`attempts.jsonl` marks a cancelled
in-progress attempt as `interrupted`. Logs accumulate
for the invocation; retain the evidence you need and remove old run directories
after stopping the watcher. Signal exit codes are 130 (Ctrl+C) / 143 (SIGTERM),
after the selected-UE shutdown attempt. Cleanup failure remains visible in output
and the summary; successful cleanup requires zero bearers and modem disabled.

These watchers repair the PDU and laptop network, and can restore radio settings
with `--auto-cell-lock`. A running MPX client then follows
host IP changes as described [below](#which-ip-bindings-change-and-how-mpx-follows-them).
They do not start MPX or restart applications bound explicitly to an old IP.
Offline simulated checks pass, and the operator has reported a connection
self-check recovery as recorded above. **Timed radio-failure trials, attribution
of the recovery branch, and MPTCP/video traffic acceptance remain pending**.

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
