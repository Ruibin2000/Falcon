#!/usr/bin/env python3
"""UE2 wired20 watcher; verify/restore the wired cell lock before registration.

Manual Laptop command used with Spark TX 70 / RX 35:
    sudo bash ~/falcon-ue2-wired20/reconnect_ue2_wired20.sh \
        --auto-cell-lock --interval 3 --verbose 3 --registration-timeout 30

These wired defaults precede user arguments so explicit CLI values still win.
See docs/laptop_wired_ue2_quick_start.md for source-bound UL traffic commands.
"""

import sys

import connect_ue as connect
import reconnect_ue as reconnect


UE2_AT_PORT = "/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    # Keep the shared modem/SIM, host-network and USB ownership safeguards.
    # Only this entry point selects the SSB derived for the 20-MHz wired cell.
    original_role = connect.ROLES[2]
    connect.ROLES[2] = dict(original_role, ssb=639648, label="n78-wired20")
    try:
        if "--help" in argv or "-h" in argv:
            print("Wired UE2 defaults override the shared defaults shown below: "
                  "--auto-cell-lock --interval 3 --verbose 3 --registration-timeout 30.", flush=True)
        else:
            print("UE2 wired20: startup cell-lock verification/restoration is on; "
                  "PCI 2 / SSB 639648 / SCS 30 kHz / n78; "
                  "require matching QNWLOCK readback before registration and PDU setup.", flush=True)
        # Use the same guarded startup/recovery path as the other UE watchers.
        # A matching saved lock is reused; failed writes/readbacks cannot pass
        # startup preparation. The shared engine preserves identity/PDU guards
        # and restores CFUN=1 after any permitted minimum-functionality retry.
        return reconnect.main([
            "--at-port", UE2_AT_PORT, "--auto-cell-lock",
            "--interval", "3", "--verbose", "3", "--registration-timeout", "30",
            *argv, "--ue", "2",
        ])
    finally:
        connect.ROLES[2] = original_role


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(f"STOP: {error}", file=sys.stderr)
        sys.exit(1)
