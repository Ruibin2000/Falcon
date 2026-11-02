# Spark Auto Quick Start

Run the testbed from **one Spark terminal**. No tmux or extra terminal windows.
The controller manages RIC, CU, DU1, DU2, xApp and the ten Open5GS services.
Docker, MongoDB and the external MPTCP server stay running when it stops.

## 1. Prepare once

Complete the [manual build/configuration preparation](spark_quick_commands.md#1a-prepare-the-cu-identity-binary-and-isolated-flexric-plugin)
and [post-reboot performance setup](spark_quick_commands.md#2-restore-performance-settings-after-reboot).
Docker and the existing `open5gs-mongo` container/subscriber profiles must be
available. Stop manually launched RIC/CU/DUs/xApp before using auto mode.

The controller reads the deployed OCUDU YAML and snapshots it for this run:
**DU1 3660 MHz / 20 MHz / TX 70 / RX 35**, **DU2 40 MHz / TX 60 / RX 10**.
It never rewrites those source files or retunes DU1.

## 2. Check and start

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
python3 -B scripts/spark_auto.py --check
sudo python3 -B scripts/spark_auto.py
```

`--check` only reads files/configuration. Normal startup builds a private
collector/plugin, then checks/starts **MongoDB → 5GC → RIC → CU → DU1 → DU2
→ xApp**. Each stage must pass before the next starts. Keep the printed
`/tmp/falcon-spark-auto-*` directory for logs and `status.json`.

At `[RUNNING]`, keep the Laptop UE watchers active and start/reconnect the formal
MPTCP server. xApp listens on `127.0.0.1:8765`, protocol **2**, profile
**`du27_bound_v1`**. Registration events appear in the controller; verify actual
KPM reception in the MPTCP application. No UE data or MPTCP registration yet
is a waiting state, not a component failure. Traffic remains with MPTCP.

Example registration output (application/request IDs come from MPTCP):

```text
[xapp] APP_REGISTER_RECEIVED app=mptcp-server request=reg-1
[xapp] APP_REGISTERED app=mptcp-server request=reg-1 subscription=sub-1 acknowledgement=queued
```

Registration rejection, unregistration and disconnection also appear here.

## 3. Operate in that terminal

Enter one controller command per line:

```text
status
tx_gain 0 60
rx_gain 0 10
```

Gain commands go **only to DU2**, through its virtual terminal. Native gain
acknowledgements appear in the controller. Full output stays in each
`NAME.console.log`; native CU/DU logs and final `publisher.json` are also local.

## 4. Stop everything managed by this run

Press **Ctrl+C**, or enter:

```text
stop
```

The controller stops **xApp → DU2 → DU1 → CU → RIC → 5GC**. It first allows
normal E2 deletion; hung processes have bounded TERM/KILL fallback. Docker and
MongoDB remain running. Any unexpected component exit/startup timeout triggers
the same cleanup. Infrastructure probes run every 5 seconds; three consecutive
failed probes also trigger cleanup. Missing UE traffic or an absent MPTCP client
does not trigger it. Forced or incomplete cleanup returns failure visibly.

From another terminal, substitute the printed directory:

```bash
sudo python3 -B scripts/spark_auto.py --status /tmp/falcon-spark-auto-XXXXXXXX
sudo python3 -B scripts/spark_auto.py --stop /tmp/falcon-spark-auto-XXXXXXXX
```

Detailed captures stay local under the [archive policy](experiments/README.md#local-archive-policy).
Offline process/PTY regression tests cover the controller; full hardware
cold-start, gain control and shutdown acceptance still require a live run.
