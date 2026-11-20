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


def du_names(args):
    if args.du2_wired20_only:
        return ("du2",)
    return ("du1",) if args.du1_only else ("du1", "du2")


def profile_name(args):
    return "wired-du2-ue2" if args.du2_wired20_only else "fr1-ue1" if args.du1_only else "dual"


def run_identity(args, source):
    """Scope the wired run's snapshot without creating another shared config."""
    identity = json.loads(source.read_text())
    if args.du2_wired20_only:
        identity["du_nodes"] = [node for node in identity["du_nodes"] if str(node.get("du_id")) == "2"]
        if len(identity["du_nodes"]) != 1 or "internet2" not in identity["dnns"]:
            raise Fault("Wired DU2 needs exactly one admitted DU 2 and DNN internet2")
        identity["dnns"] = ["internet2"]
    return identity


def service_order(args):
    return ("ric", "cu", *du_names(args), "xapp")


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
    native_log: Path = None
    gnb_id: str = None
    du_id: str = None
    required_protocol: tuple = ()


class LogTail:
    """Follow a private native log from creation, with bounded reads/lines."""

    def __init__(self, path, callback):
        self.path, self.callback = path, callback
        self.stream = None
        self.pending = b""

    def poll(self):
        try:
            current = self.path.stat()
        except FileNotFoundError:
            return
        if self.stream is not None:
            opened = os.fstat(self.stream.fileno())
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino) or current.st_size < self.stream.tell():
                self.close()
                self.pending = b""
        if self.stream is None:
            self.stream = self.path.open("rb")
        data = self.stream.read(262144)
        self.pending += data
        lines = self.pending.split(b"\n")
        self.pending = lines.pop()[-16384:]
        for line in lines:
            self.callback(line[-16384:])

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


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
        self.protocol = {}
        self.xapp_id = None
        self.e42_response = False
        self.available_e2_nodes = None
        self.broker_ready = False
        self.native = LogTail(spec.native_log, self._native_line) if spec.native_log else None
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
        if self.spec.name in ("cu", "du1", "du2") and self.native is None:
            self._native_line(raw)
        if self.spec.name in ("du1", "du2") and "Resident LDPC decoder enabled for PUSCH acceleration" in line:
            self._state("cuda_pusch", "ready", self.spec.name, "CUDA_PUSCH_READY device=0 resident_ldpc=true")
        if "E42 SUBSCRIPTION DELETE RESPONSE rx" in line:
            self.deletions += 1
        match = re.search(r"identity collector: (\d+) KPM subscriptions", line)
        if match:
            self.subscriptions = int(match[1])
            # The collector explicitly permits at most one KPM subscription
            # per E2 node (e2_collector.c); this is also the unique node count.
            self._event("xapp", f"KPM_SUBSCRIPTIONS_READY subscribed_e2_nodes={self.subscriptions} subscriptions={self.subscriptions}")
        if line.startswith("SUBSCRIPTION_READY host=127.0.0.1 port=8765 "):
            self.broker_ready = True
            self._event("xapp", "BROKER_READY endpoint=127.0.0.1:8765")
        self._console_protocol(line)
        if self.spec.name in ("du1", "du2") and re.search(r"gain set|gain.*(?:fail|not successful)|invalid.*(?:gain|command)", line, re.I):
            self._event(self.spec.name, line)
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
        # Publish readiness only after all events from this line are queued.
        for marker in self.spec.markers:
            if marker in line:
                self.seen.add(marker)

    def _state(self, key, state, owner, message):
        if self.protocol.get(key) == state:
            return
        if key not in self.protocol and len(self.protocol) >= 128:
            self.protocol.pop(next(iter(self.protocol)))
        self._event(owner, message)
        self.protocol[key] = state

    def _identity(self):
        fields = "node=" + self.spec.name.upper()
        if self.spec.gnb_id is not None:
            fields += " gnb_id=" + str(self.spec.gnb_id)
        if self.spec.du_id is not None:
            fields += " du_id=" + str(self.spec.du_id)
        return fields

    def _console_protocol(self, line):
        if self.spec.name == "ric":
            request = re.search(r"E2 SETUP-REQUEST rx from PLMN\s+\d+\.\s*\d+ Node ID (\d+) RAN type (\w+)(?: ID (\d+))?", line)
            if request:
                gnb, ran_type, du = request.groups()
                node = "DU" + du if ran_type == "ngran_gNB_DU" and du else "CU" if ran_type in (
                    "ngran_gNB", "ngran_gNB_CU", "ngran_gNB_CUCP") else ran_type
                self._event("ric", f"E2_REGISTER_RECEIVED node={node} gnb_id={gnb}" + (f" du_id={du}" if du else ""))
            if "[iApp]: E42 SETUP-REQUEST rx" in line:
                self._event("ric", "E42_REGISTER_RECEIVED node=xApp")
            if "[iApp]: E42 SETUP-RESPONSE tx" in line:
                self._event("ric", "E42_SETUP_RESPONSE_SENT node=xApp")
            disconnected = re.search(r"xApp (\d+) disconnected!", line)
            if disconnected:
                xid = disconnected[1]
                self._state("e42:" + xid, "disconnected", "ric", f"E42_DISCONNECTED xapp_id={xid}")
        if self.spec.name == "xapp":
            if "[xApp]: E42 SETUP-RESPONSE rx" in line:
                self.e42_response = True
            xid = re.search(r"\[xApp\]: xApp ID = (\d+)", line)
            if xid and self.e42_response:
                self.xapp_id = xid[1]
                self._state("e42", "registered", "ric", f"E42_REGISTERED node=xApp xapp_id={self.xapp_id} evidence=e42_setup_response_rx")
                self.e42_response = False
            nodes = re.search(r"Registered E2 Nodes = (\d+)", line)
            if nodes:
                self.available_e2_nodes = int(nodes[1])

    def _native_line(self, raw):
        if not any(marker in raw for marker in (b"E2 Setup procedure", b"F1Setup", b"Notifying connection drop")):
            return
        line = ANSI.sub("", raw.decode(errors="replace")).strip()
        if "E2 Setup procedure successful." in line:
            self._state("e2", "registered", "ric", "E2_REGISTERED " + self._identity() + " evidence=e2_setup_success")
        elif re.search(r"E2 Setup procedure (?:failed|aborted)\.", line):
            self._state("e2", "failed", "ric", "E2_REGISTRATION_FAILED " + self._identity())
        elif ("E2AP:" in line or "E2:" in line) and "Notifying connection drop to upper layers" in line:
            self._state("e2", "disconnected", "ric", "E2_DISCONNECTED " + self._identity())
        f1 = re.search(r"\b(Rx|Tx) PDU du=(\d+)[^:\r\n]*:\s*F1Setup(Request|Response|Failure)\b", line)
        if self.spec.name == "cu" and f1:
            direction, du, kind = f1.groups()
            if direction == "Rx" and kind == "Request":
                self._state("f1:" + du, "requested", "cu", f"F1_REGISTER_RECEIVED node=DU{du} du_id={du}")
            elif direction == "Tx" and kind == "Response":
                self._state("f1:" + du, "registered", "cu", f"F1_DU_REGISTERED node=DU{du} du_id={du} evidence=f1_setup_response_tx")
            elif direction == "Tx" and kind == "Failure":
                self._state("f1:" + du, "failed", "cu", f"F1_REGISTRATION_FAILED du_id={du}")
        elif self.spec.name in ("du1", "du2") and f1 and f1[1] == "Rx":
            if f1[3] == "Response":
                self.protocol["f1"] = "registered"
            elif f1[3] == "Failure":
                self._state("f1", "failed", "cu", "F1_REGISTRATION_FAILED " + self._identity())
        if self.spec.name in ("du1", "du2") and "F1-C:" in line and "Notifying connection drop to upper layers" in line:
            self._state("f1", "disconnected", "cu", "F1_DU_DISCONNECTED " + self._identity())

    def _event(self, name, line):
        try:
            self.events.put_nowait((name, line))
        except queue.Full:
            pass  # Full console log remains on disk; UI must not block readers.

    def _read(self):
        pending = b""
        try:
            while True:
                if self.native:
                    self.native.poll()
                if not select.select([self.master], [], [], 0.1)[0]:
                    continue
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
            if self.native:
                try:
                    self.native.poll()
                except OSError as exc:
                    self.error = str(exc)
                self.native.close()
            self.stream.close()
            self.finished.set()

    def ready(self):
        return all(marker in self.seen for marker in self.spec.markers)

    def write(self, command):
        if self.process.poll() is not None:
            raise Fault(self.spec.name.upper() + " is no longer running")
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

    def __init__(self, command, identity, dus=("du1", "du2")):
        self.command, self.identity, self.dus = command, identity, dus

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
            profiles = [[imsi, dnn] for name, imsi, dnn in (
                ("du1", "001010000000101", "internet"), ("du2", "001010000000102", "internet2"))
                if name in self.dus]
            code += """
const s=db.getSiblingDB('open5gs').subscribers;
for (const [imsi,dnn] of PROFILES) {
 const rows=s.find({imsi},{_id:0,slice:1}).toArray();
 const sessions=rows.length===1 ? (rows[0].slice||[]).filter(x=>x.sst===1)
   .flatMap(x=>x.session||[]).filter(x=>x.name===dnn&&x.type===1) : [];
 if(sessions.length!==1) { print('Invalid subscriber/session: '+imsi); quit(1); }
}
""".replace("PROFILES", json.dumps(profiles))
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
        for name in self.dus:
            suffix = int(name[-1])
            subnet = "10.45" if suffix == 1 else "10.46"
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
        nodes = sum(name in ready for name in ("cu", *self.dus))
        if sum(local == 36421 for local, peer in established) < nodes:
            raise Fault("RIC E2 association missing")
        if "cu" in ready and not any(peer == 38412 for local, peer in established):
            raise Fault("CU N2 association missing")
        dus = sum(name in ready for name in self.dus)
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
        self.dus = du_names(args)
        self.order = service_order(args)
        self.expected_subscriptions = 1 + len(self.dus)
        self.gain_target = self.dus[-1]
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
        self.down_seen = set()
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
        connections = self.connection_status()
        value = dict(supervisor="falcon-spark-auto", pid=os.getpid(), start_ticks=start_ticks(os.getpid()),
                     profile=profile_name(self.args), gain_target=self.gain_target,
                     script=str(Path(__file__).resolve()), phase=self.phase, reason=self.reason,
                     ready=sorted(self.ready), failed=self.failed, cleanup_errors=self.cleanup_errors,
                     core_managed=self.core_managed, mongo_preserved=True,
                     processes={name: dict(pid=child.process.pid, exit_code=child.process.poll(),
                         ready=name in self.ready, console=str(child.path),
                         native_log=str(child.spec.native_log) if child.spec.native_log else None,
                         protocol=dict(child.protocol)) for name, child in self.children.items()},
                     registrations=connections["xapp"]["registered_apps"],
                     connections=connections, health_failures=self.health_failures)
        try:
            atomic_json(self.directory / "status.json", value)
        except OSError:
            self.io_failure("Controller status file unavailable")
        return value

    def connection_status(self):
        def running(name):
            child = self.children.get(name)
            return child is not None and child.process.poll() is None

        def state(name, key):
            child = self.children.get(name)
            if child is None:
                return "not_started"
            if not running(name):
                return "down"
            return child.protocol.get(key, "waiting")

        ric = self.children.get("ric")
        nodes = {name: state(name, "e2") for name in ("cu", *self.dus)}
        if ric is not None and not running("ric"):
            nodes = {name: "down" for name in nodes}
        cu = self.children.get("cu")
        dus = {}
        for name in self.dus:
            default_id = name[-1]
            du = self.children.get(name)
            du_id = str(du.spec.du_id or default_id) if du else default_id
            current = cu.protocol.get("f1:" + du_id, "waiting") if cu else "not_started"
            if (du is not None and not running(name)) or (cu is not None and not running("cu")):
                current = "down"
            elif du and du.protocol.get("f1") in ("disconnected", "failed"):
                current = du.protocol["f1"]
            elif du and du.protocol.get("f1") == "registered" and current == "waiting":
                current = "registered"
            dus[name] = current
        xapp = self.children.get("xapp")
        e42 = state("xapp", "e42")
        if ric and not running("ric"):
            e42 = "down"
        elif ric and xapp and ric.protocol.get("e42:" + str(xapp.xapp_id)) == "disconnected":
            e42 = "disconnected"
        return dict(
            ric=dict(e2_nodes=nodes, registered_e2_nodes=sum(s == "registered" for s in nodes.values()),
                     xapp=e42, xapp_id=xapp.xapp_id if xapp else None),
            cu=dict(dus=dus, registered_dus=sum(s == "registered" for s in dus.values())),
            xapp=dict(ric=e42, available_e2_nodes=xapp.available_e2_nodes if xapp else None,
                      subscribed_e2_nodes=xapp.subscriptions if running("xapp") else 0 if xapp else None,
                      kpm_subscriptions=xapp.subscriptions if running("xapp") else 0 if xapp else None,
                      broker=("ready" if xapp.broker_ready else "waiting") if running("xapp") else "down" if xapp else "not_started",
                      registered_apps=len(xapp.apps) if running("xapp") else 0))

    def show_status(self):
        value = self.snapshot()
        links = value["connections"]
        def process(name):
            child = self.children.get(name)
            return "not_started" if child is None else "running" if child.process.poll() is None else "down"
        def count(number):
            return "unknown" if number is None else str(number)
        health = "degraded" if self.health_failures else "ok" if self.core_ready else "pending"
        self.say(f"[STATUS] phase={self.phase} health={health}")
        ric, cu, xapp = links["ric"], links["cu"], links["xapp"]
        node_states = " ".join(f"{name.upper()}={state}" for name, state in ric["e2_nodes"].items())
        du_states = " ".join(f"{name.upper()}={state}" for name, state in cu["dus"].items())
        self.say(f"[ric] process={process('ric')} E2 nodes registered={ric['registered_e2_nodes']}/{self.expected_subscriptions} ({node_states}); xApp={ric['xapp']} id={ric['xapp_id'] or '-'}")
        self.say(f"[cu] process={process('cu')} RIC={ric['e2_nodes']['cu']}; DUs registered={cu['registered_dus']}/{len(self.dus)} ({du_states})")
        for name in self.dus:
            child = self.children.get(name)
            backend = "cpu"
            if self.args.cuda:
                state = "not_started" if child is None else "down" if child.process.poll() is not None else child.protocol.get("cuda_pusch", "waiting")
                backend = "cuda_" + state
            self.say(f"[{name}] process={process(name)} RIC={ric['e2_nodes'][name]} CU={cu['dus'][name]} uplink={backend}")
        self.say(f"[xapp] process={process('xapp')} RIC={xapp['ric']}; E2 nodes subscribed={count(xapp['subscribed_e2_nodes'])}; KPM subscriptions={count(xapp['kpm_subscriptions'])}; broker={xapp['broker']} apps registered={xapp['registered_apps']}")

    def request_stop(self, reason):
        if not self.stop_event.is_set():
            self.reason = reason
        self.stop_event.set()

    def check_children(self):
        if self.stop_event.is_set():
            raise Stopping()
        for name, child in self.children.items():
            if child.process.poll() is not None:
                if name not in self.down_seen:
                    self.down_seen.add(name)
                    self.say(f"[{name}] DOWN exit_code={child.process.returncode}; stopping managed testbed")
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
            if self.health_failures:
                self.say("[HEALTH RECOVERED] Infrastructure probes passed")
            self.health_failures = 0
        self.snapshot()

    def drain_events(self):
        while True:
            try:
                name, line = self.events.get_nowait()
            except queue.Empty:
                break
            self.say(f"[{name}] {line}")

    def pump(self):
        self.drain_events()
        self.check_children()
        self.health()

    def wait(self, label, condition, timeout=None):
        started = time.monotonic()
        deadline = started + (self.args.startup_timeout if timeout is None else timeout)
        next_update = started + 5
        last = "not ready"
        while True:
            self.pump()
            try:
                complete = condition()
            except Stopping:
                raise
            except Exception as exc:
                last = str(exc)
                complete = False
            if complete:
                # The condition can become true during a transport probe.
                # Print its confirmation events before READY or the next START.
                self.drain_events()
                self.check_children()
                return
            now = time.monotonic()
            if now >= deadline:
                raise Fault(f"{label} startup timed out: {last}")
            if now >= next_update:
                self.say(f"[WAIT] {label} ({now - started:.0f}s): {last}")
                next_update = now + 5
            self.stop_event.wait(0.1)

    def service_ready(self, name):
        child = self.children[name]
        if not child.ready():
            missing = [marker for marker in child.spec.markers if marker not in child.seen]
            raise Fault(name + " awaiting startup output: " + ", ".join(missing))
        missing = [f"{key}={child.protocol.get(key, 'waiting')}" for key in child.spec.required_protocol
                   if child.protocol.get(key) != "registered"]
        if "f1" in child.spec.required_protocol and child.spec.du_id is not None:
            cu = self.children.get("cu")
            state = cu.protocol.get("f1:" + str(child.spec.du_id), "waiting") if cu else "not_started"
            if state != "registered":
                missing.append("CU F1=" + state)
        if missing:
            raise Fault(name + " awaiting registration: " + ", ".join(missing))
        self.host.transport_check(self.ready | {name})
        return True

    def input_command(self, line):
        line = line.strip()
        if line in ("stop", "quit", "exit"):
            self.request_stop("operator stop")
        elif line == "status":
            self.show_status()
        elif line in ("help", "?"):
            self.say("Commands: status | tx_gain 0 VALUE | rx_gain 0 VALUE | stop; Ctrl+C stops the testbed.")
        else:
            match = re.fullmatch(r"(tx_gain|rx_gain)\s+0\s+(\d+(?:\.\d+)?)", line)
            if not match:
                self.say(f"[INPUT] Use status, stop, tx_gain 0 VALUE or rx_gain 0 VALUE ({self.gain_target.upper()} only).")
                return
            # B210 single-channel hardware ranges. Native DU/UHD still validates.
            limit = 89.75 if match[1] == "tx_gain" else 76.0
            gain = float(match[2])
            if not math.isfinite(gain) or not 0 <= gain <= limit:
                self.say(f"[INPUT] {match[1]} must be within 0..{limit} dB.")
                return
            if self.gain_target not in self.ready:
                self.say(f"[INPUT] {self.gain_target.upper()} is not ready.")
                return
            self.children[self.gain_target].write(line)
            self.say(f"[{self.gain_target.upper()} INPUT] " + line)

    def execute(self, services, interactive=True):
        old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        for sig in old_handlers:
            signal.signal(sig, lambda number, frame: self.request_stop(signal.Signals(number).name))
        try:
            self.say("[DATABASE] Checking MongoDB and subscriber profiles for "
                     + ", ".join("UE" + name[-1] for name in self.dus))
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
            self.drain_events()
            self.show_status()
            self.say("[RUNNING] Waiting for MPTCP registration; UE/KPM/client absence is not a component failure.")
            self.say(f"Commands: status | tx_gain 0 VALUE | rx_gain 0 VALUE | stop. Gains control {self.gain_target.upper()}; Ctrl+C stops all managed services.")
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
            if child.deletions != self.expected_subscriptions:
                self.cleanup_errors.append(f"xapp: {child.deletions}/{self.expected_subscriptions} E2 delete responses; cleanup unverified")
            summary = self.directory / "publisher.json"
            try:
                value = json.loads(summary.read_text())
                if value["status"] != "passed" or any(value["counters"].get(k, 0) for k in ("active_connections", "active_registrations")):
                    raise ValueError("failed publisher/active connections")
            except (OSError, ValueError, KeyError) as exc:
                self.cleanup_errors.append("xapp final summary: " + str(exc))

    def cleanup(self):
        for name in reversed(self.order):
            try:
                self.stop_child(name)
            except Exception as exc:
                self.cleanup_errors.append(name + ": " + str(exc))
            self.drain_events()
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


def radio_gains(config, label):
    gains = tuple(config["ru_sdr"].get(key) for key in ("tx_gain", "rx_gain"))
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value < 0 for value in gains):
        raise Fault(f"{label}: TX/RX gains must be finite nonnegative numbers in the deployed YAML")
    return gains


def check_files(args):
    ocudu = args.ocudu.resolve()
    if args.du2_config and not args.du2_wired20_only:
        raise Fault("--du2-config requires the wired DU2 profile")
    if args.du1_config and args.du2_wired20_only:
        raise Fault("The wired DU2 profile does not use --du1-config")
    sources = {
        "cu.yml": ocudu / "configs/cu.yml",
        "cu_identity_e2.yml": ROOT / "configs/ocudu/cu_identity_e2.yml",
        "local.json": ROOT / "configs/ue_identity" / ("fr1_ue1.json" if args.du1_only else "local.json"),
        "subscriptions.json": ROOT / "configs/ue_identity/subscriptions.json",
    }
    if args.du2_wired20_only:
        sources["du2.yml"] = (args.du2_config.resolve() if args.du2_config else
                              ROOT / "configs/ocudu/dual_fr1/du2_b210_n78_20mhz_wired.yml")
    else:
        sources["du1.yml"] = args.du1_config.resolve() if args.du1_config else ocudu / "configs/du1_b210_n78_3660mhz.yml"
    if not args.du1_only and not args.du2_wired20_only:
        sources.update({"du2.yml": ocudu / "configs/du2_b210_n78_40mhz.yml",
                        "du2_e2.yml": ocudu / "configs/du2_flexric.yml"})
    if args.cuda:
        sources["cuda_uplink.yml"] = ROOT / "configs/ocudu/cuda_uplink.yml"
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
    if args.cuda:
        check_cuda_artifact(args)
    for name in ("docker", "systemctl", "ip", "ss", "stdbuf", "bash", "gcc"):
        if not shutil.which(name):
            raise Fault("Missing command: " + name)
    spec = importlib.util.spec_from_file_location("falcon_auto_config", ROOT / "scripts/dual_fr1/check_config.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    cu = checker.merge(checker.load(sources["cu.yml"]), checker.load(sources["cu_identity_e2.yml"]))
    du1 = checker.load(sources["du1.yml"]) if "du1.yml" in sources else None
    du2 = checker.load(sources["du2.yml"]) if "du2.yml" in sources else None
    if "du2_e2.yml" in sources:
        du2 = checker.merge(du2, checker.load(sources["du2_e2.yml"]))
    dus = [(label, config) for label, config in (("du1", du1), ("du2", du2)) if config is not None]
    # Auto mode overrides log filenames into its private run directory. Old
    # manual log ownership must not invalidate an otherwise valid offline check.
    for label, config in dus:
        config["log"]["filename"] = str(args.run_root / f"falcon-auto-check-{os.getpid()}-{label}.log")
    errors, _ = checker.validate(cu, du1, du2, du2_wired20=args.du2_wired20_only)
    run_identity(args, sources["local.json"])
    for label, config in dus:
        radio_gains(config, label)
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
    if supervisor.args.du2_wired20_only:
        atomic_json(directory / "local.json", run_identity(supervisor.args, sources["local.json"]))
        hashes[str(directory / "local.json")] = file_sha256(directory / "local.json")
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
                 du_binary(supervisor.args)):
        hashes[str(path)] = file_sha256(path)
    revisions = {}
    for path in (ROOT, supervisor.args.ocudu, supervisor.args.flexric):
        # The controller runs as root, while these user-owned repositories do
        # not. Trust only this explicit path for these read-only git commands.
        git = ["git", "-c", "safe.directory=" + str(path), "-C", path]
        revisions[str(path)] = dict(head=supervisor.command([*git, "rev-parse", "HEAD"]).strip(),
                                   status=supervisor.command([*git, "status", "--short"]).splitlines())
    atomic_json(directory / "manifest.json", dict(profile=profile_name(supervisor.args),
                                                  hashes=hashes, revisions=revisions))

    return service_plan(supervisor.args, directory)


def du_binary(args):
    return (args.cuda_build if args.cuda else args.ocudu / "build-integrated") / "apps/du_split_8/odu"


def check_cuda_artifact(args):
    binary = du_binary(args)
    cache = args.cuda_build / "CMakeCache.txt"
    if not binary.is_file() or not os.access(binary, os.X_OK) or not cache.is_file():
        raise Fault("Missing CUDA DU build; run scripts/cuda_ldpc/build.py first")
    values = cache.read_text()
    if not re.search(r"^ENABLE_CUDA:BOOL=ON$", values, re.M) or not re.search(
            r"^CUDA_ACCEL_FOUND:BOOL=TRUE$", values, re.M):
        raise Fault("Selected DU build does not have CUDA acceleration enabled")
    try:
        validation = json.loads((args.cuda_build / "falcon-cuda-validation.json").read_text())
        if (validation["status"] != "passed" or validation["du_sha256"] != file_sha256(binary)
                or validation["overlay_sha256"] != file_sha256(ROOT / "configs/ocudu/cuda_uplink.yml")):
            raise ValueError("validation does not match the DU binary or uplink overlay")
    except (OSError, ValueError, KeyError) as exc:
        raise Fault("CUDA DU validation missing or stale; run scripts/cuda_ldpc/build.py: " + str(exc)) from exc


def service_plan(args, directory):
    ocudu = args.ocudu
    ran = ocudu / "build-integrated/apps"
    identity = json.loads((directory / "local.json").read_text())
    gnb_id = str(identity["cu"]["gnb_id"])
    du_args = ["-c", directory / "cuda_uplink.yml"] if args.cuda else []
    cuda_markers = ("Resident LDPC decoder enabled for PUSCH acceleration",) if args.cuda else ()
    e2_marker = "E2: Connection" if args.cuda else "E2AP: Connection"
    services = [
        Service("ric", ["stdbuf", "-oL", "-eL", args.ric, "-c", directory / "ric.conf"], ROOT,
                ("[NEAR-RIC]: Loading SM ID = 2 with def = ORAN-E2SM-KPM",)),
        # OCUDU's stdout sink flushes every entry. Its file sink buffers entries
        # without a periodic flush, so an idle CU can hide E2 success until DUs
        # generate more logs. Archive the live stream in NAME.console.log.
        Service("cu", [ran / "cu/ocu", "-c", directory / "cu.yml", "-c", directory / "cu_identity_e2.yml",
                       "log", "--filename", "stdout"], ocudu,
                ("==== CU started ===", "N2: Connection", "E2AP: Connection"),
                gnb_id=gnb_id, required_protocol=("e2",)),
    ]
    for name in du_names(args):
        overlay = ["-c", directory / "du2_e2.yml"] if name == "du2" and not args.du2_wired20_only else []
        services.append(Service(name, [du_binary(args), "-c", directory / (name + ".yml"),
                        *overlay, *du_args, "log", "--filename", "stdout"], ocudu,
                ("==== DU started ===", "F1-C: Connection to CU-CP", e2_marker) + cuda_markers,
                gnb_id=gnb_id,
                du_id=str(yaml.safe_load((directory / (name + ".yml")).read_text())["gnb_du_id"]),
                required_protocol=("e2", "f1")))
    services.append(Service("xapp", [sys.executable, "-B", ROOT / "scripts/ue_identity/xapp_ue_identity.py",
                         "--collector", directory / "collector", "--config", directory / "local.json",
                         "--e2-config", directory / "xapp.conf", "--publish-config", directory / "subscriptions.json",
                         "--fresh-only", "--duration", "0", "--publisher-summary", directory / "publisher.json"], ROOT,
                ("SUBSCRIPTION_READY host=127.0.0.1 port=8765 profile=du27_bound_v1 source=e2",
                 f"identity collector: {1 + len(du_names(args))} KPM subscriptions, duration=0"),
                required_protocol=("e42",)))
    return services


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
    selection = value.add_mutually_exclusive_group()
    selection.add_argument("--du1-only", action="store_true", help="FR1 profile: only DU1/UE1, two E2 subscriptions and DU1 gain control")
    selection.add_argument("--du2-wired20-only", action="store_true",
                           help="wired profile: only DU2/UE2, direct n78 / 20 MHz, two E2 subscriptions and DU2 gain control")
    value.add_argument("--du1-config", type=Path, metavar="YAML",
                       help="Select a full DU1 YAML for a comparison run; validated and copied into the run directory")
    value.add_argument("--du2-config", type=Path, metavar="YAML",
                       help="Select a full wired20 DU2 YAML for a comparison run; requires the wired DU2 profile")
    value.add_argument("--cuda", action="store_true", help="use the validated CUDA uplink DU binary/overlay for selected DUs")
    value.add_argument("--cuda-build", type=Path, default=Path("/home/nyu/ocudu/build-cuda-upstream"))
    value.add_argument("--run-root", type=Path, default=Path("/tmp"))
    value.add_argument("--startup-timeout", type=float, default=120)
    value.add_argument("--build-timeout", type=float, default=180)
    value.add_argument("--stop-timeout", type=float, default=30)
    value.add_argument("--health-interval", type=float, default=5)
    value.add_argument("--health-failures", type=int, default=3)
    value.add_argument("--no-input", action="store_true", help="signals/status files only; no DU gain command input")
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
        if not any(Path(arg.decode(errors="replace")).name in (
                "spark_auto.py", "spark_fr1_auto.py", "spark_wired_du2_auto.py") for arg in command):
            raise Fault("PID is not a spark_auto controller; no signal sent")
        os.kill(pid, signal.SIGINT)
        print("Normal shutdown requested; inspect the controller or status.json for completion.")
        return 0
    args.ocudu, args.flexric, args.ric = args.ocudu.resolve(), args.flexric.resolve(), args.ric.resolve()
    args.run_root = args.run_root.resolve()
    args.cuda_build = args.cuda_build.resolve()
    sources = check_files(args)
    if args.check:
        gains = []
        for name in du_names(args):
            label = name.upper()
            config = yaml.safe_load(sources[label.lower() + ".yml"].read_text())
            tx, rx = radio_gains(config, label)
            gains.append(f"{label} {tx:g}/{rx:g}")
        print("PASS: offline configs/artifacts; " + ", ".join(gains) + "; no services/radios started.")
        if args.du1_config:
            print("DU1 configuration:", sources["du1.yml"])
        if args.du2_wired20_only:
            print("DU2 wired20 configuration:", sources["du2.yml"])
        if args.cuda:
            print("PASS: validated CUDA DU selected for " + " and ".join(name.upper() for name in du_names(args)) + "; uplink PUSCH/LDPC required.")
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
    prefix = ("falcon-spark-wired-du2-auto-" if args.du2_wired20_only else
              "falcon-spark-fr1-auto-" if args.du1_only else "falcon-spark-auto-")
    directory = Path(tempfile.mkdtemp(prefix=prefix, dir=args.run_root))
    print("Spark auto run directory:", directory, flush=True)
    for name in du_names(args):
        print(name.upper() + " configuration:", sources[name + ".yml"], flush=True)
    supervisor = Supervisor(args, directory)
    old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    for sig in old_handlers:
        signal.signal(sig, lambda number, frame: supervisor.request_stop(signal.Signals(number).name))
    try:
        supervisor.snapshot()
        identity = run_identity(args, sources["local.json"])
        supervisor.host = Host(supervisor.command, identity, du_names(args))
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
