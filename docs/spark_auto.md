# Spark Auto Quick Start

Run the testbed from **one Spark terminal**. No tmux or extra terminal windows.
The controller manages RIC, CU, DU1, DU2, xApp and the ten Open5GS services.
Docker, MongoDB and the external MPTCP server stay running when it stops.

For **DU1/UE1 only**, use the [Spark FR1 auto guide](operations/spark_fr1_auto.md)
and `scripts/spark_fr1_auto.py`. That profile uses two E2 subscriptions and
routes gain commands to DU1; this guide describes the default dual profile.

For **DU2/UE2 only over direct n78 wired / 20 MHz**, use
[`scripts/spark_wired_du2_auto.py`](../scripts/spark_wired_du2_auto.py) and the
[wired DU2 quick start](spark_wired_du2_quick_start.md). It uses the same controller,
with two E2 subscriptions, DU2 gain control and the dedicated wired20 DU YAML.

## 1. Prepare once

Complete the [manual build/configuration preparation](spark_quick_commands.md#1a-prepare-the-cu-identity-binary-and-isolated-flexric-plugin)
and [post-reboot performance setup](spark_quick_commands.md#2-restore-performance-settings-after-reboot).
Docker and the existing `open5gs-mongo` container/subscriber profiles must be
available. Stop manually launched RIC/CU/DUs/xApp before using auto mode.

The controller reads the deployed OCUDU YAML and snapshots it for this run:
**DU1 3660 MHz / 20 MHz / TX 70 / RX 25**, **DU2 40 MHz / TX 60 / RX 35**.
It never rewrites those source files or retunes DU1.
Gain checks and the `--check` summary read the deployed YAML. The controller
does not require an older fixed gain pair, so operator tuning in those files
is used on the next start. Record the actual values for each run.

**TDD profile, updated 2026-11-02:** both DUs explicitly use **DDDSUUUUUU**
(3 full DL slots, 1 special slot with 8 DL symbols and no UL symbols,
6 full UL slots). At 30 kHz SCS the 10-slot period is 5 ms, giving 60% UL
airtime instead of the previous 30%. Both the maintained Falcon templates and
deployed `/home/nyu/ocudu/configs/` files carry this setting. Auto mode copies
the complete deployed YAML into each run, including `cell_cfg.tdd_ul_dl_cfg`.
Stop an existing controller normally and start it again to load this profile;
then reconnect the Laptop UEs. Both DU profiles pass OCUDU `--dryrun`; live
connectivity and throughput with the new pattern still need verification.

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

For the optional validated GPU candidate, follow [CUDA uplink PUSCH/LDPC](operations/cuda_ldpc.md),
then use `--check --cuda` and start with `--cuda`. This selects CUDA uplink
for both DUs; startup without that flag continues to use the existing CPU DUs.

Startup confirmations stay within their component's stage: CU waits for E2
registration; each DU waits for E2 registration and F1 setup confirmed by both
CU and DU; xApp waits for E42 registration, the broker listener and all three
KPM subscriptions. Confirmation updates are printed before `[READY]` and the
next `[START]`. Missing confirmations time out and trigger cleanup.
While waiting, `[WAIT]` prints the missing confirmation every five seconds.
The controller automatically prints the complete status summary once, then
prints `[RUNNING]` and the command prompt. Later events still appear live.

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
rx_gain 0 35
```

Connection requests, successful E2/F1/E42 setup, observed disconnections and
component exits appear as updates, for example:

```text
[ric] E2_REGISTERED node=DU2 gnb_id=411 du_id=2 evidence=e2_setup_success
[cu] F1_DU_REGISTERED node=DU2 du_id=2 evidence=f1_setup_response_tx
[ric] E42_REGISTERED node=xApp xapp_id=7 evidence=e42_setup_response_rx
[xapp] KPM_SUBSCRIPTIONS_READY subscribed_e2_nodes=3 subscriptions=3
[du2] DOWN exit_code=1; stopping managed testbed
```

`status` shows the managed components and current observed counts. Example
with all registrations complete and one MPTCP application:

```text
[STATUS] phase=running health=ok
[ric] process=running E2 nodes registered=3/3 (CU=registered DU1=registered DU2=registered); xApp=registered id=7
[cu] process=running RIC=registered; DUs registered=2/2 (DU1=registered DU2=registered)
[du1] process=running RIC=registered CU=registered uplink=cpu
[du2] process=running RIC=registered CU=registered uplink=cpu
[xapp] process=running RIC=registered; E2 nodes subscribed=3; KPM subscriptions=3; broker=ready apps registered=1
```

Registration requires protocol success evidence; otherwise it shows `waiting`.
CU/DU updates follow the live E2/F1 info logs (keep the deployed
`all_level: info`). Auto mode selects OCUDU's `stdout` log sink, which flushes
each entry, and archives it in `NAME.console.log`. This avoids waiting for a
buffered log file to fill while CU is idle before DU startup.
xApp's node count comes from successful KPM subscriptions,
one per node; broker counts follow app registration/unregistration/disconnection.
The same details are saved in `status.json`. Pi-Radio power and the UE radio
link require their own checks. Restart the controller normally to load updates
to this script; running controllers keep their loaded version.

Gain commands go **only to DU2**, through its virtual terminal. Native gain
acknowledgements appear in the controller. Full output, including native CU/DU
logs, stays in each `NAME.console.log`; final `publisher.json` is also local.

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
