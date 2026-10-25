# Dual UE Laptop Automation — One-shot Startup and Self-check

Updated: 2026-10-24. Developer: Ruibin.

Run these scripts on the **UE laptop**. Start the core, CU and both DUs on
**Spark first**, following [Spark quick commands](dual_ue_spark_quick_commands.md).
This guide covers one-shot modem enable/registration, live serving-cell checks,
IPv4 PDU connection, WWAN/policy routing and ping. After success the launcher
**stays in the terminal, blocking until Ctrl+C**. It performs no further status
queries or ping during that wait. For ongoing monitoring/recovery use the
[laptop automatic reconnect Quick Start](dual_ue_laptop_reconnect_quick_start.md).
**Use `connect_ue1.sh` / `connect_ue2.sh` for this guide.** The separate
`reconnect_ue*.sh` entry scripts run continuous recovery and include their own
AT port/automatic cell-lock options. Those options are not added to the one-shot
entry scripts. Both modes use the same per-UE lock to reject simultaneous ownership.

**Acceptance scope, 2026-10-24:** cold-start reproduction, full repeatability
and bidirectional disturbance/survivor testing are
[supplemental experiments](development/dual_ue_supplemental_experiments.md).
They are not current Dual UE acceptance criteria or merge prerequisites.

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
check/restore the selected role's lock through its AT port.

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

The entry points are [`connect_ue1.sh`](../scripts/dual_fr1/connect_ue1.sh) and
[`connect_ue2.sh`](../scripts/dual_fr1/connect_ue2.sh). Both use
[`connect_ue.py`](../scripts/dual_fr1/connect_ue.py) and
[`reset_ue_network.py`](../scripts/dual_fr1/reset_ue_network.py).
Keep these **four files together** when copying them to the laptop. The older
standalone `~/falcon-reset-ue-network.py` does not install the launchers.
Stop the selected UE's existing launcher/watcher before a new run or manual
configuration. **Ctrl+C now shuts down that UE**, including bearer deletion and
modem disable. Stop both roles before updating their shared helper files, then
restart them to load the new version.

### Transfer the four scripts from Spark

Run this block in **Bash on the UE laptop**. It transfers all four files from
Spark into `~/falcon-ue-connect` through **one SSH connection**:

```bash
(
  set -euo pipefail
  mkdir -p ~/falcon-ue-connect

  ssh -T nyu@10.20.44.26 \
    'tar -C /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1 -czf - connect_ue1.sh connect_ue2.sh connect_ue.py reset_ue_network.py' |
    tar -xzf - -C ~/falcon-ue-connect

  ls -l ~/falcon-ue-connect/{connect_ue1.sh,connect_ue2.sh,connect_ue.py,reset_ue_network.py}
)
```

Enter the password for **Spark's `nyu` account** when prompted. A normal
successful password login needs one authentication for this connection. The
earlier `scp` command used Bash brace expansion to produce four separate remote
sources, which could cause repeated SSH authentication; the command above
streams one archive containing exactly the four scripts. If SSH or extraction
fails, the block stops before the final file listing.

The `ls` command must list all four files before continuing. Repeat the transfer
after updating the scripts on Spark so that the laptop uses the current versions.
The archive is streamed directly between `tar` processes; no intermediate archive
or temporary extraction directory is created. Repeating the transfer overwrites
the four named files. **Stop active launchers and reconnect watchers before replacing their
files**, then restart them so the running Python process loads the new version.

The management addresses for this setup are Spark `10.20.44.26` and laptop
`10.20.73.246`. Spark's SSH port 22 was confirmed listening on 2026-10-24.
The earlier push from Spark to the laptop returned `Connection refused` on
the laptop's port 22; pulling from the laptop uses Spark's SSH listener.
If the management addresses change, run `ip -4 route get 10.20.73.246` on
Spark, substituting the laptop's current IP if needed, and use the reported
`src` address in the `ssh` command.

### Run

After the transfer, use **two laptop terminals**. Start UE1 first:

```bash
# Laptop terminal 1: leave this running after PASS.
sudo bash ~/falcon-ue-connect/connect_ue1.sh
```

After UE1 prints PASS and its waiting message, start UE2 in terminal 2:

```bash
# Laptop terminal 2: leave this running after PASS.
sudo bash ~/falcon-ue-connect/connect_ue2.sh
```

`[sudo] password for david:` is a separate prompt for the **laptop's `david`
account**. It grants local permission to configure the modem and networking.
It is independent of the Spark password used for the file transfer. Running
the two launchers in separate terminals can require separate local sudo
authentication; an expired cache can prompt again.

A successful run **holds the connection and waits for Ctrl+C** after the ping
checks. Waiting uses `signal.pause()`, with no periodic wakeup, modem queries,
health probes, ping or automatic redial. The Python process and a few open file
handles remain; it does not busy-wait. No shared network lock is held while
idle; the other UE can prepare, monitor and stop independently. For ongoing monitoring, use the separate
[laptop automatic reconnect Quick Start](dual_ue_laptop_reconnect_quick_start.md).

These are self-checking connection launchers: they perform checks and prepare
the selected UE through successful ping. Without extra options, the terminal
shows the current step, `[OK]` / `[FAIL]` markers, final `PASS`, the idle-wait
message and the run evidence directory. After Ctrl+C it shows shutdown progress
and the saved evidence path. Modem details, commands and raw ping output are saved in the log.
Use `--verbose` to also show that full output in the terminal:

```bash
# Laptop terminal 1
sudo bash ~/falcon-ue-connect/connect_ue1.sh --verbose
# Laptop terminal 2
sudo bash ~/falcon-ue-connect/connect_ue2.sh --verbose
```

Example of the default display (illustrative, not a new hardware result):

```text
[1/9] Modem / SIM identity ... [OK]
[2/9] Modem registration ... [OK]
[3/9] Serving cell ... [OK]
[4/9] PDU session / serving-cell recheck ... [OK]
[5/9] WWAN / policy routing / Wi-Fi fallback block ... [OK]
[6/9] Source-bound and ordinary routes ... [OK]
[7/9] Source-bound ping ... [OK]
[8/9] Ordinary ping ... [OK]
[9/9] Final identity / cell / network verification ... [OK]
PASS: UE1 / FR1 connected
UE1 connected; waiting for Ctrl+C to shut down (no polling or ping)
```

The step label appears immediately; its completion marker follows when the
operation finishes. Errors and required manual serial instructions remain
visible in both modes. `--verbose` changes only terminal detail; checks,
connection actions, exit status and full log capture are the same.
During registration, the detailed output reports the modem state, 3GPP
registration/packet-service states, PLMN, access technology and elapsed wait.
Startup registration polls sleep at most **0.25 seconds** between queries;
this faster polling ends once registration is ready. The default passive hold
after success still performs no polling or ping.
It also announces each modem/SIM query, so a slow query can be distinguished
from a completed query reporting an unregistered modem. These details are
saved in `run.log` even without `--verbose`.

If the laptop already has a current Falcon checkout, you can also run from
that checkout's repository root:

```bash
# Laptop terminal 1
sudo bash scripts/dual_fr1/connect_ue1.sh
# Laptop terminal 2, after UE1 PASS
sudo bash scripts/dual_fr1/connect_ue2.sh
```

The remaining examples use the copied files under `~/falcon-ue-connect`.

The commands above demonstrate UE1 followed by UE2. The two roles can also
start concurrently in separate terminals; each retains its own modem lock.
Only host network transactions are coordinated as described below.
A run can reuse an already correct PDU and host path when no other script owns
that role. Ctrl+C on a current holder/watcher first shuts that role down; a later
launcher enables/reconnects it. No cell-lock configuration is sent automatically.

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

### Ctrl+C shutdown and optional immediate exit

Ctrl+C (SIGINT) or SIGTERM cancels the current work/wait and invokes the existing
[`reset_ue_network.py --shutdown`](../scripts/dual_fr1/reset_ue_network.py) logic
for **only this UE** before exit:

1. Verify this role's current modem IMEI/SIM/device identity; rediscover by IMEI
   if its object has disappeared or been replaced.
2. Install/retain its independent destination block against Wi-Fi fallback.
3. Disconnect the selected PDU, clear its IPv4 addresses/routes/policy rules,
   and return the WWAN to DOWN / MTU 1500.
4. Delete all of the selected modem's listed bearers and disable that modem.
5. Verify shutdown, write the outcome to `summary.json`, then exit 130 for Ctrl+C
   or 143 for SIGTERM. Management Wi-Fi and the other UE remain available.

Shutdown takes the shared lock only for its host updates/verification; modem
operations happen outside it. Repeated Ctrl+C/SIGTERM does not interrupt cleanup;
cleanup children are isolated from subsequent terminal stop signals. A failed disconnect,
bearer deletion or disable prints `shutdown [FAIL]` and records the error; it
never prints successful shutdown without the final checks.

This applies to **both** one-shot entry points and the reconnect watchers,
including Ctrl+C during startup or `--check-only`. A normally completed
`--check-only` remains read-only and exits 0 immediately. **Interrupting a
`--check-only` run explicitly shuts down its selected UE.**

For the previous batch behavior (verify then exit, leaving the UE connected),
use the optional flag:

```bash
sudo bash ~/falcon-ue-connect/connect_ue1.sh --exit-on-success
sudo bash ~/falcon-ue-connect/connect_ue2.sh --exit-on-success
```

The default is the low-resource wait. `--exit-on-success` changes only successful
completion; Ctrl+C before that exit still invokes shutdown. A non-signal failure
exits 1 with evidence for diagnosis; it does not claim shutdown completed.

### What each run does

1. Reject execution on a host with either Spark service IP locally assigned.
   Select exactly one modem by the role's IMEI and verify the active SIM IMSI
   and current device identifier. Recheck identity before modem changes and
   host reset.
2. Enable that modem if disabled and poll registration with a 45-second wait budget.
   Read the **actual serving** 5GNR cell with
   `mmcli -m <current-path> --get-cell-info -K`. Require exactly one serving NR
   record with the role's PCI and NCI, plus registered PLMN `00101` and NR
   access without LTE. Neighbors are not serving-cell evidence. When reported,
   the cell's PLMN, TAC and NR-ARFCN must also match; the backend may report the
   carrier or SSB NR-ARFCN. Missing optional radio fields are not claimed as
   verified. Cell IDs and PCI in this interface are hexadecimal, as specified
   by the [ModemManager interface](https://github.com/linux-mobile-broadband/ModemManager/blob/main/introspection/org.freedesktop.ModemManager1.Modem.xml).
3. If the serving cell matches, **skip serial configuration**. If it differs,
   is missing, or cannot be proved, stop with the expected identifiers and
   manual serial instructions. No PDU or routing configuration is started
   after an initial failed serving-cell check; a previously disabled modem
   may have been enabled for registration.
4. Install or validate the independent destination `unreachable` block. Reuse
   one connected bearer for the expected APN, or run
   `mmcli --simple-connect=apn=<role-apn>,ip-type=ipv4`. A foreign APN or multiple
   active bearers stop the run. Read the connected bearer and require a valid,
   unsuspended static IPv4 configuration in the role's pool. Recheck the serving
   cell after connecting.
5. Validate ownership of the dedicated `qmi_wwan` interface and the role's policy
   resources. Reuse a complete host path; otherwise reset this role's old host
   IPv4 configuration while keeping the PDU. The independent destination block
   stays installed. Require an ordinary route lookup to the service IP to fail
   after reset before rebuilding.
6. Install source and destination guards first, set the current bearer MTU and
   bring up the interface. Add the current address with `noprefixroute`, a
   service `/32` route in table `151` or `152`, and both source and destination
   lookup rules. No WWAN default route is installed. Source rules are scoped to
   this UE IP and its Spark service; destination rules also catch ordinary
   traffic without a bound source.
7. Verify both `ip route get <service> from <current-UE-IP>` and ordinary
   `ip route get <service>` select the correct WWAN and policy table. Ordinary
   traffic must also select the current bearer source IP. Run five source-bound
   pings and five ordinary pings. Each ping command must succeed; its full
   output, including packet loss, is saved. A successful ping command can still
   report some packet loss, so inspect the log for link quality.
8. Recheck the current bearer, serving cell, host configuration and routes.
   Check management state across the run. Check the other UE's addresses,
   rules, main/private routes and interface UP/MTU state immediately before
   and after each exclusive host update, allowing its independent recovery
   between those transactions. Print `PASS` only after all checks succeed.

Management Wi-Fi remains available for SSH and destinations outside these
two Spark service IPs. The independent `20151` / `20152` blocks survive the
existing role reset and shutdown helper. They are runtime rules: a laptop
reboot clears them, and the next successful script preflight installs them
again. This does not change a NetworkManager profile or install a boot service.

### Waiting at modem registration

Step 2 waits for ModemManager state `registered`, `connecting` or `connected`
and 3GPP registration `home` or `roaming`, then verifies PLMN `00101` and NR SA
access. Generic `connected` alone does not pass when 3GPP is still `searching`.
`enabled` means powered on but not
registered, while `searching` means searching for a network; neither passes this
step. See the [ModemManager state definitions](https://www.freedesktop.org/software/ModemManager/doc/1.18.0/ModemManager/ModemManager-Flags-and-Enumerations.html#MMModemState).

With `--verbose`, a wait can look like this (illustrative):

```text
Registration: querying current modem / active SIM status (wait budget 45s; command timeout 75s)
Registration: state=enabled 3gpp=idle packet=detached PLMN=-- access=--; elapsed=0s
Registration: waiting 0.25s before the next modem / SIM query
```

The script waits at most 0.25 seconds between completed status polls. The wait
budget is checked between queries; an individual external command can take up
to 75 seconds, so it is not a hard wall-clock limit for the whole step. On
timeout, the error includes the last reported registration state. On Ctrl+C,
the step prints `[CANCELLED]`, the summary records `interrupted`, and the launcher
runs selected-UE shutdown before exiting 130. Cancellation does not establish that network registration failed.

The Spark CU configuration now sets `cu_cp.request_pdu_session_timeout: 10`
seconds in the base file and identity overlay. It takes effect at the next CU
start. The earlier 3-second window released a newly connected UE before the
laptop requested a PDU during a measured startup. Faster polling and the longer
CU window reduce this race; they do not guarantee a specific registration time.
Use the [Spark CU launch sequence](dual_ue_spark_quick_commands.md#4-start-identity-ric-then-identity-enabled-cu-in-separate-terminals).

For a bounded read-only diagnosis, use the current modem path/index printed by
the IMEI check; indices can change after USB reconnect:

```bash
read -r -p 'Current UE1 modem path/index from the IMEI check: ' MODEM
sudo timeout 12s mmcli --timeout=10 -m "$MODEM" -K
sudo timeout 12s mmcli --timeout=10 -m "$MODEM" --get-cell-info -K
printf 'cell-info exit=%s\n' "$?"
```

`enabled / idle / detached`, no reported PLMN/access technology and
`NoNetworkFound` from GetCellInfo indicate the modem has no usable serving-network
evidence at that time. Verify Spark DU1/CU/core availability and the selected
UE's radio mode, cell lock and signal before PDU/IP troubleshooting. The script
does not automatically change the cell lock to overcome this condition. Follow
the serving-cell procedure below when manual serial checks are required.

### Serving-cell mismatch or unavailable GetCellInfo

Follow the script's expected identifiers and the manual's
[UE1 serving-cell steps](dual_ue_laptop_quick_commands.md#12-verify-the-at-port-and-restore-the-du1-lock)
or [UE2 serving-cell steps](dual_ue_laptop_quick_commands.md#22-verify-the-at-port-and-restore-the-du2-lock) to identify
this modem's AT port. Confirm `AT+CIMI` before any manual configuration.
If necessary, set NR SA preferences and the correct lock in minicom, read back
`AT+QNWLOCK="common/5g"`, `AT+QENG="servingcell"` and `AT+C5GREG?`, then exit
minicom and rerun the same connection script.

If GetCellInfo is unavailable or omits PCI/NCI, an explicitly selected AT port
can supply **read-only** serving-cell evidence:

```bash
# Recorded USB wiring: UE1 on 4-4, UE2 on 4-3; confirm the role in section 1.
sudo bash ~/falcon-ue-connect/connect_ue1.sh \
  --at-port /dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.2-port0

sudo bash ~/falcon-ue-connect/connect_ue2.sh \
  --at-port /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0
```

The script first tries GetCellInfo. If that proves a matching cell, it does
not open the serial port. A complete mismatching cell is rejected even if
`--at-port` was supplied. The serial fallback checks that the tty and WWAN
belong to the same physical USB device, rejects a busy port, and queries
`AT+CGSN`, `AT+CIMI` and `AT+QENG="servingcell"`. It verifies serial IMEI/IMSI
before accepting a matching NR SA cell. Serial termios settings are restored
when the query ends. No lock, band, mode or CFUN command is sent automatically.
Keep ModemManager running; do not interrupt the other UE to obtain an AT port.

For automatic lock restoration and a PLMN registration request after radio
failure, use the separate reconnect watcher, whose role entry scripts include the
[`--auto-cell-lock --at-port ...` option](runbooks/dual_ue_laptop_reconnect_reference.md#automatic-cell-lock-and-registration-after-radio-failure).
This one-shot launcher keeps its read-only AT fallback.
With those built-in options, the watcher immediately verifies/restores the serial cell lock
and checks/requests registration on startup. Later radio failures get a 10-second
observation window before forced recovery. Any required background registration
client uses a default 5-second timeout.
Its `--registration-grace` and `--registration-request-timeout` options belong
to the reconnect scripts; the one-shot launcher's passive-wait behavior is unchanged.
The shared launcher's PDU-disconnect requests, including Ctrl+C cleanup, now
use a built-in 2-second mmcli client timeout and a 3-second process watchdog.
Success returns immediately. A timeout remains a failure and does not imply
that the modem's backend disconnect has completed; incomplete shutdown is reported.

### Recover a dropped or stuck UE PDU

The [laptop automatic reconnect Quick Start](dual_ue_laptop_reconnect_quick_start.md) covers
continuous recovery, including guarded suspended-PDU and repeated-ping-failure
redials. This section describes **manual recovery with a one-shot verification**. Stop any watcher for the
selected role before running it.

After the obstruction is removed and radio coverage returns, rerun only the
affected role's connection script. It reuses a valid bearer or connects a
disconnected one, reads the current allocation and rebuilds stale host state.

If the modem still reports a connected bearer but it is suspended, or ping
continues failing after coverage returns, explicitly disconnect that role's
PDU and clear its host path before reconnecting. For **UE2 / FR3**, run on
the **laptop**:

```bash
sudo python3 ~/falcon-ue-connect/reset_ue_network.py --ue 2 --disconnect &&
  sudo bash ~/falcon-ue-connect/connect_ue2.sh --verbose --registration-timeout 90
```

For **UE1 / FR1**:

```bash
sudo python3 ~/falcon-ue-connect/reset_ue_network.py --ue 1 --disconnect &&
  sudo bash ~/falcon-ue-connect/connect_ue1.sh --verbose --registration-timeout 90
```

The existing reset helper selects the modem by IMEI. For a modem reported as
connected, `--disconnect` sends `--simple-disconnect`, clears the selected
role's host IPv4 addresses/routes/rules and leaves the modem enabled. The
independent `20151` / `20152` destination blocks stay installed. The other
UE and management Wi-Fi are preserved. `&&` prevents the connection script
from running if reset fails. Keep any required `--at-port` option on the
connection command.

This is an explicit recovery operation; use it after checking the failed
stage, radio coverage and server availability. A failed ping alone does not
establish that a PDU is broken. The one-shot launcher reports the failure so that a
server outage or a deliberate experiment fault does not trigger repeated
redials. If ModemManager rejects the disconnect or the new connection still
fails, retain the error and run log for diagnosis. A fresh physical-modem
recovery test remains pending.

Offline recovery checks cover a suspended bearer followed by a new IP on
either role, failed ping followed by recovery with the same IP, failed
disconnect, preservation of the other UE, and retention of the independent
Wi-Fi fallback block.

### Which IP bindings change, and how MPX follows them

The launcher reads the current bearer allocation and refreshes the WWAN address,
role-table source route and source/destination policy rules. Refresh shell
variables and restart ordinary traffic commands explicitly bound to an old UE IP.
For MPX subnet matching, automatic address tracking, subflow recovery and the
retained experiment evidence, see
[IP changes and MPX in the laptop reconnect reference](runbooks/dual_ue_laptop_reconnect_reference.md#which-ip-bindings-change-and-how-mpx-follows-them).

### Recheck, logs and failure handling

Normally completed modem/PDU/host checks, without enable, connect, route changes
or ping (Ctrl+C/SIGTERM still invokes selected-UE shutdown):

```bash
sudo bash ~/falcon-ue-connect/connect_ue1.sh --check-only
sudo bash ~/falcon-ue-connect/connect_ue2.sh --check-only
# Add --verbose to show full details during read-only checks too.
sudo bash ~/falcon-ue-connect/connect_ue1.sh --check-only --verbose
```

The two ping steps show `[SKIP: check-only]` in this mode; they are not marked
successful without sending traffic.

Use `--registration-timeout 90` for a longer registration wait, or
`--output-root /existing/directory` to choose the evidence parent directory.
Every normal invocation prints a private directory such as
`/tmp/falcon-ue1-connect-<unique-suffix>`, containing `run.log` and
`summary.json`. Read these with sudo or copy them with appropriate ownership
before sharing. The summary records UTC start/end times, role, modem identity,
APN, serving-cell evidence, current bearer/interface/IP/prefix/MTU, both ping
outputs and final status, plus the latest registration snapshot when available.
A connected `summary.json` is saved before the idle wait. On interrupt it is
updated with the stop signal, lifecycle and nested `shutdown` completion/error.
`run.log` retains full printed command/details/ping
output even when `--verbose` is absent. Dependency/root/lock failures occur before a run
directory is allocated. It does not record modem authentication properties.

Normal startup stays in the idle wait after `connected`. Exit status is `0` for
`connected` with `--exit-on-success`, or `checked` with `--check-only`.
Failure exits `1`, with the failed stage and reason. A serving-cell failure is
marked `serial_check_required`; Ctrl+C exits `130` with status `interrupted`
after selected-UE shutdown, with an explicit cancellation reason and cleanup
outcome; SIGTERM exits `143`. Foreign policy resources and non-role addresses
are preserved and require manual inspection. If the script's host rebuild
fails midway, it attempts to clear only this role's partial host path while
retaining the independent block; it reports any incomplete cleanup. A failed
PDU attempt or a later cell/ping check can leave the selected modem enabled and
the PDU connected for inspection. Ping failure keeps a fully built path for
diagnosis and does not print a final success. Rerun after resolving the cause.

Ctrl+C already performs shutdown for an active holder/watcher. After the process
has exited, these remain available for manual reset or cleanup:

```bash
sudo python3 ~/falcon-ue-connect/reset_ue_network.py --ue 1
sudo python3 ~/falcon-ue-connect/reset_ue_network.py --ue 2
# To disconnect PDU, clear this role's host path/bearers and disable the modem:
sudo python3 ~/falcon-ue-connect/reset_ue_network.py --ue 1 --shutdown
sudo python3 ~/falcon-ue-connect/reset_ue_network.py --ue 2 --shutdown
```

The automation has offline tests with simulated ModemManager/kernel state and
the archived QENG readbacks. **A fresh end-to-end run on the two physical laptop
modems is still required.** No new live ping or MPTCP result is asserted here.

