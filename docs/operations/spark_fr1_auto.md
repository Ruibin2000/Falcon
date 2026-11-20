# Spark FR1 Auto Quick Start

Run **CU + DU1 + UE1** using the shared Spark controller. This profile starts
FlexRIC and the continuous xApp, with no DU2, UE2 or Pi-Radio requirement.
UE1 still runs on the Laptop.

## Check and start

Stop an existing manual or automatic RAN run first. Complete the same
[build and host preparation](../spark_auto.md#1-prepare-once) used by dual mode.
The existing `open5gs-mongo` container and UE1 subscriber must be available.

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
python3 -B scripts/spark_fr1_auto.py --check
sudo python3 -B scripts/spark_fr1_auto.py
```

Startup order: **Database → 5GC → FlexRIC → CU → DU1 → xApp**.
The shared ten-service 5GC is retained; subscriber checks select UE1
`001010000000101` / DNN `internet`, and route checks select `ogstun_1` /
`10.45.0.0/16`. DU2 files, its radio and its subscriber are not required.

The controller reads `/home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml`, including
the current gains and TDD pattern, and snapshots it in
`/tmp/falcon-spark-fr1-auto-*`. The FR1 profile is 3660 MHz, 20 MHz,
23.04 MS/s, PCI 1 and B210 serial `3271233`, with the operator-confirmed
TX 70 / RX 25 dB settings. The current TDD pattern is
`DDDSUUUUUU`: six UL slots per 5-ms period. `--check` prints the actual gains.

For a radio comparison, select a complete DU1 YAML with `--du1-config` in
both the check and start commands:

```bash
python3 -B scripts/spark_fr1_auto.py --du1-config /path/to/du1.yml --check
sudo python3 -B scripts/spark_fr1_auto.py --du1-config /path/to/du1.yml
```

The selected file receives the usual validation and is copied to the run's
`du1.yml`; its source path and hash are recorded in `manifest.json`. Match
the Laptop cell lock to the actual DU startup output for that configuration.

### Optional CUDA candidate

For the separately validated CUDA candidate, append `--cuda` to both commands.
CPU remains the default; see the [CUDA validation scope](cuda_ldpc.md).

## Connect UE1 and MPTCP

On the Laptop, start only the UE1 watcher:

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --interval 3 --verbose 2
```

At Spark's `[RUNNING]`, the xApp waits for the formal MPTCP application's
registration on `127.0.0.1:8765`, protocol 2 / profile `du27_bound_v1`.
The identity configuration selects DU1 and DNN `internet`; DU KPM retains the
100-ms subscription period. No dummy application is needed.

## Status, gains and stop

Enter `status` in the Spark controller terminal. Expect **2/2 E2 nodes**
(CU, DU1), **1/1 DU** on CU, **2 KPM subscriptions**, and the current broker
application count. Gain commands `tx_gain 0 VALUE` and `rx_gain 0 VALUE`
control **DU1 only** in this profile.

Enter `stop` or press **Ctrl+C** to stop **xApp → DU1 → CU → FlexRIC → 5GC**.
Any managed component failure triggers the same cleanup. xApp shutdown
requires two E2 delete responses. Docker/MongoDB and the external MPTCP
process are preserved. Stop the Laptop UE1 watcher separately with Ctrl+C.

From another Spark terminal, substitute the printed directory:

```bash
sudo python3 -B scripts/spark_fr1_auto.py --status /tmp/falcon-spark-fr1-auto-XXXXXXXX
sudo python3 -B scripts/spark_fr1_auto.py --stop /tmp/falcon-spark-fr1-auto-XXXXXXXX
```

Dual and FR1 controllers share the same lock and cannot run together. Logs
and `status.json` remain local. Offline process/PTY tests cover both modes;
live FR1 radio, UE/PDU and MPTCP reception acceptance still requires a run.
