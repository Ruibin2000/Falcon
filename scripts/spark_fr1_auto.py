#!/usr/bin/env python3
"""Run the FR1 testbed in one Spark terminal: CU, DU1/UE1, FlexRIC and xApp."""

import sys

from spark_auto import Fault, main


if __name__ == "__main__":
    try:
        sys.exit(main([*sys.argv[1:], "--du1-only"]))
    except (Fault, OSError, ValueError) as error:
        print("FAIL:", error, file=sys.stderr)
        sys.exit(1)
