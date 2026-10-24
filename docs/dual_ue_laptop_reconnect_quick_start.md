# Dual UE Laptop Automatic Reconnect — Quick Start

Updated: 2026-10-24. Developer: Ruibin.

Run these watchers on the **UE laptop** during an experiment. Each one prepares
its selected UE, verifies connectivity, then keeps monitoring and recovering that
UE until stopped. For a launcher that exits after successful self-check/ping,
use [laptop one-shot startup and self-check](dual_ue_automation.md).

The entry points are [`reconnect_ue1.sh`](../scripts/dual_fr1/reconnect_ue1.sh)
(**UE1 / FR1**) and [`reconnect_ue2.sh`](../scripts/dual_fr1/reconnect_ue2.sh)
(**UE2 / FR3**). They use [`reconnect_ue.py`](../scripts/dual_fr1/reconnect_ue.py),
[`connect_ue.py`](../scripts/dual_fr1/connect_ue.py) and
[`reset_ue_network.py`](../scripts/dual_fr1/reset_ue_network.py): **five files**.

## Before starting

- **Spark:** start the core, CU and both DUs using
  [Spark quick commands](dual_ue_spark_quick_commands.md). Start the Spark video
  demo server separately when needed; these laptop scripts do not start it.
- **Laptop:** attach both modems, keep ModemManager running, and verify the SIMs
  and expected serving-cell settings. The scripts identify modems by IMEI/SIM;
  see [expected roles](dual_ue_automation.md#expected-roles) for the full values.
- A matching cell skips serial configuration. Missing registration/cell evidence
  or a mismatch fails that attempt; manually correct serial settings if needed.
  The watcher does not send cell-lock, band, mode or CFUN configuration commands.

Required laptop packages, if not already installed:

```bash
sudo apt install modemmanager iproute2 iputils-ping python3 minicom
sudo systemctl enable --now ModemManager
```

| Role | APN / UE pool | Spark service | Video preference |
| --- | --- | --- | --- |
| UE1 / FR1 | `internet` / `10.45.0.0/16` | `10.45.0.1` on `ogstun_1` | Backup |
| UE2 / FR3 | `internet2` / `10.46.0.0/16` | `10.46.0.1` on `ogstun_2` | Primary |

FR1/FR3 are demo labels; both current radios use n78. The `.1` service addresses
stay on Spark. Current UE IPs, interface names and modem indices are discovered
automatically on the laptop.

## Copy or update the five files

Run in **Bash on the laptop**. Stop active watchers before updating the shared
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

## Start the watchers

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

## Retry and health-check interval

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

## Output levels

| Watcher option | Terminal output |
| --- | --- |
| `--verbose 1` (default) | Attempt number and `SUCCESS` / `FAIL` only. |
| `--verbose 2` | Each attempt's step labels, `[OK]` / `[FAIL]`, result, actionable error and evidence directory. |
| `--verbose 3` | Level 2 plus executed query/change commands, validated identity/cell/bearer details, command output and raw ping results; healthy checks are shown too. |

All three levels save the same detailed `run.log`; raw bearer authentication
properties are not dumped. Healthy monitoring is silent at levels 1 and 2.
**Silent means no terminal output: the status checks, ping traffic and file logging
still happen.** It does not mean passive monitoring without network traffic.
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

## Stop or switch to manual operations

Run only **one watcher per role**; duplicate watchers are rejected. UE1 and UE2
watchers can run together: a shared lock serializes each check/recovery with the
other role and with the one-shot connection scripts. The lock is released during
the retry wait, and waiting for it does not count as a connection attempt.
Stop the affected watcher with **Ctrl+C before manual modem configuration, reset,
shutdown or a one-shot run for that role**, otherwise it will try to reconnect
a deliberately stopped path. Ctrl+C/SIGTERM requests a stop after the current
transaction; interval waits wake immediately. Stopping a watcher leaves the
modem, PDU and host network configuration in place. It does not disconnect traffic.
No service, boot job or background daemon is installed automatically.

## Automatic recovery

Recovery proceeds as follows:

1. Rediscover the modem/SIM and current serving cell. Missing registration or
   unproved/mismatching cells fail that attempt and continue polling. Level 2/3
   explains the required manual checks. No cell lock, band, mode or CFUN write is
   sent; correct the serial settings manually if needed. A wrong cell never
   triggers PDU dial/disconnect or host rebuild.
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

## Optional parameters

`--at-port` uses the same owned-port, read-only serving-cell fallback described in
[the one-shot guide](dual_ue_automation.md#serving-cell-mismatch-or-unavailable-getcellinfo).
Use the option on a watcher as follows, replacing the serial link with this UE's
verified AT port:

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --verbose 2 \
  --at-port /dev/serial/by-path/REPLACE_WITH_UE2_AT_PORT
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

## Logs and exit status

Evidence goes into a private `/tmp/falcon-ueN-reconnect-<unique-suffix>` directory,
or under `--output-root /existing/directory`. Level 1 omits the directory from the
terminal; locate it in a second terminal with:

```bash
sudo ls -td /tmp/falcon-ue1-reconnect-* /tmp/falcon-ue2-reconnect-*
```

`run.log` retains detailed attempts and health checks; `attempts.jsonl` records
each attempt's UTC times, outcome, failed stage, current IP, ping output and
forced-redial reason when applicable. `summary.json` is written on exit and
records the last verified state (not a new post-exit measurement). Logs accumulate
for the invocation; retain the evidence you need and remove old run directories
after stopping the watcher. Signal exit codes are 130 (Ctrl+C) / 143 (SIGTERM).

These watchers repair the PDU and laptop network. A running MPX client then follows
host IP changes as described [below](#which-ip-bindings-change-and-how-mpx-follows-them).
They do not start MPX or restart applications bound explicitly to an old IP.
Offline simulated checks pass; **physical obstruction/recovery and MPTCP traffic
acceptance with these new watchers remain pending**.

## Video during monitoring and recovery

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

## Which IP bindings change, and how MPX follows them

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
