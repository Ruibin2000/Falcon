#!/usr/bin/env python3
"""Run direct n78 wired20 DU2/UE2 using the shared Spark auto controller.

From /home/nyu/Desktop/Falcon_repo/Falcon, run manually:
    python3 -B scripts/spark_wired_du2_auto.py --check
    sudo python3 -B scripts/spark_wired_du2_auto.py

The wired YAML selects TX 70 / RX 35, 20 MHz and 100-ms DU metrics. Wait for
[RUNNING], then start the Laptop wired UE2 watcher. The controller accepts
status, tx_gain 0 VALUE, rx_gain 0 VALUE and stop; native DU command t is not
forwarded. See docs/spark_wired_du2_quick_start.md for the iperf/log commands.
"""

import sys

from spark_auto import Fault, main


if __name__ == "__main__":
    try:
        sys.exit(main([*sys.argv[1:], "--du2-wired20-only"]))
    except (Fault, OSError, ValueError) as error:
        print("FAIL:", error, file=sys.stderr)
        sys.exit(1)
