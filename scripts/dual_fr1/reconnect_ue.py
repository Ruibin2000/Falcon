#!/usr/bin/env python3
"""Watch one laptop UE and recover its PDU/host path until stopped (Ctrl+C)."""

import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import ipaddress
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

import connect_ue as connect


ERRORS = (ValueError, OSError, subprocess.SubprocessError)
SHARED_LOCK = "/run/lock/falcon-ue-connect.lock"


def now():
    return datetime.now(timezone.utc).isoformat()


class LevelTee(connect.Tee):
    """Always save details; expose only the chosen level to the terminal."""
    def __init__(self, terminal, log, level):
        super().__init__(terminal, log, verbose=level == 3)
        self.level = level

    def show(self, value, detail=None):
        self.log.write(value if detail is None else detail)
        if self.level >= 2:
            self.terminal.write(detail if self.verbose and detail is not None else value)
        self.flush()


@contextlib.contextmanager
def capture(log, level):
    original_read, original_reset_read = connect.read, connect.reset.read

    def read(*command):
        # Query commands are useful evidence. Do not dump raw bearer properties,
        # which may contain authentication fields; Connection prints validated data.
        print("$ " + shlex.join(command), flush=True)
        return original_read(*command)

    with contextlib.redirect_stdout(LevelTee(sys.stdout, log, level)), \
            contextlib.redirect_stderr(LevelTee(sys.stderr, log, level)), \
            connect.capture_reset_output():
        connect.read = connect.reset.read = read
        try:
            yield
        finally:
            connect.read, connect.reset.read = original_read, original_reset_read


@contextlib.contextmanager
def shared_lock():
    """Do not hold the host-wide mutation lock while waiting between checks."""
    with open(SHARED_LOCK, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


class Recovery(connect.Connection):
    def __init__(self, *args, redial=False, redial_allowed=True, failed_bearer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.redial_requested = redial
        self.redial_allowed = redial_allowed
        self.failed_bearer = failed_bearer
        self.redial_started_at = None

    def active(self):
        info = self.checked_modem()
        active = []
        for path in connect.reset.bearer_paths(info):
            details = connect.kv("mmcli", "-b", path, "-K")
            if details.get("bearer.status.connected") == "yes":
                active.append((path, details))
        connect.require(len(active) <= 1, "Multiple connected bearers; refusing automatic disconnect")
        if active:
            connect.require(active[0][1].get("bearer.properties.apn") == self.role["apn"],
                            "Foreign APN; refusing automatic disconnect")
        return info, active

    def bearer(self, connect=False):
        if connect:
            self.recover_stuck()
        return super().bearer(connect=connect)

    @staticmethod
    def allocation(active):
        # Bearer counters/duration may tick while reading. Compare ownership and
        # allocation only; live traffic statistics are not an allocation change.
        keys = ("bearer.properties.apn", "bearer.status.connected", "bearer.status.suspended",
                "bearer.status.interface", "bearer.ipv4-config.method", "bearer.ipv4-config.address",
                "bearer.ipv4-config.prefix", "bearer.ipv4-config.mtu")
        return [(path, tuple(details.get(key) for key in keys)) for path, details in active]

    def recover_stuck(self):
        info, active = self.active()
        if not active:
            return
        path, details = active[0]
        suspended = details.get("bearer.status.suspended") == "yes"
        same_failed = self.failed_bearer == (path, details.get("bearer.ipv4-config.address"))
        if not (suspended or (self.redial_requested and same_failed)) or not self.redial_allowed:
            return
        # Refuse destructive recovery for foreign/malformed resources, just as
        # the one-shot launcher does. A suspended *valid* static bearer is allowed.
        connect.require(details.get("bearer.ipv4-config.method") == "static", "Non-static bearer; inspect its owner")
        source = ipaddress.IPv4Address(details.get("bearer.ipv4-config.address", ""))
        connect.require(source in ipaddress.IPv4Network(self.role["pool"])
                        and str(source) != self.role["server"], "Bearer IP is outside the role pool")
        ipaddress.IPv4Interface(f"{source}/{int(details.get('bearer.ipv4-config.prefix', '-1'))}")
        connect.require(576 <= int(details.get("bearer.ipv4-config.mtu", "0")) <= 65535,
                        "Invalid bearer MTU; refusing automatic disconnect")
        interface = details.get("bearer.status.interface", "")
        connect.require(connect.ports(info) == {interface} and connect.reset.WWAN.fullmatch(interface),
                        "Expected one dedicated, owned WWAN for automatic disconnect")
        self.host_preflight(dict(interface=interface))
        before = self.surroundings(dict(interface=interface))
        self.serving_cell()
        _, current = self.active()
        connect.require(self.allocation(current) == self.allocation(active),
                        "Bearer changed before disconnect; retry discovery")
        self.block(install=False)
        connect.status("Recover stuck PDU: disconnect selected UE, clear its host path, then redial")
        # Track failed disconnects too, so a rejected request cannot be hammered.
        self.redial_started_at = time.monotonic()
        self.result.update(redial=True, previous_source=str(source), previous_bearer=path,
                           redial_reason="suspended" if suspended else "consecutive ping failures")
        connect.change("mmcli", "-m", self.modem, "--simple-disconnect")
        _, remaining = self.active()
        connect.require(not remaining, "Bearer still connected after disconnect; stopping this attempt")
        self.checked_modem()
        connect.reset.reset(self.ue)
        self.block(install=False)
        connect.require(self.surroundings(dict(interface=interface)) == before,
                        "Other UE/management state changed during disconnect")
        self.redial_requested = False


def probe(session):
    """Read current state and send two single pings; no modem/network mutations."""
    session.discover()
    session.serving_cell()
    bearer = session.bearer()
    session.host_preflight(bearer)
    connect.require(session.configured(bearer), "Host path is incomplete or the bearer IP changed")
    for bound in (True, False):
        session.routes(bearer)
        command = ["ping", "-n", "-c", "1", "-W", "2", "-w", "3"]
        if bound:
            command.extend(["-I", bearer["source"]])
        try:
            print(connect.read(*command, session.role["server"]), end="")
        except subprocess.CalledProcessError as error:
            print(error.output or "Ping command failed without stdout", file=sys.stderr)
            if error.stderr:
                print(error.stderr, file=sys.stderr)
            raise
    connect.require(session.bearer() == bearer, "PDU changed during health check")
    connect.require(session.configured(bearer), "Host path changed during health check")
    session.routes(bearer)
    return bearer


class Watcher:
    def __init__(self, args, directory, log, stop=None):
        self.args, self.directory, self.log = args, Path(directory), log
        self.stop = stop if stop is not None else threading.Event()
        self.terminal = sys.stdout
        self.attempts = self.ping_failures = 0
        self.last_redial = None
        self.failed_bearer = None
        self.healthy = False
        self.started_at = now()
        self.exit_signal = None

    def session(self, recovery=False):
        kwargs = dict(at_port=self.args.at_port, registration_timeout=self.args.registration_timeout,
                      ping_count=1)
        if recovery:
            allowed = self.last_redial is None or time.monotonic() - self.last_redial >= self.args.redial_cooldown
            return Recovery(self.args.ue, redial=self.ping_failures >= self.args.redial_after,
                            redial_allowed=allowed, failed_bearer=self.failed_bearer, **kwargs)
        return connect.Connection(self.args.ue, **kwargs)

    def say(self, message):
        self.log.write(message + "\n")
        self.log.flush()
        if self.args.verbose >= 2:
            print(message, file=self.terminal, flush=True)

    def attempt(self):
        self.attempts += 1
        prefix = f"UE{self.args.ue} / {connect.ROLES[self.args.ue]['label']} attempt {self.attempts}"
        print(prefix + " ...", end=" " if self.args.verbose == 1 else "\n", file=self.terminal, flush=True)
        session = self.session(recovery=True)
        with capture(self.log, self.args.verbose):
            print(f"\n{now()} {prefix}", flush=True)
            try:
                session.run()
                self.healthy = True
                self.ping_failures = 0
                self.failed_bearer = None
            except KeyboardInterrupt as error:
                self.healthy = False
                signum, reason = connect.interruption(error)
                session.result.update(status="interrupted", stage=session.stage, error=reason, signal=signum)
                line = "CANCELLED" if self.args.verbose == 1 else f"{prefix}: CANCELLED"
                print(line, file=self.terminal, flush=True)
                self.log.write(f"{prefix}: CANCELLED ({reason})\n")
                raise
            except ERRORS as error:
                self.healthy = False
                ping_error = (session.stage == "ping" and isinstance(error, subprocess.SubprocessError)
                              and getattr(error, "cmd", [None])[0] == "ping")
                self.ping_failures = self.ping_failures + 1 if ping_error else 0
                self.failed_bearer = ((session.result.get("bearer"), session.result.get("source"))
                                      if ping_error else None)
                session.result.update(status="serial_check_required" if isinstance(error, connect.CellError) else "failed",
                                      stage=session.stage, error=str(error))
                connect.status(f"STOP at {session.stage}: {error}", error=True)
                if isinstance(error, subprocess.CalledProcessError) and error.stderr:
                    print(error.stderr, file=sys.stderr)
                if isinstance(error, connect.CellError):
                    session.manual_hint()
            finally:
                if session.redial_started_at is not None:
                    self.last_redial = session.redial_started_at
                session.result.update(attempt=self.attempts, ended_at=now())
                with (self.directory / "attempts.jsonl").open("a") as records:
                    records.write(json.dumps(session.result) + "\n")
        result = "SUCCESS" if self.healthy else "FAIL"
        print(result if self.args.verbose == 1 else f"{prefix}: {result}", file=self.terminal, flush=True)
        self.log.write(f"{prefix}: {result}\n")
        self.log.flush()

    def run(self):
        waiting = False
        try:
            self.say(f"Watching UE{self.args.ue}; interval={self.args.interval:g}s, evidence={self.directory}; Ctrl+C to shut down this UE")
            while not self.stop.is_set():
                with shared_lock() as acquired:
                    if not acquired:
                        if not waiting:
                            self.say("Waiting for another UE operation to release the shared network lock")
                        waiting = True
                    else:
                        waiting = False
                        if self.healthy:
                            with capture(self.log, 3 if self.args.verbose == 3 else 1):
                                try:
                                    probe(self.session())
                                except ERRORS as error:
                                    self.healthy = False
                                    print(f"{now()} Health check failed: {error}", flush=True)
                            if not self.healthy:
                                self.say("Link check failed; starting recovery")
                        if not self.healthy and not self.stop.is_set():
                            self.attempt()
                            if self.stop.is_set():
                                break
                            if self.args.once and self.healthy:
                                return 0
                            if self.args.max_attempts and self.attempts >= self.args.max_attempts:
                                return 0 if self.healthy else 1
                # No overlap: a slow command/registration is never interrupted to
                # create another attempt, and the other UE may work during this wait.
                self.stop.wait(self.args.interval)
            return 128 + self.exit_signal if self.exit_signal else 0
        except KeyboardInterrupt as error:
            self.exit_signal, reason = connect.interruption(error)
            self.stop.set()
            self.say(reason)
            return 128 + self.exit_signal
        finally:
            verified_before_stop = self.healthy
            shutdown = None
            if self.exit_signal is not None:
                with capture(self.log, self.args.verbose):
                    shutdown = connect.shutdown_on_interrupt(self.args.ue, lock_path=SHARED_LOCK)
                self.healthy = False
                outcome = "SUCCESS" if shutdown["status"] == "completed" else "FAIL"
                message = f"UE{self.args.ue} shutdown: {outcome}"
                # A stop result must remain visible even at minimal verbosity.
                print(message, file=self.terminal, flush=True)
                self.log.write(message + "\n")
                if shutdown["status"] != "completed":
                    print("Cleanup incomplete: " + shutdown["error"], file=self.terminal, flush=True)
            summary = dict(ue=self.args.ue, path=connect.ROLES[self.args.ue]["label"],
                           started_at=self.started_at, ended_at=now(), attempts=self.attempts,
                           last_connection_verified=verified_before_stop, interval_seconds=self.args.interval,
                           verbose=self.args.verbose, signal=self.exit_signal, shutdown=shutdown,
                           note="SIGINT/SIGTERM runs selected-role shutdown; normal --once success leaves the UE connected")
            (self.directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            self.say(f"Stopped; evidence saved: {self.directory}")


def positive_seconds(value):
    try:
        value = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a positive number of seconds") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("expected a finite number greater than zero")
    return value


def positive_int(value):
    try:
        value = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a positive integer") from None
    if value < 1:
        raise argparse.ArgumentTypeError("expected an integer greater than zero")
    return value


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ue", required=True, type=int, choices=(1, 2))
    parser.add_argument("--interval", type=positive_seconds, default=1.0,
                        help="Seconds AFTER each check/attempt before the next, default 1; no overlapping attempts")
    parser.add_argument("--verbose", type=int, choices=(1, 2, 3), default=1,
                        help="1: attempt number/result only (default); 2: steps; 3: full command/details/ping output")
    parser.add_argument("--at-port", help="Owned USB serial port for read-only serving-cell fallback")
    parser.add_argument("--registration-timeout", type=positive_int, default=5,
                        help="Registration wait per attempt, 1..300 seconds (default 5)")
    parser.add_argument("--redial-after", type=positive_int, default=3,
                        help="Redial on the next attempt after this many consecutive failed ping attempts, default 3")
    parser.add_argument("--redial-cooldown", type=positive_seconds, default=30.0,
                        help="Minimum seconds between forced disconnect requests, default 30; also applies to suspended PDU")
    parser.add_argument("--once", action="store_true", help="Retry until first success, then exit instead of watching")
    parser.add_argument("--max-attempts", type=positive_int, help="Stop after this many total connection attempts")
    parser.add_argument("--output-root", default="/tmp", help="Existing parent for private logs, attempts.jsonl and summary.json")
    args = parser.parse_args(argv)
    if args.registration_timeout > 300:
        parser.error("--registration-timeout must be in 1..300")
    return args


def main(argv=None):
    args = arguments(argv)
    connect.require(os.geteuid() == 0, "Run the watcher with sudo on the UE laptop")
    for command in ("mmcli", "ip", "ping"):
        connect.require(shutil.which(command), f"Missing required command: {command}")
    with connect.role_lock(args.ue):
        directory = Path(tempfile.mkdtemp(prefix=f"falcon-ue{args.ue}-reconnect-", dir=args.output_root))
        with (directory / "run.log").open("w") as log:
            watcher = Watcher(args, directory, log)

            with connect.StopSignals():
                return watcher.run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(f"STOP: {error}", file=sys.stderr)
        sys.exit(1)
