# Dual UE Laptop Automation — One-shot Startup and Self-check

Updated: 2026-10-24. Developer: Ruibin.

Run these scripts on the **UE laptop**. Start the core, CU and both DUs on
**Spark first**, following [Spark quick commands](dual_ue_spark_quick_commands.md).
This guide covers one-shot modem enable/registration, live serving-cell checks,
IPv4 PDU connection, WWAN/policy routing and ping. A successful launcher exits;
monitoring during an experiment is covered separately in the
[laptop automatic reconnect Quick Start](dual_ue_laptop_reconnect_quick_start.md).

The entry points are [`connect_ue1.sh`](../scripts/dual_fr1/connect_ue1.sh) and
[`connect_ue2.sh`](../scripts/dual_fr1/connect_ue2.sh). Both use
[`connect_ue.py`](../scripts/dual_fr1/connect_ue.py) and
[`reset_ue_network.py`](../scripts/dual_fr1/reset_ue_network.py).
Keep these **four files together** when copying them to the laptop. The older
standalone `~/falcon-reset-ue-network.py` does not install the launchers.
Stop the selected UE's reconnect watcher before a one-shot run or manual reset;
stop both watchers before updating their shared helper files.

## Transfer the four scripts from Spark

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
the four named files. **Stop active reconnect watchers before replacing their
files**, then restart them so the running Python process loads the new version.

The management addresses for this setup are Spark `10.20.44.26` and laptop
`10.20.73.246`. Spark's SSH port 22 was confirmed listening on 2026-10-24.
The earlier push from Spark to the laptop returned `Connection refused` on
the laptop's port 22; pulling from the laptop uses Spark's SSH listener.
If the management addresses change, run `ip -4 route get 10.20.73.246` on
Spark, substituting the laptop's current IP if needed, and use the reported
`src` address in the `ssh` command.

## Run

After the transfer, run on the **UE laptop**:

```bash
cd ~/falcon-ue-connect
sudo bash connect_ue1.sh
# Continue only after UE1 prints PASS and exits with status 0.
sudo bash connect_ue2.sh
```

`[sudo] password for david:` is a separate prompt for the **laptop's `david`
account**. It grants local permission to configure the modem and networking.
It is independent of the Spark password used for the file transfer. Running
the two commands in the same terminal may reuse sudo's cached authentication;
another terminal or an expired cache can prompt again.

A successful run exits after the ping checks; it does not keep pinging, monitor
later outages or redial automatically. For ongoing monitoring, use the separate
[laptop automatic reconnect Quick Start](dual_ue_laptop_reconnect_quick_start.md).

These are self-checking connection launchers: they perform checks and prepare
the selected UE through successful ping. Without extra options, the terminal
shows the current step, `[OK]` / `[FAIL]` markers, final `PASS`, and the log
directory. Modem details, commands and raw ping output are saved in the log.
Use `--verbose` to also show that full output in the terminal:

```bash
sudo bash ~/falcon-ue-connect/connect_ue1.sh --verbose
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
Evidence saved: /tmp/falcon-ue1-connect-<unique-suffix>
```

The step label appears immediately; its completion marker follows when the
operation finishes. Errors and required manual serial instructions remain
visible in both modes. `--verbose` changes only terminal detail; checks,
connection actions, exit status and full log capture are the same.

If the laptop already has a current Falcon checkout, you can also run from
that checkout's repository root:

```bash
sudo bash scripts/dual_fr1/connect_ue1.sh
sudo bash scripts/dual_fr1/connect_ue2.sh
```

The remaining examples use the copied files under `~/falcon-ue-connect`.

Required laptop packages:

```bash
sudo apt install modemmanager iproute2 iputils-ping python3 minicom
sudo systemctl enable --now ModemManager
```

Complete UE1 first and then UE2. Concurrent launches of the one-shot scripts are
rejected by a shared lock. Existing manual modem/network operations and network
managers are outside that lock; finish those operations before running a script.
You do not need to disconnect a healthy existing PDU. Repeated runs reuse an
already correct bearer and host path, then repeat verification.

## Expected roles

| Item | UE1 / FR1 | UE2 / FR3 |
| --- | --- | --- |
| Modem IMEI | `863305041978437` | `863305041980706` |
| Active SIM IMSI | `001010000000101` | `001010000000102` |
| APN | `internet` | `internet2` |
| UE pool | `10.45.0.0/16` | `10.46.0.0/16` |
| Spark service IP | `10.45.0.1` on `ogstun_1` | `10.46.0.1` on `ogstun_2` |
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

## What each run does

1. Reject execution on a host with either Spark service IP locally assigned.
   Select exactly one modem by the role's IMEI and verify the active SIM IMSI
   and current device identifier. Recheck identity before modem changes and
   host reset.
2. Enable that modem if disabled and wait up to 45 seconds for registration.
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
   Check management and the other UE's IPv4 addresses, rules, main/private
   routes and interface UP/MTU state against the snapshot taken before PDU
   connection.
   Print `PASS` only after all checks succeed.

Management Wi-Fi remains available for SSH and destinations outside these
two Spark service IPs. The independent `20151` / `20152` blocks survive the
existing role reset and shutdown helper. They are runtime rules: a laptop
reboot clears them, and the next successful script preflight installs them
again. This does not change a NetworkManager profile or install a boot service.

## Serving-cell mismatch or unavailable GetCellInfo

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
# Replace the placeholder with this UE's actual USB serial link.
sudo bash ~/falcon-ue-connect/connect_ue1.sh \
  --at-port /dev/serial/by-path/REPLACE_WITH_UE1_AT_PORT

sudo bash ~/falcon-ue-connect/connect_ue2.sh \
  --at-port /dev/serial/by-path/REPLACE_WITH_UE2_AT_PORT
```

The script first tries GetCellInfo. If that proves a matching cell, it does
not open the serial port. A complete mismatching cell is rejected even if
`--at-port` was supplied. The serial fallback checks that the tty and WWAN
belong to the same physical USB device, rejects a busy port, and queries
`AT+CGSN`, `AT+CIMI` and `AT+QENG="servingcell"`. It verifies serial IMEI/IMSI
before accepting a matching NR SA cell. Serial termios settings are restored
when the query ends. No lock, band, mode or CFUN command is sent automatically.
Keep ModemManager running; do not interrupt the other UE to obtain an AT port.

## Recover a dropped or stuck UE PDU

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

## Which IP bindings change, and how MPX follows them

The launcher reads the current bearer allocation and refreshes the WWAN address,
role-table source route and source/destination policy rules. Refresh shell
variables and restart ordinary traffic commands explicitly bound to an old UE IP.
For MPX subnet matching, automatic address tracking, subflow recovery and the
retained experiment evidence, see
[IP changes and MPX in the laptop reconnect guide](dual_ue_laptop_reconnect_quick_start.md#which-ip-bindings-change-and-how-mpx-follows-them).

## Recheck, logs and failure handling

Read-only modem/PDU/host checks, without enable, connect, route changes or ping:

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
outputs and final status. `run.log` retains full printed command/details/ping
output even when `--verbose` is absent. Dependency/root/lock failures occur before a run
directory is allocated. It does not record modem authentication properties.

Exit status is `0` for `connected`, or for `checked` with `--check-only`.
Failure exits `1`, with the failed stage and reason. A serving-cell failure is
marked `serial_check_required`. Foreign policy resources and non-role addresses
are preserved and require manual inspection. If the script's host rebuild
fails midway, it attempts to clear only this role's partial host path while
retaining the independent block; it reports any incomplete cleanup. A failed
PDU attempt or a later cell/ping check can leave the selected modem enabled and
the PDU connected for inspection. Ping failure keeps a fully built path for
diagnosis and does not print a final success. Rerun after resolving the cause.

For normal reset or end-of-experiment shutdown after using these scripts:

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

