#!/usr/bin/env python3
"""Watch one laptop UE; recover PDU/host state and optional cell lock until Ctrl+C."""

import argparse
import contextlib
import csv
from datetime import datetime, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

import connect_ue as connect


ERRORS = (ValueError, OSError, subprocess.SubprocessError, connect.termios.error, csv.Error)
SHARED_LOCK = "/run/lock/falcon-ue-connect.lock"


def radio_query(fd, command, evidence):
    print("AT > " + command, flush=True)
    evidence.setdefault("commands", []).append(command)
    reply = connect.at_reply(fd, command)
    print(reply.strip(), flush=True)
    return reply


def restore_cell_lock(at_port, info, role, evidence):
    """Restore this verified modem's NR SA settings; OK is not serving proof."""
    def query(fd, command):
        return radio_query(fd, command, evidence)

    def fields(fd, command, prefix, name):
        reply = query(fd, command)
        records = [next(csv.reader([line.split(":", 1)[1].strip()], skipinitialspace=True, strict=True))
                   for line in reply.replace("\r", "\n").splitlines()
                   if line.strip().startswith(prefix + ":")]
        records = [record for record in records if record and record[0] == name]
        if len(records) != 1 or len(records[0]) < 2:
            raise connect.CellError(f"Missing/ambiguous readback for {command}")
        return [value.strip() for value in records[0][1:]]

    def write(fd, command):
        # Record even a failed/interrupted write: some settings may already have
        # taken effect. Never report the operation as an atomic rollback.
        evidence.setdefault("writes", []).append(command)
        query(fd, command)

    with connect.serial_modem(at_port, info, role, query=query) as fd:
        for name, expected in (("mode_pref", "NR5G"), ("nr5g_disable_mode", "2")):
            command = f'AT+QNWPREFCFG="{name}"'
            if fields(fd, command, "+QNWPREFCFG", name) != [expected]:
                write(fd, command + "," + expected)
                if fields(fd, command, "+QNWPREFCFG", name) != [expected]:
                    raise connect.CellError(f"Setting readback mismatch: {name}")
        band_query = 'AT+QNWPREFCFG="nr5g_band"'
        bands = fields(fd, band_query, "+QNWPREFCFG", "nr5g_band")
        if len(bands) != 1 or "78" not in bands[0].split(":"):
            write(fd, band_query + ",78")
            bands = fields(fd, band_query, "+QNWPREFCFG", "nr5g_band")
            if len(bands) != 1 or "78" not in bands[0].split(":"):
                raise connect.CellError("NR SA band readback does not include n78")
        lock_query = 'AT+QNWLOCK="common/5g"'
        evidence["previous_lock"] = fields(fd, lock_query, "+QNWLOCK", "common/5g")
        target = [str(role["pci"]), str(role["ssb"]), "30", "78"]
        actual = evidence["previous_lock"]
        evidence["lock_action"] = "reused"
        if actual != target:
            evidence["lock_action"] = "written"
            try:
                write(fd, lock_query + "," + ",".join(target))
            except connect.ATCommandError as error:
                evidence["lock_write_error"] = dict(cme_code=error.cme_code, reply=error.reply)
                if error.cme_code != 902:
                    raise
                # A vendor rejection is never interpreted as success. Continue
                # only if an independent readback proves the exact target tuple.
                actual = fields(fd, lock_query, "+QNWLOCK", "common/5g")
                evidence["lock_after_error"] = actual
                if actual != target:
                    raise
                evidence["lock_action"] = "verified_after_902"
                connect.status("Radio recovery: lock write returned 902; exact target lock read back independently")
            else:
                actual = fields(fd, lock_query, "+QNWLOCK", "common/5g")
        else:
            connect.status("Radio recovery: saved cell lock already matches; skipping duplicate QNWLOCK write")
        if actual != target:
            raise connect.CellError(f"Cell-lock readback mismatch: expected {target}, got {actual}")
        evidence["verified_lock"] = actual
        for command, key in (('AT+QENG="servingcell"', "qeng"), ("AT+C5GREG?", "c5greg")):
            # SEARCH / not registered is valid diagnostic output after a lock
            # write; full registration and cell checks run on the next attempt.
            evidence[key] = query(fd, command).strip()


def serial_registration(evidence, role):
    """Distinguish live SA proof, known radio loss, and unparseable diagnostics."""
    matches = re.findall(r"(?m)^\s*\+C5GREG:\s*\d+\s*,\s*(\d+)(?:\s*,|\s*$)", evidence.get("c5greg", ""))
    registration = int(matches[0]) if len(matches) == 1 else None
    try:
        cell = connect.qeng_serving_cell(evidence.get("qeng", ""))
    except connect.CellError:
        cell = None
    expected_cell = (cell is not None and cell["pci"] == role["pci"] and cell["nci"] == role["nci"]
                     and cell.get("plmn") == "00101" and cell.get("tac") == 7
                     and cell.get("arfcn") in (role["ssb"], role["carrier"]) and cell.get("band") == 78)
    search = bool(re.search(r'\+QENG:\s*"servingcell"\s*,\s*"(?:SEARCH|LIMSRV)"', evidence.get("qeng", "")))
    result = dict(c5greg_status=registration, expected_serving_cell=expected_cell,
                  registered=expected_cell and registration in (1, 5),
                  radio_lost=search or registration in (0, 2, 3, 4))
    evidence["serial_registration"] = result
    return result


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



class Recovery(connect.Connection):
    def __init__(self, *args, redial=False, redial_allowed=True, failed_bearer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.redial_requested = redial
        self.redial_allowed = redial_allowed
        self.failed_bearer = failed_bearer
        self.redial_started_at = None

    def repair_radio(self):
        evidence = self.result["radio_recovery"]
        info, _ = self.active()  # Includes fresh IMEI/SIM and foreign-APN guards.
        net_ports = connect.ports(info)
        connect.require(len(net_ports) == 1, "Expected one owned WWAN for automatic cell lock")
        interface = next(iter(net_ports))
        with self.network(shared=True):
            self.host_preflight(dict(interface=interface))
        connect.status(f"Radio recovery: UE{self.ue} / {self.role['label']}; restore NR SA / "
                       f"PCI={self.role['pci']} SSB={self.role['ssb']}, then request PLMN 00101 registration")
        # MM can retain connected bearers after its own 3GPP state becomes
        # searching/detached. Release that owned stale PDU before locking.
        self.release_radio_pdu(evidence)
        info = self.checked_modem()
        restore_cell_lock(self.at_port, info, self.role, evidence)
        live = serial_registration(evidence, self.role)
        # Cover a stale positive MM registration cache when AT proves radio loss.
        if live["radio_lost"]:
            self.release_radio_pdu(evidence, serial_lost=True)
        # The serial context is closed before talking to ModemManager again.
        info = self.checked_modem()
        if info.get("modem.generic.state") == "disabled":
            connect.change("mmcli", "-m", self.modem, "--enable")
            info = self.checked_modem()
        technologies = {token.strip().lower() for value in connect.values(info, "modem.generic.access-technologies")
                        for token in value.split(",")}
        registered = (info.get("modem.generic.state") in ("registered", "connecting", "connected")
                      and info.get("modem.3gpp.operator-code") == "00101"
                      and "5gnr" in technologies and "lte" not in technologies)
        if not registered or not live["registered"]:
            connect.require(info.get("modem.generic.state") not in ("connecting", "connected", "disconnecting"),
                            "Modem still reports an active PDU; refusing registration until owned stale PDU is released")
            evidence["registration_requested"] = True
            connect.change("mmcli", "-m", self.modem, "--3gpp-register-in-operator=00101")
        else:
            evidence["registration_requested"] = False
        self.checked_modem()
        evidence["status"] = "applied"
        connect.status("Radio recovery [OK]: lock read back; next attempt must verify registration, cell, PDU and ping")

    @staticmethod
    def registration_lost(info):
        return (info.get("modem.3gpp.registration-state") in ("idle", "searching", "denied", "unknown")
                and info.get("modem.3gpp.packet-service-state") == "detached")

    def disconnectable(self, info, details):
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
        return dict(source=str(source), interface=interface)

    def release_radio_pdu(self, evidence, *, serial_lost=False):
        info, active = self.active()
        if not active or not (serial_lost or self.registration_lost(info)):
            return
        connect.require(self.redial_allowed, "Stale-PDU disconnect is in redial cooldown; continue radio checks")
        bearer = self.disconnectable(info, active[0][1])
        with self.network(shared=True):
            self.host_preflight(bearer)
        # Prove the serial endpoint before disrupting a PDU. Close it before
        # MM disconnects; the later lock transaction validates identities again.
        with connect.serial_modem(self.at_port, info, self.role,
                                  query=lambda fd, cmd: radio_query(fd, cmd, evidence)):
            pass
        latest, current = self.active()
        connect.require(self.allocation(current) == self.allocation(active),
                        "Bearer changed before radio recovery disconnect; retry discovery")
        connect.require(serial_lost or self.registration_lost(latest),
                        "3GPP registration recovered before stale-PDU disconnect; retry verification")
        with self.host_update(bearer):
            self.host_preflight(bearer)
            self.block(install=True)
        connect.status("Radio recovery: release selected UE's stale PDU before registration; Wi-Fi fallback stays blocked")
        self.redial_started_at = time.monotonic()
        evidence["pdu_disconnect_requested"] = True
        self.result.update(redial=True, previous_source=bearer["source"], previous_bearer=active[0][0],
                           redial_reason="radio lost with stale connected PDU")
        connect.change("mmcli", "-m", self.modem, "--simple-disconnect")
        _, remaining = self.active()
        connect.require(not remaining, "Bearer still connected after radio recovery disconnect")
        self.checked_modem()
        self.clear_host(bearer)
        evidence["pdu_disconnected"] = True

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
        bearer = self.disconnectable(info, details)
        source, interface = bearer["source"], bearer["interface"]
        with self.network(shared=True):
            self.host_preflight(dict(interface=interface))
            self.block(install=False)
        self.serving_cell()
        _, current = self.active()
        connect.require(self.allocation(current) == self.allocation(active),
                        "Bearer changed before disconnect; retry discovery")
        with self.network(shared=True):
            self.host_preflight(dict(interface=interface))
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
        self.clear_host(dict(interface=interface))
        self.redial_requested = False


def probe(session):
    """Read current state and send two single pings; no modem/network mutations."""
    started = time.monotonic()
    print(f"{now()} UE{session.ue} health check started", flush=True)
    session.discover()
    session.serving_cell()
    bearer = session.bearer()
    with session.network(shared=True):
        session.host_preflight(bearer)
        connect.require(session.configured(bearer), "Host path is incomplete or the bearer IP changed")
    for bound in (True, False):
        with session.network(shared=True):
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
    with session.network(shared=True):
        connect.require(session.configured(bearer), "Host path changed during health check")
        session.routes(bearer)
    print(f"{now()} UE{session.ue} health check OK: {bearer['source']} via {bearer['interface']}; "
          f"elapsed={time.monotonic() - started:.3f}s", flush=True)
    return bearer


class Watcher:
    def __init__(self, args, directory, log, stop=None):
        self.args, self.directory, self.log = args, Path(directory), log
        self.stop = stop if stop is not None else threading.Event()
        self.terminal = sys.stdout
        self.attempts = self.ping_failures = 0
        self.last_redial = None
        self.last_cell_lock = None
        self.failed_bearer = None
        self.healthy = False
        self.started_at = now()
        self.exit_signal = None
        self.modem_cache = {}

    def session(self, recovery=False):
        kwargs = dict(at_port=self.args.at_port, registration_timeout=self.args.registration_timeout,
                      ping_count=1, modem_cache=self.modem_cache, network_lock_path=SHARED_LOCK)
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

    def repair_radio(self, session, error):
        remaining = (0 if self.last_cell_lock is None else
                     max(0, self.args.cell_lock_cooldown - (time.monotonic() - self.last_cell_lock)))
        evidence = dict(status="cooldown" if remaining else "started", reason=str(error),
                        started_at=now(), at_port=self.args.at_port)
        session.result["radio_recovery"] = evidence
        if remaining:
            evidence["remaining_seconds"] = round(remaining, 1)
            connect.status(f"Radio recovery: cell-lock cooldown, {remaining:.1f}s remaining; continue checking registration")
            return
        try:
            session.repair_radio()
        except KeyboardInterrupt:
            evidence["status"] = "interrupted"
            raise
        except ERRORS as recovery_error:
            evidence.update(status="failed", error=str(recovery_error))
            connect.status(f"Radio recovery [FAIL]: {recovery_error}", error=True)
        finally:
            # Also throttle rejected/failed writes and registration requests.
            # Start the gap when the operation ends, not while it is in flight.
            self.last_cell_lock = time.monotonic()
            evidence["ended_at"] = now()

    def attempt(self):
        self.attempts += 1
        prefix = f"UE{self.args.ue} / {connect.ROLES[self.args.ue]['label']} attempt {self.attempts}"
        print(prefix + " ...", end=" " if self.args.verbose == 1 else "\n", file=self.terminal, flush=True)
        session = self.session(recovery=True)
        with capture(self.log, self.args.verbose):
            print(f"\n{now()} {prefix}", flush=True)
            try:
                try:
                    session.run()
                except connect.CellError as error:
                    if self.args.auto_cell_lock:
                        self.repair_radio(session, error)
                    raise
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
                session.result.update(status=("radio_retry_pending" if self.args.auto_cell_lock else "serial_check_required")
                                      if isinstance(error, connect.CellError) else "failed",
                                      stage=session.stage, error=str(error))
                connect.status(f"STOP at {session.stage}: {error}", error=True)
                if isinstance(error, subprocess.CalledProcessError) and error.stderr:
                    print(error.stderr, file=sys.stderr)
                if isinstance(error, connect.CellError) and not self.args.auto_cell_lock:
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
        try:
            self.say(f"Watching UE{self.args.ue}; interval={self.args.interval:g}s; independent modem/PDU checks, "
                     f"shared host updates; evidence={self.directory}; Ctrl+C to shut down this UE")
            while not self.stop.is_set():
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
                # Radio/PDU operations and ping never hold the shared network lock.
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
                    shutdown = connect.shutdown_on_interrupt(self.args.ue, lock_path=SHARED_LOCK,
                                                             modem_cache=self.modem_cache)
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
                           auto_cell_lock=self.args.auto_cell_lock, cell_lock_cooldown=self.args.cell_lock_cooldown,
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
    parser.add_argument("--at-port", help="Owned USB AT port for read-only cell fallback, or radio writes with --auto-cell-lock")
    parser.add_argument("--auto-cell-lock", action="store_true",
                        help="On registration/cell failure, restore this UE's NR SA/cell lock and request registration; requires --at-port")
    parser.add_argument("--cell-lock-cooldown", type=positive_seconds, default=30.0,
                        help="Minimum seconds AFTER a radio recovery before another, default 30; checks continue meanwhile")
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
    if args.auto_cell_lock and not args.at_port:
        parser.error("--auto-cell-lock requires --at-port for this UE's verified AT port")
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
