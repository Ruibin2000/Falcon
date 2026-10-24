#!/usr/bin/env python3
"""Read gain acknowledgement times from a DU console transcript and timing file."""

import argparse
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys


def gain_events(transcript, timing):
    """Reconstruct output observation times, anchored to the launcher's UTC marker.

    This measures receipt of the successful console reply, not RF settling.
    Only output records are accepted; input logging is deliberately unnecessary.
    """
    # Snapshot timing first: its complete records should have corresponding
    # bytes by the time the flushed output transcript is read.
    timing_data = Path(timing).read_bytes()
    transcript_data = Path(transcript).read_bytes()
    header_end = transcript_data.find(b"\n")
    if header_end < 0 or b"[COMMAND=" not in transcript_data[:header_end]:
        raise ValueError("Unrecognized script transcript header")
    data = transcript_data[header_end + 1:]
    elapsed = Decimal(0)
    offset = 0
    ends, times = [], []
    lines = timing_data.splitlines(keepends=True)
    for raw in lines:
        if not raw.endswith(b"\n"):
            break  # A live timing file can end in a partial record.
        fields = raw.split(maxsplit=2)
        if len(fields) != 3:
            raise ValueError("Expected advanced script timing records")
        kind, delay, value = fields
        if kind not in (b"H", b"O", b"S"):
            raise ValueError("Expected output-only timing; input records are not supported")
        try:
            delta = Decimal(delay.decode("ascii"))
            if not delta.is_finite() or delta < 0:
                raise ValueError("Invalid timing delay")
            elapsed += delta
            if kind == b"O":
                count = int(value)
                if count < 0:
                    raise ValueError("Invalid output byte count")
                if offset + count > len(data):
                    raise ValueError("Console transcript is shorter than its timing records")
                offset += count
                ends.append(offset)
                times.append(elapsed)
        except (InvalidOperation, UnicodeError) as error:
            raise ValueError("Invalid timing record") from error
    data = data[:offset]  # Exclude the footer and not-yet-timed live output.
    marker = re.search(rb"FALCON_CONSOLE_CLOCK (\d{4}-\d\d-\d\dT[^\s]+Z)", data)
    if marker is None:
        raise ValueError("No UTC clock marker; restart the DU with the updated console launcher")
    anchor = datetime.fromisoformat(marker.group(1).decode("ascii").replace("Z", "+00:00"))
    anchor_elapsed = times[bisect_left(ends, marker.end())]
    events = []
    for match in re.finditer(rb"\b(Tx|Rx) gain set to ([-+0-9.eE]+) dB for port (\d+)\.", data):
        observed = times[bisect_left(ends, match.end())]
        when = anchor + timedelta(microseconds=int((observed - anchor_elapsed) * 1000000))
        events.append(dict(time_utc=when.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                           direction=match.group(1).decode("ascii").lower(),
                           port=int(match.group(3)), gain_db=float(match.group(2)),
                           event="gain_acknowledged", timestamp_basis="console_output_observed",
                           console_log=str(Path(transcript).resolve())))
    return events


def latest_console(du):
    runs = [p / "startup.log" for p in Path("/tmp").glob(f"falcon-du{du}-*")
            if (p / "startup.log").is_file()]
    if not runs:
        raise ValueError(f"No DU{du} startup.log found under /tmp")
    # Select the latest console first, then require its timing file. Never
    # silently substitute an older timed run for a newer uninstrumented run.
    return max(runs, key=lambda p: p.stat().st_mtime_ns)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("startup_log", nargs="?", help="Console transcript from run_du_console.sh")
    parser.add_argument("--du", type=int, choices=(1, 2), help="Select the latest DU1/DU2 console under /tmp")
    parser.add_argument("--json", action="store_true", help="Print JSON lines for analysis/archival")
    args = parser.parse_args(argv)
    if bool(args.startup_log) == (args.du is not None):
        parser.error("Supply a startup_log path or --du 1/2")
    try:
        transcript = Path(args.startup_log) if args.startup_log else latest_console(args.du)
        timing = Path(str(transcript) + ".timing")
        if not timing.is_file():
            raise ValueError(f"Timing file missing: {timing}; use the updated launcher on the next DU start")
        events = gain_events(transcript, timing)
        for event in events:
            if args.json:
                print(json.dumps(event))
            else:
                print(f"{event['time_utc']}  {event['direction']}_gain {event['port']} {event['gain_db']:g}  acknowledged")
        if not events:
            print("No successful gain replies recorded in this run yet", file=sys.stderr)
        return 0
    except (ValueError, OSError) as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
