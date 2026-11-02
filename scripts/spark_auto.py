#!/usr/bin/env python3
"""Run the Spark testbed in one terminal; keep MongoDB and Docker on shutdown."""

import argparse
from collections import deque
from dataclasses import dataclass
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pty
import queue
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import threading
import time
import urllib.request

import yaml


ROOT = Path(__file__).resolve().parents[1]
CORE = tuple("open5gs-" + name for name in (
    "nrfd", "scpd", "udrd", "udmd", "ausfd", "pcfd", "nssfd", "upfd", "smfd", "amfd"))
LEGACY = tuple("open5gs-" + name for name in (
    "mmed", "hssd", "pcrfd", "sgwcd", "sgwud", "bsfd", "seppd"))
ORDER = ("ric", "cu", "du1", "du2", "xapp")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Executed in an already separate session, before exec; no preexec_fn in a
# multithreaded parent. All native components retain a controlling terminal.
PTY_EXEC = "import fcntl,os,sys,termios; fcntl.ioctl(0,termios.TIOCSCTTY,0); os.execvpe(sys.argv[1],sys.argv[1:],os.environ)"


class Fault(RuntimeError):
    pass


class Stopping(Exception):
    pass


@dataclass
class Service:
    name: str
    argv: list
    cwd: Path
    markers: tuple = ()


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    os.replace(temporary, path)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def start_ticks(pid):
    # comm may contain spaces or parentheses.
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def group_alive(pgid):
    # Exclude zombies; SIGKILL cannot remove a zombie awaiting its parent.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == pgid and fields[0] != "Z":
                return True
        except (OSError, ValueError, IndexError):
            continue
    return False


def signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


class Child:
    def __init__(self, spec, directory, events):
        self.spec, self.events = spec, events
        self.seen = set()
        self.tail = deque(maxlen=100)
        self.error = None
        self.deletions = 0
        self.subscriptions = None
        self.apps = set()
        self.finished = threading.Event()
        self.path = directory / (spec.name + ".console.log")
        self.stream = self.path.open("wb", buffering=0)
        master, slave = pty.openpty()
        settings = termios.tcgetattr(slave)
        settings[3] &= ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, settings)
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-u", "-c", PTY_EXEC, *map(str, spec.argv)],
                cwd=spec.cwd, stdin=slave, stdout=slave, stderr=slave,
                start_new_session=True, close_fds=True)
        except BaseException:
            self.stream.close()
            os.close(master)
            raise
        finally:
            os.close(slave)
        self.master = master
        self.thread = threading.Thread(target=self._read, name=spec.name + "-log", daemon=True)
        self.thread.start()

    def _line(self, raw):
        line = ANSI.sub("", raw.decode(errors="replace")).strip()
        self.tail.append(line)
        for marker in self.spec.markers:
            if marker in line:
                self.seen.add(marker)
        if "E42 SUBSCRIPTION DELETE RESPONSE rx" in line:
            self.deletions += 1
        match = re.search(r"identity collector: (\d+) KPM subscriptions", line)
        if match:
            self.subscriptions = int(match[1])
        if self.spec.name == "du2" and re.search(r"gain set|gain.*(?:fail|not successful)|invalid.*(?:gain|command)", line, re.I):
            self._event("du2", line)
        if self.spec.name == "xapp":
            for kind in ("APP_REGISTER_RECEIVED", "APP_REGISTERED", "APP_REGISTER_REJECTED",
                         "APP_UNREGISTER_RECEIVED", "APP_UNREGISTERED", "APP_DISCONNECTED"):
                if kind + " " not in line:
                    continue
                try:
                    value = json.loads(line.split(kind + " ", 1)[1])
                    key = value.get("subscription_id")
                    if kind == "APP_REGISTERED":
                        self.apps.add(key)
                    elif kind in ("APP_UNREGISTERED", "APP_DISCONNECTED"):
                        self.apps.discard(key)
                    fields = ["app=" + str(value.get("requested_app_id") or value.get("app_id") or "-")]
                    for label, field in (("request", "request_id"), ("subscription", "subscription_id"),
                                         ("acknowledgement", "acknowledgement"), ("reason", "reason")):
                        if value.get(field) is not None:
                            fields.append(f"{label}={value[field]}")
                    self._event("xapp", kind + " " + " ".join(fields))
                except (ValueError, TypeError):
                    pass

    def _event(self, name, line):
        try:
            self.events.put_nowait((name, line))
        except queue.Full:
            pass  # Full console log remains on disk; UI must not block readers.

    def _read(self):
        pending = b""
        try:
            while True:
                try:
                    data = os.read(self.master, 16384)
                except OSError as exc:
                    if exc.errno == 5:  # PTY slave closed (EIO).
                        break
                    raise
                if not data:
                    break
                self.stream.write(data)
                pending += data
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    self._line(line[-16384:])
                pending = pending[-16384:]
            if pending:
                self._line(pending)
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.stream.close()
            self.finished.set()

    def ready(self):
        return all(marker in self.seen for marker in self.spec.markers)

    def write(self, command):
        if self.process.poll() is not None:
            raise Fault("DU2 is no longer running")
        # The native dispatcher splits on semicolons, then removes newlines.
        # Delimit every command even when several writes arrive in one read.
        os.write(self.master, (command + ";\n").encode("ascii"))

    def close_log(self):
        self.thread.join(timeout=2)
        os.close(self.master)
        self.thread.join(timeout=1)


def socket_rows(text):
    rows = []
    seen = set()
    for line in text.splitlines():
        parts = line.split()
        for state in ("LISTEN", "UNCONN", "ESTAB"):
            if state not in parts:
                continue
            i = parts.index(state)
            if len(parts) > i + 4:
                # ss may print both an endpoint and its indented association,
                # and annotate the latter with %interface. Count it only once.
                local, peer = (re.sub(r"%[^:\]]+", "", endpoint) for endpoint in parts[i + 3:i + 5])
                row = (state, local, peer)
                if row not in seen:
                    rows.append(row)
                    seen.add(row)
            break
    return rows


def port(endpoint):
    try:
        return int(endpoint.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        return None


class Host:
    """All mutating host operations are confined to these explicit methods."""

    def __init__(self, command, identity):
        self.command, self.identity = command, identity

    def collision_check(self):
        conflicts = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                comm = (entry / "comm").read_text().strip()
                argv = (entry / "cmdline").read_bytes().decode(errors="replace").split("\0")
                if comm in ("odu", "ocu", "nearRT-RIC") or any(Path(arg).name == "xapp_ue_identity.py" for arg in argv):
                    conflicts.append(f"{comm} PID {entry.name}")
            except OSError:
                continue
        sctp = self.command(["ss", "-H", "-l", "-n", "-A", "sctp"])
        tcp = self.command(["ss", "-H", "-ltn"])
        for _, local, _ in socket_rows(sctp + "\n" + tcp):
            if port(local) in (36421, 36422, 38472, 8765):
                conflicts.append("occupied endpoint " + local)
        if conflicts:
            raise Fault("Stop the manual RAN/xApp before using auto mode: " + "; ".join(conflicts))

    def database_start(self):
        running = self.command(["docker", "inspect", "--format", "{{.State.Running}}", "open5gs-mongo"]).strip()
        if running != "true":
            self.command(["docker", "start", "open5gs-mongo"])

    def database_check(self, subscribers=False):
        code = "if (db.adminCommand({ping:1}).ok !== 1) quit(1);"
        if subscribers:
            # Only query fields needed for the session check; never authentication.
            code += """
const s=db.getSiblingDB('open5gs').subscribers;
for (const [imsi,dnn] of [['001010000000101','internet'],['001010000000102','internet2']]) {
 const rows=s.find({imsi},{_id:0,slice:1}).toArray();
 const sessions=rows.length===1 ? (rows[0].slice||[]).filter(x=>x.sst===1)
   .flatMap(x=>x.session||[]).filter(x=>x.name===dnn&&x.type===1) : [];
 if(sessions.length!==1) { print('Invalid subscriber/session: '+imsi); quit(1); }
}
"""
        self.command(["docker", "exec", "open5gs-mongo", "mongosh", "--quiet", "--eval", code])

    def core_start(self):
        # Match the dedicated Spark SA selection in the manual procedure.
        self.command(["systemctl", "stop", "--no-block", *LEGACY])
        for unit in CORE:
            self.command(["systemctl", "start", "--no-block", unit])

    def core_check(self):
        state = self.command(["systemctl", "is-active", *CORE]).splitlines()
        if state != ["active"] * len(CORE):
            raise Fault("Not all ten Open5GS services are active")
        for suffix, subnet in ((1, "10.45"), (2, "10.46")):
            tun = f"ogstun_{suffix}"
            links = json.loads(self.command(["ip", "-j", "link", "show", "dev", tun]))
            if len(links) != 1 or "UP" not in links[0]["flags"] or links[0]["mtu"] != 1400:
                raise Fault(tun + " must be UP with MTU 1400")
            addresses = json.loads(self.command(["ip", "-j", "-4", "addr", "show", "dev", tun]))
            if not any(a.get("local") == subnet + ".0.1" and a.get("prefixlen") == 16
                       for link in addresses for a in link.get("addr_info", [])):
                raise Fault(tun + " has the wrong IPv4 address")
            routes = json.loads(self.command(["ip", "-j", "-4", "route", "show", subnet + ".0.0/16"]))
            if not routes or any(r.get("dev") != tun for r in routes):
                raise Fault("Wrong route for " + subnet + ".0.0/16")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for url in (self.identity["amf"]["url"], self.identity["smf_url"]):
            with opener.open(url + "?page=0&page_size=1", timeout=2) as response:
                value = json.loads(response.read(1024 * 1024))
                if response.status != 200 or not isinstance(value.get("items"), list) or not isinstance(value.get("pager"), dict):
                    raise Fault("Core infoAPI is not ready")

    def transport_check(self, ready):
        sctp = socket_rows(self.command(["ss", "-H", "-n", "-a", "-A", "sctp"]))
        listeners = {port(local) for state, local, peer in sctp if state in ("LISTEN", "UNCONN")}
        established = [(port(local), port(peer)) for state, local, peer in sctp if state == "ESTAB"]
        if "ric" in ready and not {36421, 36422} <= listeners:
            raise Fault("RIC E2/E42 listeners are unavailable")
        nodes = sum(name in ready for name in ("cu", "du1", "du2"))
        if sum(local == 36421 for local, peer in established) < nodes:
            raise Fault("RIC E2 association missing")
        if "cu" in ready and not any(peer == 38412 for local, peer in established):
            raise Fault("CU N2 association missing")
        dus = sum(name in ready for name in ("du1", "du2"))
        if sum(local == 38472 for local, peer in established) < dus:
            raise Fault("CU/DU F1 association missing")
        if "xapp" in ready:
            tcp = socket_rows(self.command(["ss", "-H", "-ltn"]))
            if not any(port(local) == 8765 for state, local, peer in tcp):
                raise Fault("xApp application listener is unavailable")
            if not any(local == 36422 for local, peer in established):
                raise Fault("xApp E42 association missing")

    def core_stop(self):
        self.command(["systemctl", "stop", "--no-block", *reversed(CORE)], stopping=True)

    def core_stopped(self):
        value = self.command(["systemctl", "show", "--property=ActiveState", "--value", *CORE], stopping=True)
        states = value.split()
        return len(states) == len(CORE) and all(s in ("inactive", "failed") for s in states)

    def core_kill(self):
        self.command(["systemctl", "kill", "--kill-whom=all", "--signal=SIGKILL", *CORE], stopping=True)


class Supervisor:
    def __init__(self, args, directory, host=None):
        self.args, self.directory = args, Path(directory)
        self.children = {}
        self.ready = set()
        self.events = queue.Queue(maxsize=256)
        self.stop_event = threading.Event()
        self.reason = ""
        self.failed = False
        self.core_managed = False
        self.core_ready = False
        self.phase = "preparing"
        self.cleanup_errors = []
        self.health_failures = 0
        self.next_health = 0
        self.host = host
        self.audit = (self.directory / "supervisor.log").open("a", buffering=1)
        self.audit_failed = False

    def io_failure(self, message):
        # A full disk or closed output must never prevent process cleanup.
        if message not in self.cleanup_errors:
            self.cleanup_errors.append(message)
        self.failed = True
        self.request_stop(message)

    def say(self, text):
        try:
            print(text, flush=True)
        except OSError:
            self.io_failure("Controller output unavailable")
        if not self.audit_failed:
            try:
                self.audit.write(time.strftime("%Y-%m-%dT%H:%M:%S%z ") + text + "\n")
            except OSError:
                self.audit_failed = True
                self.io_failure("Controller audit log unavailable")

    def snapshot(self):
        value = dict(supervisor="falcon-spark-auto", pid=os.getpid(), start_ticks=start_ticks(os.getpid()),
                     script=str(Path(__file__).resolve()), phase=self.phase, reason=self.reason,
                     ready=sorted(self.ready), failed=self.failed, cleanup_errors=self.cleanup_errors,
                     core_managed=self.core_managed, mongo_preserved=True,
                     processes={name: dict(pid=child.process.pid, exit_code=child.process.poll(),
                         ready=name in self.ready, console=str(child.path)) for name, child in self.children.items()},
                     registrations=len(self.children["xapp"].apps) if "xapp" in self.children else 0)
        try:
            atomic_json(self.directory / "status.json", value)
        except OSError:
            self.io_failure("Controller status file unavailable")
        return value

    def request_stop(self, reason):
        if not self.stop_event.is_set():
            self.reason = reason
        self.stop_event.set()

    def check_children(self):
        if self.stop_event.is_set():
            raise Stopping()
        for name, child in self.children.items():
            if child.process.poll() is not None:
                raise Fault(f"{name} exited unexpectedly ({child.process.returncode}); see {child.path}")
            if child.error:
                raise Fault(f"{name} console logging failed: {child.error}")

    def command(self, argv, timeout=10, stopping=False, cwd=None, env=None):
        # Drain output to a file, not an unbounded pipe. Each command is bounded
        # and in its own group so cancellation does not leave build/health jobs.
        with tempfile.TemporaryFile(dir=self.directory) as output:
            process = subprocess.Popen(list(map(str, argv)), stdout=output, stderr=output,
                                       cwd=cwd, env=env, start_new_session=True)
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if not stopping:
                        self.check_children()
                    if time.monotonic() >= deadline:
                        raise Fault("Command timed out: " + str(argv[0]))
                    time.sleep(0.05)
                output.seek(0)
                data = output.read(65536).decode(errors="replace")
                if process.returncode:
                    raise Fault(f"{Path(str(argv[0])).name} failed ({process.returncode}): {data[-2000:].strip()}")
                return data
            finally:
                # Also reap descendants of commands that exited before a child.
                if group_alive(process.pid):
                    signal_group(process.pid, signal.SIGKILL)
                process.wait()

    def health(self):
        if not self.core_ready or time.monotonic() < self.next_health:
            return
        self.next_health = time.monotonic() + self.args.health_interval
        try:
            self.host.database_check()
            self.host.core_check()
            self.host.transport_check(self.ready)
        except Stopping:
            raise
        except Exception as exc:
            self.health_failures += 1
            self.say(f"[HEALTH {self.health_failures}/{self.args.health_failures}] {exc}")
            if self.health_failures >= self.args.health_failures:
                raise Fault("Sustained infrastructure health failure: " + str(exc)) from exc
        else:
            self.health_failures = 0
        self.snapshot()

    def pump(self):
        self.check_children()
        while True:
            try:
                name, line = self.events.get_nowait()
            except queue.Empty:
                break
            self.say(f"[{name}] {line}")
        self.health()

    def wait(self, label, condition, timeout=None):
        deadline = time.monotonic() + (self.args.startup_timeout if timeout is None else timeout)
        last = "not ready"
        while True:
            self.pump()
            try:
                if condition():
                    return
            except Stopping:
                raise
            except Exception as exc:
                last = str(exc)
            if time.monotonic() >= deadline:
                raise Fault(f"{label} startup timed out: {last}")
            self.stop_event.wait(0.1)

    def service_ready(self, name):
        child = self.children[name]
        if not child.ready():
            return False
        self.host.transport_check(self.ready | {name})
        return True

    def input_command(self, line):
        line = line.strip()
        if line in ("stop", "quit", "exit"):
            self.request_stop("operator stop")
        elif line == "status":
            value = self.snapshot()
            self.say(f"[STATUS] {self.phase}; ready={','.join(value['ready'])}; broker registrations={value['registrations']}")
        elif line in ("help", "?"):
            self.say("Commands: status | tx_gain 0 VALUE | rx_gain 0 VALUE | stop; Ctrl+C stops the testbed.")
        else:
            match = re.fullmatch(r"(tx_gain|rx_gain)\s+0\s+(\d+(?:\.\d+)?)", line)
            if not match:
                self.say("[INPUT] Use status, stop, tx_gain 0 VALUE or rx_gain 0 VALUE (DU2 only).")
                return
            # B210 single-channel hardware ranges. Native DU/UHD still validates.
            limit = 89.75 if match[1] == "tx_gain" else 76.0
            gain = float(match[2])
            if not math.isfinite(gain) or not 0 <= gain <= limit:
                self.say(f"[INPUT] {match[1]} must be within 0..{limit} dB.")
                return
            if "du2" not in self.ready:
                self.say("[INPUT] DU2 is not ready.")
                return
            self.children["du2"].write(line)
            self.say("[DU2 INPUT] " + line)

    def execute(self, services, interactive=True):
        old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        for sig in old_handlers:
            signal.signal(sig, lambda number, frame: self.request_stop(signal.Signals(number).name))
        try:
            self.say("[DATABASE] Checking MongoDB and the two subscriber profiles")
            self.host.database_start()
            self.wait("MongoDB", lambda: self.host.database_check(subscribers=True) is None)
            self.say("[READY] database")
            self.core_managed = True
            self.phase = "starting core"
            self.host.core_start()
            self.wait("5GC", lambda: self.host.core_check() is None)
            self.core_ready = True
            self.say("[READY] 5GC (10 services, TUN/routes and infoAPIs)")
            for spec in services:
                self.phase = "starting " + spec.name
                self.say("[START] " + spec.name)
                self.children[spec.name] = Child(spec, self.directory, self.events)
                self.snapshot()
                self.wait(spec.name, lambda name=spec.name: self.service_ready(name))
                self.ready.add(spec.name)
                self.say("[READY] " + spec.name)
                self.snapshot()
            self.phase = "running"
            self.snapshot()
            self.say("[RUNNING] Waiting for MPTCP registration; UE/KPM/client absence is not a component failure.")
            self.say("Commands: status | tx_gain 0 VALUE | rx_gain 0 VALUE | stop. Ctrl+C stops all managed services.")
            pending = b""
            while not self.stop_event.is_set():
                self.pump()
                if interactive and select.select([sys.stdin], [], [], 0.1)[0]:
                    data = os.read(sys.stdin.fileno(), 4096)
                    if not data:
                        self.request_stop("control terminal EOF")
                    else:
                        pending += data
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            self.input_command(line.decode(errors="replace"))
                        if len(pending) > 256:
                            pending = b""
                            self.say("[INPUT] Command too long")
                else:
                    self.stop_event.wait(0.1)
        except Stopping:
            pass
        except Exception as exc:
            self.failed = True
            self.reason = str(exc)
            self.say("[FAILED] " + self.reason)
        finally:
            self.phase = "stopping"
            self.say("[STOP] " + (self.reason or "startup interrupted"))
            self.cleanup()
            self.phase = "failed" if self.failed or self.cleanup_errors else "stopped"
            self.snapshot()
            self.say(f"[{self.phase.upper()}] Docker/MongoDB preserved; logs: {self.directory}")
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
            try:
                self.audit.close()
            except OSError:
                self.io_failure("Controller audit log unavailable")
        return 1 if self.failed or self.cleanup_errors else 0

    def stop_child(self, name):
        child = self.children.get(name)
        if child is None:
            return
        self.say("[STOP] " + name)
        deadline = time.monotonic() + self.args.stop_timeout
        if child.process.poll() is None:
            # Signal only the coordinator first: it owns collector E2 deletion.
            try:
                child.process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            while child.process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
        forced = child.process.poll() is None
        if group_alive(child.process.pid):
            signal_group(child.process.pid, signal.SIGTERM)
            grace = time.monotonic() + min(3, self.args.stop_timeout)
            while group_alive(child.process.pid) and time.monotonic() < grace:
                time.sleep(0.05)
            if group_alive(child.process.pid):
                forced = True
                signal_group(child.process.pid, signal.SIGKILL)
        child.process.wait(timeout=3)
        deadline = time.monotonic() + 2
        while group_alive(child.process.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if group_alive(child.process.pid):
            self.cleanup_errors.append(name + ": process group still alive after SIGKILL")
        child.close_log()
        if not child.finished.is_set():
            self.cleanup_errors.append(name + ": console reader did not finish")
        if forced or child.error or child.process.returncode != 0:
            self.cleanup_errors.append(f"{name}: exit={child.process.returncode}, forced={forced}, log_error={child.error}")
        if name == "xapp" and name in self.ready:
            if child.deletions != 3:
                self.cleanup_errors.append(f"xapp: {child.deletions}/3 E2 delete responses; cleanup unverified")
            summary = self.directory / "publisher.json"
            try:
                value = json.loads(summary.read_text())
                if value["status"] != "passed" or any(value["counters"].get(k, 0) for k in ("active_connections", "active_registrations")):
                    raise ValueError("failed publisher/active connections")
            except (OSError, ValueError, KeyError) as exc:
                self.cleanup_errors.append("xapp final summary: " + str(exc))

    def cleanup(self):
        for name in ("xapp", "du2", "du1", "cu", "ric"):
            try:
                self.stop_child(name)
            except Exception as exc:
                self.cleanup_errors.append(name + ": " + str(exc))
        if self.core_managed:
            try:
                self.host.core_stop()
                deadline = time.monotonic() + self.args.stop_timeout
                while not self.host.core_stopped() and time.monotonic() < deadline:
                    time.sleep(0.1)
                if not self.host.core_stopped():
                    self.host.core_kill()
                    self.cleanup_errors.append("5GC stop timed out; sent SIGKILL to managed units")
                    deadline = time.monotonic() + 3
                    while not self.host.core_stopped() and time.monotonic() < deadline:
                        time.sleep(0.1)
                    if not self.host.core_stopped():
                        self.cleanup_errors.append("5GC units remain active after SIGKILL")
            except Exception as exc:
                self.cleanup_errors.append("5GC stop: " + str(exc))
        for error in self.cleanup_errors:
            self.say("[CLEANUP] " + error)


def check_files(args):
    ocudu = args.ocudu.resolve()
    sources = {
        "cu.yml": ocudu / "configs/cu.yml",
        "cu_identity_e2.yml": ROOT / "configs/ocudu/cu_identity_e2.yml",
        "du1.yml": ocudu / "configs/du1_b210_n78_3660mhz.yml",
        "du2.yml": ocudu / "configs/du2_b210_n78_40mhz.yml",
        "du2_e2.yml": ocudu / "configs/du2_flexric.yml",
        "local.json": ROOT / "configs/ue_identity/local.json",
        "subscriptions.json": ROOT / "configs/ue_identity/subscriptions.json",
    }
    for path in sources.values():
        if not path.is_file():
            raise Fault("Missing configuration: " + str(path))
    for path in (args.flexric / "build-ocudu/src/xApp/libe42_xapp.a",
                 args.flexric / "build-ocudu/src/util/CMakeFiles/e2_time_obj.dir/time_now_us.c.o",
                 ROOT / "configs/flexric/ric_ue_identity.conf",
                 ROOT / "configs/flexric/xapp_ue_identity_expanded.conf"):
        if not path.is_file():
            raise Fault("Missing pinned FlexRIC artifact/configuration: " + str(path))
    publish = json.loads(sources["subscriptions.json"].read_text())
    if publish.get("bind") != "127.0.0.1" or publish.get("port") != 8765:
        raise Fault("Auto mode expects the MPTCP broker on 127.0.0.1:8765")
    for path in (ocudu / "build-integrated/apps/cu/ocu", ocudu / "build-integrated/apps/du_split_8/odu", args.ric):
        if not path.is_file() or not os.access(path, os.X_OK):
            raise Fault("Missing executable; complete manual build preparation: " + str(path))
    for name in ("docker", "systemctl", "ip", "ss", "stdbuf", "bash", "gcc"):
        if not shutil.which(name):
            raise Fault("Missing command: " + name)
    spec = importlib.util.spec_from_file_location("falcon_auto_config", ROOT / "scripts/dual_fr1/check_config.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    cu = checker.merge(checker.load(sources["cu.yml"]), checker.load(sources["cu_identity_e2.yml"]))
    du1 = checker.load(sources["du1.yml"])
    du2 = checker.merge(checker.load(sources["du2.yml"]), checker.load(sources["du2_e2.yml"]))
    # Auto mode overrides log filenames into its private run directory. Old
    # manual log ownership must not invalidate an otherwise valid offline check.
    for label, config in (("du1", du1), ("du2", du2)):
        config["log"]["filename"] = str(args.run_root / f"falcon-auto-check-{os.getpid()}-{label}.log")
    errors, _ = checker.validate(cu, du1, du2)
    for label, config, gains in (("DU1", du1, (70, 35)), ("DU2", du2, (60, 10))):
        if (config["ru_sdr"].get("tx_gain"), config["ru_sdr"].get("rx_gain")) != gains:
            errors.append(f"{label}: expected accepted startup gains {gains}; source YAML is never rewritten")
    if cu["metrics"]["periodicity"].get("cu_cp_report_period") != 1000:
        errors.append("CU identity period must be 1000 ms")
    if errors:
        raise Fault("; ".join(errors))
    return sources


def prepare(supervisor, sources):
    directory = supervisor.directory
    hashes = {}
    for name, source in sources.items():
        shutil.copyfile(source, directory / name)
        hashes[str(source)] = file_sha256(source)
    env = dict(os.environ, FALCON_IDENTITY_SM_DIR=str(directory / "sm"), FLEXRIC_DIR=str(supervisor.args.flexric),
               FLEXRIC_BUILD=str(supervisor.args.flexric / "build-ocudu"))
    supervisor.say("[PREPARE] Building the isolated collector/plugin; no services started")
    result = supervisor.command(["bash", ROOT / "scripts/ue_identity/build.sh", directory / "collector"],
                                timeout=supervisor.args.build_timeout, env=env)
    (directory / "build.log").write_text(result)
    for name, source in (("ric.conf", ROOT / "configs/flexric/ric_ue_identity.conf"),
                         ("xapp.conf", ROOT / "configs/flexric/xapp_ue_identity_expanded.conf")):
        replacement = "SM_DIR = " + json.dumps(str(directory / "sm") + "/")
        text, count = re.subn(r'^SM_DIR\s*=.*$', lambda match: replacement, source.read_text(), count=1, flags=re.M)
        if count != 1:
            raise Fault("Cannot select the isolated plugin in " + str(source))
        (directory / name).write_text(text)
        supervisor.command([directory / "collector", "--check-config", directory / name])
    supervisor.command([directory / "collector", "--check-clock"])
    for path in (directory / "collector", directory / "sm/libkpm_sm.so", supervisor.args.ric,
                 supervisor.args.ocudu / "build-integrated/apps/cu/ocu",
                 supervisor.args.ocudu / "build-integrated/apps/du_split_8/odu"):
        hashes[str(path)] = file_sha256(path)
    revisions = {}
    for path in (ROOT, supervisor.args.ocudu, supervisor.args.flexric):
        # The controller runs as root, while these user-owned repositories do
        # not. Trust only this explicit path for these read-only git commands.
        git = ["git", "-c", "safe.directory=" + str(path), "-C", path]
        revisions[str(path)] = dict(head=supervisor.command([*git, "rev-parse", "HEAD"]).strip(),
                                   status=supervisor.command([*git, "status", "--short"]).splitlines())
    atomic_json(directory / "manifest.json", dict(hashes=hashes, revisions=revisions))
    ocudu = supervisor.args.ocudu
    ran = ocudu / "build-integrated/apps"
    return [
        Service("ric", ["stdbuf", "-oL", "-eL", supervisor.args.ric, "-c", directory / "ric.conf"], ROOT,
                ("[NEAR-RIC]: Loading SM ID = 2 with def = ORAN-E2SM-KPM",)),
        Service("cu", [ran / "cu/ocu", "-c", directory / "cu.yml", "-c", directory / "cu_identity_e2.yml",
                       "log", "--filename", directory / "cu.log"], ocudu,
                ("==== CU started ===", "N2: Connection", "E2AP: Connection")),
        Service("du1", [ran / "du_split_8/odu", "-c", directory / "du1.yml", "log", "--filename", directory / "du1.log"], ocudu,
                ("==== DU started ===", "F1-C: Connection to CU-CP", "E2AP: Connection")),
        Service("du2", [ran / "du_split_8/odu", "-c", directory / "du2.yml", "-c", directory / "du2_e2.yml",
                        "log", "--filename", directory / "du2.log"], ocudu,
                ("==== DU started ===", "F1-C: Connection to CU-CP", "E2AP: Connection")),
        Service("xapp", [sys.executable, "-B", ROOT / "scripts/ue_identity/xapp_ue_identity.py",
                         "--collector", directory / "collector", "--config", directory / "local.json",
                         "--e2-config", directory / "xapp.conf", "--publish-config", directory / "subscriptions.json",
                         "--fresh-only", "--duration", "0", "--publisher-summary", directory / "publisher.json"], ROOT,
                ("SUBSCRIPTION_READY host=127.0.0.1 port=8765 profile=du27_bound_v1 source=e2",
                 "identity collector: 3 KPM subscriptions, duration=0")),
    ]


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    mode = value.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="read-only offline file/config checks; no host or radio operations")
    mode.add_argument("--prepare-only", action="store_true", help="build isolated collector/plugin without starting services")
    mode.add_argument("--stop", type=Path, metavar="RUN_DIRECTORY", help="request normal shutdown of an existing auto controller")
    mode.add_argument("--status", type=Path, metavar="RUN_DIRECTORY", help="read an existing run's status.json")
    value.add_argument("--ocudu", type=Path, default=Path("/home/nyu/ocudu"))
    value.add_argument("--flexric", type=Path, default=Path("/home/nyu/flexric"))
    value.add_argument("--ric", type=Path, default=Path("/usr/local/bin/flexric/ric/nearRT-RIC"))
    value.add_argument("--run-root", type=Path, default=Path("/tmp"))
    value.add_argument("--startup-timeout", type=float, default=120)
    value.add_argument("--build-timeout", type=float, default=180)
    value.add_argument("--stop-timeout", type=float, default=30)
    value.add_argument("--health-interval", type=float, default=5)
    value.add_argument("--health-failures", type=int, default=3)
    value.add_argument("--no-input", action="store_true", help="signals/status files only; no DU2 command input")
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    if any(not math.isfinite(getattr(args, key)) or getattr(args, key) <= 0 for key in
           ("startup_timeout", "build_timeout", "stop_timeout", "health_interval")) or args.health_failures < 1:
        raise Fault("Timeouts/intervals and health-failures must be positive")
    if args.status or args.stop:
        directory = args.status or args.stop
        state = json.loads((directory / "status.json").read_text())
        if args.status:
            print(json.dumps(state, indent=2))
            return 0
        pid = state["pid"]
        if state.get("supervisor") != "falcon-spark-auto" or pid <= 1 or state["phase"] in ("stopped", "failed", "prepared"):
            raise Fault("No active auto controller in that run directory")
        if start_ticks(pid) != state["start_ticks"]:
            raise Fault("Stale controller PID; no signal sent")
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if not any(Path(arg.decode(errors="replace")).name == "spark_auto.py" for arg in command):
            raise Fault("PID is not a spark_auto controller; no signal sent")
        os.kill(pid, signal.SIGINT)
        print("Normal shutdown requested; inspect the controller or status.json for completion.")
        return 0
    args.ocudu, args.flexric, args.ric = args.ocudu.resolve(), args.flexric.resolve(), args.ric.resolve()
    args.run_root = args.run_root.resolve()
    sources = check_files(args)
    if args.check:
        print("PASS: offline configs/artifacts; DU1 70/35, DU2 60/10; no services/radios started.")
        return 0
    if not args.prepare_only and os.geteuid() != 0:
        raise Fault("Run with sudo python3 -B scripts/spark_auto.py (one controller manages native processes and systemd)")
    if not args.prepare_only and not args.no_input and not sys.stdin.isatty():
        raise Fault("Use an interactive terminal, or explicitly select --no-input")
    lock = None
    if not args.prepare_only:
        lock = open("/run/lock/falcon-spark-auto.lock", "a+")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Fault("Another Spark auto controller is already running") from None
    directory = Path(tempfile.mkdtemp(prefix="falcon-spark-auto-", dir=args.run_root))
    print("Spark auto run directory:", directory, flush=True)
    supervisor = Supervisor(args, directory)
    old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    for sig in old_handlers:
        signal.signal(sig, lambda number, frame: supervisor.request_stop(signal.Signals(number).name))
    try:
        supervisor.snapshot()
        identity = json.loads(sources["local.json"].read_text())
        supervisor.host = Host(supervisor.command, identity)
        if not args.prepare_only:
            supervisor.host.collision_check()
        services = prepare(supervisor, sources)
        if args.prepare_only:
            supervisor.phase = "prepared"
            supervisor.snapshot()
            supervisor.say("[PREPARED] No services or radios started")
            return 0
        return supervisor.execute(services, interactive=not args.no_input)
    except Stopping:
        supervisor.phase = "stopped"
        supervisor.snapshot()
        supervisor.say("[STOPPED] Preparation cancelled; no services or radios started")
        return 130
    except BaseException as exc:
        supervisor.phase = "failed"
        supervisor.failed = True
        supervisor.reason = str(exc)
        supervisor.snapshot()
        raise
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if not supervisor.audit.closed:
            try:
                supervisor.audit.close()
            except OSError:
                pass
        if lock:
            lock.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Fault, OSError, ValueError) as error:
        print("FAIL:", error, file=sys.stderr)
        sys.exit(1)
