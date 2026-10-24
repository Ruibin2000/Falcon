#!/usr/bin/env python3
"""Connect and verify one laptop UE, then hold until Ctrl+C shuts that UE down."""

import argparse
import contextlib
import csv
from datetime import datetime, timezone
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time

import reset_ue_network as reset


ROLES = {
    1: dict(imei="863305041978437", imsi="001010000000101", apn="internet",
            pool="10.45.0.0/16", server="10.45.0.1", table=151,
            priorities=(10151, 10152, 10153, 10154), block=20151,
            pci=1, nci=0x66C000, ssb=643680, carrier=644000, label="FR1"),
    2: dict(imei="863305041980706", imsi="001010000000102", apn="internet2",
            pool="10.46.0.0/16", server="10.46.0.1", table=152,
            priorities=(10161, 10162, 10163, 10164), block=20152,
            pci=2, nci=0x66C001, ssb=639648, carrier=640000, label="FR3"),
}
# FR1/FR3 are the demo path labels; both current radio configurations use n78.
NETWORK_LOCK = "/run/lock/falcon-ue-connect.lock"


class CellError(ValueError):
    """No acceptable live registration/serving-cell evidence."""


class ATCommandError(CellError):
    """Keep a rejected command's raw reply and vendor code as evidence."""
    def __init__(self, command, reply):
        self.command, self.reply = command, reply
        match = re.search(r"\+CME ERROR:\s*(\d+)", reply)
        self.cme_code = int(match[1]) if match else None
        super().__init__(f"No successful reply to AT command {command}: {reply.strip() or 'timeout/closed port'}")


class StopRequested(KeyboardInterrupt):
    def __init__(self, signum):
        self.signum = signum
        super().__init__(signal.Signals(signum).name)


class StopSignals:
    """Cancel on the first stop signal; subsequent signals cannot re-enter cleanup."""
    def __init__(self):
        self.signum = None

    def handle(self, signum, frame):
        if self.signum is None:
            self.signum = signum
            raise StopRequested(signum)

    def __enter__(self):
        self.originals = {sig: signal.signal(sig, self.handle) for sig in (signal.SIGINT, signal.SIGTERM)}
        return self

    def __exit__(self, *exception):
        for sig, handler in self.originals.items():
            signal.signal(sig, handler)


@contextlib.contextmanager
def ignore_stop_signals():
    # Ignored dispositions also protect exec'ed cleanup children from another
    # terminal Ctrl+C, which is sent to the whole foreground process group.
    original = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for sig, handler in original.items():
            signal.signal(sig, handler)


@contextlib.contextmanager
def role_lock(ue):
    # Reuse the watcher lock name so existing watcher versions also exclude a
    # new one-shot launcher for the same modem.
    with open(f"/run/lock/falcon-ue{ue}-reconnect.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f"UE{ue} already has an active connection or reconnect script; stop it first") from None
        yield


@contextlib.contextmanager
def network_lock(*, shared=False, path=None):
    """Protect kernel network transactions, never modem calls or ping waits."""
    with open(path or NETWORK_LOCK, "a") as lock:
        mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        try:
            fcntl.flock(lock, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            status("Waiting for a host network update to finish ...")
            fcntl.flock(lock, mode)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def interruption(error):
    signum = getattr(error, "signum", signal.SIGINT)
    reason = ("Interrupted by user (Ctrl+C)" if signum == signal.SIGINT else
              f"Stopped by {signal.Signals(signum).name}")
    return signum, reason


def require(condition, message):
    if not condition:
        raise ValueError(message)


def status(message, *, detail=None, error=False, end="\n"):
    """Keep progress and actionable failures visible while details go to the log."""
    stream = sys.stderr if error else sys.stdout
    if isinstance(stream, Tee):
        stream.show(message + end, None if detail is None else detail + end)
    else:
        print(detail if detail is not None else message, file=stream, end=end, flush=True)


def read(*command):
    return subprocess.check_output(command, text=True, stderr=subprocess.PIPE,
                                   timeout=75, start_new_session=True, env=dict(os.environ, LC_ALL="C"))


def change(*command):
    print("+ " + shlex.join(command), flush=True)
    completed = subprocess.run(command, text=True, capture_output=True, timeout=75,
                               start_new_session=True, env=dict(os.environ, LC_ALL="C"))
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", file=sys.stderr)
    completed.check_returncode()


def kv(*command):
    return {key.strip(): value.strip() for key, value in
            (line.split(":", 1) for line in read(*command).splitlines() if ":" in line)}


def values(info, name):
    pattern = re.compile(re.escape(name) + r"\.value\[(\d+)\]")
    indexed = [(int(match[1]), value) for key, value in info.items()
               if (match := pattern.fullmatch(key))]
    return [value for _, value in sorted(indexed)] if indexed else [info.get(name, "")]


def ports(info):
    return set(re.findall(r"([A-Za-z0-9_.-]+)\s+\(net\)",
                          "\n".join(values(info, "modem.generic.ports"))))


def number(value):
    return int(value) if str(value).isdigit() else reset.table_aliases().get(value)


def host(value, address):
    return value in (address, address + "/32")


def network_driver(interface):
    return (Path("/sys/class/net") / interface / "device/driver").resolve().name


def network_device(interface):
    return usb_parent(Path("/sys/class/net") / interface / "device")


def ip_json(*args):
    try:
        return json.loads(read("ip", "-j", "-4", *args))
    except subprocess.CalledProcessError as error:
        if args[:3] == ("route", "show", "table") and "FIB table does not exist" in (error.stderr or ""):
            return []
        raise


def mm_cell_records(info):
    """GetCellInfo -K reports an array of comma-separated cell descriptions."""
    records = []
    for description in values(info, "modem.generic.cell-info"):
        fields = {}
        for field in description.split(","):
            if ":" in field:
                key, value = field.split(":", 1)
                fields[key.strip().lower().replace(" ", "-")] = value.strip()
        if fields:
            records.append(fields)
    return records


def mm_serving_cell(info):
    records = [cell for cell in mm_cell_records(info)
               if cell.get("serving") == "yes" and cell.get("cell-type") == "5gnr"]
    if len(records) != 1:
        raise CellError("GetCellInfo must report exactly one serving 5GNR cell (neighbors do not count)")
    cell = records[0]
    try:
        # ModemManager documents ci, physical-ci and tac as hexadecimal strings.
        result = dict(pci=int(cell["physical-ci"], 16), nci=int(cell["ci"], 16),
                      source="ModemManager.GetCellInfo")
        if cell.get("operator-id") not in (None, "--"):
            result["plmn"] = cell["operator-id"]
        if cell.get("tac") not in (None, "--"):
            result["tac"] = int(cell["tac"], 16)
        if cell.get("nrarfcn") not in (None, "--"):
            result["arfcn"] = int(cell["nrarfcn"])
        return result
    except (KeyError, ValueError) as error:
        raise CellError(f"Incomplete or invalid serving-cell identifiers: {error}") from None


def qeng_serving_cell(reply):
    lines = [line.partition(":")[2].strip() for line in reply.splitlines()
             if line.strip().startswith("+QENG:") and '"servingcell"' in line]
    if len(lines) != 1:
        raise CellError("AT+QENG did not return exactly one servingcell record")
    try:
        fields = next(csv.reader(lines, skipinitialspace=True))
        if fields[1] not in ("NOCONN", "CONNECT") or fields[2] != "NR5G-SA":
            raise CellError("The modem is not camped on an NR5G-SA serving cell")
        return dict(pci=int(fields[7]), nci=int(fields[6], 16), tac=int(fields[8], 16),
                    arfcn=int(fields[9]), band=int(fields[10]), plmn=fields[4] + fields[5],
                    source='AT+QENG="servingcell" (read only)')
    except (IndexError, ValueError) as error:
        raise CellError(f"Invalid NR5G-SA QENG reply: {error}") from None


def usb_parent(path):
    for parent in (path.resolve(), *path.resolve().parents):
        if (parent / "idVendor").is_file() and (parent / "idProduct").is_file():
            return parent
    raise CellError(f"Cannot establish USB ownership for {path}")


def verify_at_port(at_port, net_ports):
    path = Path(at_port).resolve()
    if path.parent != Path("/dev") or not re.fullmatch(r"tty(?:USB|ACM)\d+", path.name):
        raise CellError("--at-port must resolve to a USB serial device under /dev")
    owner = usb_parent(Path("/sys/class/tty") / path.name / "device")
    owners = {usb_parent(Path("/sys/class/net") / name / "device") for name in net_ports}
    if owners != {owner}:
        raise CellError("The requested AT port does not belong to the selected modem's USB device")
    for process in Path("/proc").glob("[0-9]*/fd"):
        try:
            if any(fd.resolve() == path for fd in process.iterdir()):
                raise CellError(f"AT port {path} is busy; close minicom/the port owner before retrying")
        except (FileNotFoundError, PermissionError):
            continue
    return path


def at_reply(fd, command):
    termios.tcflush(fd, termios.TCIFLUSH)
    os.write(fd, (command + "\r").encode("ascii"))
    result = b""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            break
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        result += chunk
        if len(result) > 16384:
            raise CellError("Unexpectedly large AT response")
        if re.search(rb"(?:^|[\r\n])(?:OK|ERROR|\+CME ERROR[^\r\n]*)[\r\n]", result):
            break
    reply = result.decode("ascii", errors="replace")
    if not re.search(r"(?:^|[\r\n])OK(?:[\r\n]|$)", reply):
        raise ATCommandError(command, reply)
    return reply


@contextlib.contextmanager
def serial_modem(at_port, info, role, query=None):
    """Open an owned, idle AT port and verify both identities before yielding."""
    query = query or at_reply
    path = verify_at_port(at_port, ports(info))
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    original = None
    exclusive = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, termios.TIOCEXCL)
        exclusive = True
        original = termios.tcgetattr(fd)
        attrs = termios.tcgetattr(fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        for command, expected in (("AT+CGSN", role["imei"]), ("AT+CIMI", role["imsi"])):
            lines = query(fd, command).replace("\r", "\n").splitlines()
            if expected not in [line.strip() for line in lines]:
                raise CellError(f"Serial identity mismatch from {command}; no configuration sent")
        yield fd
    finally:
        try:
            if original is not None:
                termios.tcsetattr(fd, termios.TCSANOW, original)
        finally:
            if exclusive:
                with contextlib.suppress(OSError):
                    fcntl.ioctl(fd, termios.TIOCNXCL)
            os.close(fd)


def serial_cell(at_port, info, role):
    with serial_modem(at_port, info, role) as fd:
        return qeng_serving_cell(at_reply(fd, 'AT+QENG="servingcell"'))


class Connection:
    def __init__(self, ue, at_port=None, registration_timeout=45, ping_count=5,
                 modem_cache=None, network_lock_path=None):
        self.ue, self.role = ue, ROLES[ue]
        self.at_port, self.registration_timeout = at_port, registration_timeout
        self.ping_count = ping_count
        self.modem = self.identity = None
        self.device = None
        self.modem_cache = modem_cache if modem_cache is not None else {}
        self.network_lock_path = network_lock_path
        self.inventory = []
        self.stage = "preflight"
        self.result = dict(ue=ue, path=self.role["label"], status="started",
                           started_at=datetime.now(timezone.utc).isoformat())

    @contextlib.contextmanager
    def step(self, index, label, stage):
        self.stage = stage
        verbose = getattr(sys.stdout, "verbose", True)
        status(f"[{index}/9] {label} ...", end="\n" if verbose else " ")
        try:
            yield
        except KeyboardInterrupt:
            status(f"[{index}/9] {label} [CANCELLED]" if verbose else "[CANCELLED]")
            raise
        except BaseException:
            status(f"[{index}/9] {label} [FAIL]" if verbose else "[FAIL]")
            raise
        else:
            status(f"[{index}/9] {label} [OK]" if verbose else "[OK]")

    def discover(self):
        local = {address["local"] for device in ip_json("addr", "show")
                 for address in device.get("addr_info", [])}
        require(not local.intersection(role["server"] for role in ROLES.values()),
                "Spark service IP is local; run this script on the UE laptop")
        cached = self.modem_cache.get("selected")
        info = None
        if cached:
            self.modem, self.identity = cached
            try:
                info = kv("mmcli", "-m", self.modem, "-K")
            except subprocess.CalledProcessError as error:
                # Rediscover a removed object, but never query the other UE to
                # work around a slow or unresponsive selected modem.
                message = (str(error) + (error.stderr or "")).lower()
                if not any(word in message for word in ("couldn't find modem", "unknownobject", "does not exist")):
                    raise
            if info is not None and (info.get("modem.generic.equipment-identifier") != self.role["imei"]
                                     or info.get("modem.generic.device-identifier") != self.identity):
                info = None
            if info is not None:
                self.inventory = list(self.modem_cache.get("inventory", []))
                previous_ports = [item[2] for item in self.inventory if item[1] == self.role["imei"]]
                if previous_ports != [ports(info)]:
                    info = None
        if info is None:
            self.modem_cache.clear()
            paths = sorted(set(re.findall(r"/org/freedesktop/ModemManager1/Modem/\d+", read("mmcli", "-L"))))
            records = [(path, kv("mmcli", "-m", path, "-K")) for path in paths]
            matches = [(path, item) for path, item in records
                       if item.get("modem.generic.equipment-identifier") == self.role["imei"]]
            require(len(matches) == 1, "Expected IMEI must match exactly one current modem")
            self.modem, info = matches[0]
            self.identity = info.get("modem.generic.device-identifier")
            require(self.identity not in (None, "", "--"), "Missing current modem device identifier")
            self.inventory = [(path, item.get("modem.generic.equipment-identifier"), ports(item),
                               item.get("modem.generic.state")) for path, item in records]
        self.checked_modem()
        self.modem_cache.update(selected=(self.modem, self.identity), inventory=self.inventory)
        self.result.update(modem=self.modem, imei=self.role["imei"], imsi=self.role["imsi"],
                           apn=self.role["apn"], server=self.role["server"], table=self.role["table"])
        print(f"UE{self.ue} / {self.role['label']}: IMEI={self.role['imei']} IMSI={self.role['imsi']} modem={self.modem}")

    def checked_modem(self):
        info = kv("mmcli", "-m", self.modem, "-K")
        require(info.get("modem.generic.equipment-identifier") == self.role["imei"]
                and info.get("modem.generic.device-identifier") == self.identity,
                "Modem identity changed; stop before touching another device")
        sim = info.get("modem.generic.sim", "")
        require(re.fullmatch(r"/org/freedesktop/ModemManager1/SIM/\d+", sim), "No active SIM path")
        sim_info = kv("mmcli", "-i", sim, "-K")
        require(sim_info.get("sim.properties.active") == "yes"
                and sim_info.get("sim.properties.imsi") == self.role["imsi"], "Active SIM IMSI mismatch")
        self.device = info.get("modem.generic.physdev") or info.get("modem.generic.device")
        previous_ports = [item[2] for item in self.inventory if item[1] == self.role["imei"]]
        if previous_ports and previous_ports != [ports(info)]:
            self.modem_cache.pop("selected", None)
        self.inventory = [item for item in self.inventory if item[1] != self.role["imei"]]
        self.inventory.append((self.modem, self.role["imei"], ports(info), info.get("modem.generic.state")))
        self.modem_cache["inventory"] = self.inventory
        return info

    def network(self, *, shared=False):
        return network_lock(shared=shared, path=self.network_lock_path)

    @contextlib.contextmanager
    def host_update(self, bearer):
        """Compare the peer/management state only across our own kernel writes."""
        with self.network():
            before = self.surroundings(bearer)
            yield
            require(self.surroundings(bearer) == before,
                    "Management/other-UE configuration changed during host update")

    def clear_host(self, bearer):
        # Inventory was refreshed from this modem outside the network lock.
        # Host-only reset must not issue ModemManager queries under that lock.
        with self.host_update(bearer):
            self.host_preflight(bearer)
            reset.reset(self.ue, inventory=self.inventory)
            self.block(install=False)

    def verify_host_cleared(self, interface):
        pool = ipaddress.IPv4Network(self.role["pool"])
        require(not any(ipaddress.IPv4Address(address["local"]) in pool
                        for device in ip_json("addr", "show") for address in device.get("addr_info", [])),
                "Role IPv4 address remains after shutdown")
        require(not ip_json("route", "show", "table", str(self.role["table"]))
                and not any(rule.get("priority") in self.role["priorities"]
                            or number(rule.get("table")) == self.role["table"]
                            for rule in ip_json("rule", "show")), "Role routes/rules remain after shutdown")
        require(not any(route.get("dev") == interface for route in ip_json("route", "show", "table", "main")),
                "Role main-table route remains after shutdown")
        links = [link for link in json.loads(read("ip", "-j", "link", "show")) if link["ifname"] == interface]
        require(all(link.get("mtu") == 1500 and "UP" not in link.get("flags", []) for link in links),
                "Role WWAN is not DOWN / MTU 1500 after shutdown")
        self.block(install=False)

    def registered(self, enable):
        started = time.monotonic()
        deadline = started + (self.registration_timeout if enable else 0)
        print("Registration: querying current modem / active SIM status "
              f"(wait budget {self.registration_timeout if enable else 0}s; command timeout 75s)", flush=True)
        info = self.checked_modem()
        if info.get("modem.generic.state") == "disabled" and enable:
            change("mmcli", "-m", self.modem, "--enable")
            info = self.checked_modem()
        while True:
            snapshot = dict(state=info.get("modem.generic.state", "--"),
                            registration_state=info.get("modem.3gpp.registration-state", "--"),
                            packet_service_state=info.get("modem.3gpp.packet-service-state", "--"),
                            plmn=info.get("modem.3gpp.operator-code", "--"),
                            access_technologies=[v for v in values(info, "modem.generic.access-technologies") if v],
                            elapsed_seconds=round(time.monotonic() - started, 1))
            self.result["registration"] = snapshot
            description = (f"state={snapshot['state']} 3gpp={snapshot['registration_state']} "
                           f"packet={snapshot['packet_service_state']} PLMN={snapshot['plmn']} "
                           f"access={','.join(snapshot['access_technologies']) or '--'}")
            print(f"Registration: {description}; elapsed={snapshot['elapsed_seconds']:g}s", flush=True)
            if (info.get("modem.generic.state") in ("registered", "connecting", "connected")
                    and info.get("modem.3gpp.registration-state") in ("home", "roaming")):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CellError(f"Modem is not registered after {snapshot['elapsed_seconds']:g}s: {description}; "
                                "check serving cell, registration and serial configuration")
            delay = min(2, remaining)
            print(f"Registration: waiting {delay:g}s before the next modem / SIM query", flush=True)
            time.sleep(delay)
            print("Registration: querying current modem / active SIM status ...", flush=True)
            info = self.checked_modem()
        technologies = {token.strip().lower() for value in values(info, "modem.generic.access-technologies")
                        for token in value.split(",")}
        if info.get("modem.3gpp.operator-code") != "00101" or "5gnr" not in technologies or "lte" in technologies:
            raise CellError("Expected registered PLMN 00101 and NR SA access; current registration differs")
        return info

    def serving_cell(self):
        info = self.registered(enable=False)
        try:
            cell_info = kv("mmcli", "-m", self.modem, "--get-cell-info", "-K")
            cell = mm_serving_cell(cell_info)
        except (CellError, subprocess.SubprocessError) as error:
            if not self.at_port:
                raise CellError(f"Cannot prove the serving DU: {error}; use manual serial checks or --at-port") from None
            # A complete mismatching MM record is checked below, never overridden by AT.
            try:
                cell = serial_cell(self.at_port, info, self.role)
            except (OSError, termios.error) as serial_error:
                raise CellError(f"Read-only serial query failed: {serial_error}") from None
        expected = self.role
        if (cell["pci"] != expected["pci"] or cell["nci"] != expected["nci"]
                or cell.get("plmn", "00101") != "00101" or cell.get("tac", 7) != 7
                or cell.get("arfcn", expected["carrier"]) not in (expected["ssb"], expected["carrier"])
                or cell.get("band", 78) != 78):
            raise CellError(f"Serving cell mismatch: {json.dumps(cell, sort_keys=True)}")
        self.checked_modem()
        self.result["serving_cell"] = cell
        print(f"Serving cell PASS: PCI={cell['pci']} NCI={cell['nci']:X} ({cell['source']}); serial configuration skipped")
        return cell

    def bearer(self, connect=False):
        info = self.checked_modem()
        active = []
        for path in reset.bearer_paths(info):
            details = kv("mmcli", "-b", path, "-K")
            if details.get("bearer.status.connected") == "yes":
                active.append((path, details))
        require(len(active) <= 1, "Multiple connected bearers on selected modem; inspect their connection owners")
        if active:
            require(active[0][1].get("bearer.properties.apn") == self.role["apn"],
                    "A different APN is already connected; disconnect it explicitly before retrying")
        elif connect:
            self.checked_modem()
            change("mmcli", "-m", self.modem, "--simple-connect=" + f"apn={self.role['apn']},ip-type=ipv4")
            return self.bearer()
        else:
            raise ValueError("No connected bearer with the expected APN")
        path, details = active[0]
        require(details.get("bearer.status.suspended") == "no"
                and details.get("bearer.ipv4-config.method") == "static", "Bearer suspended or IPv4 is not static")
        source = str(ipaddress.IPv4Address(details.get("bearer.ipv4-config.address", "")))
        prefix = int(details.get("bearer.ipv4-config.prefix", "-1"))
        ipaddress.IPv4Interface(f"{source}/{prefix}")
        require(ipaddress.IPv4Address(source) in ipaddress.IPv4Network(self.role["pool"])
                and source != self.role["server"], "Bearer address is outside the expected UE pool")
        interface = details.get("bearer.status.interface", "")
        require(reset.WWAN.fullmatch(interface) and interface in ports(info), "Bearer WWAN is not owned by selected modem")
        mtu = int(details.get("bearer.ipv4-config.mtu", "0"))
        require(576 <= mtu <= 65535, "Bearer must report a valid IPv4 MTU in 576..65535; inspect mmcli -b")
        return dict(bearer=path, source=source, prefix=prefix, interface=interface, mtu=mtu)

    def block(self, install):
        role = self.role
        rules = ip_json("rule", "show")
        existing = [rule for rule in rules if rule.get("priority") == role["block"]]
        if not existing and install:
            change("ip", "-4", "rule", "add", "pref", str(role["block"]), "to", role["server"] + "/32", "unreachable")
            existing = [rule for rule in ip_json("rule", "show") if rule.get("priority") == role["block"]]
        require(len(existing) == 1 and self.owned_rule(existing[0], block=True),
                "Persistent Wi-Fi fallback block is missing, duplicated or occupied by another rule")

    def owned_rule(self, rule, block=False):
        allowed = {"priority", "src", "dst", "table", "action", "protocol", "flags"}
        if set(rule) - allowed or rule.get("flags") or not host(rule.get("dst"), self.role["server"]):
            return False
        source = rule.get("src", "all")
        if source != "all":
            try:
                if not ipaddress.IPv4Network(source, strict=False).subnet_of(ipaddress.IPv4Network(self.role["pool"])):
                    return False
            except ValueError:
                return False
        if block:
            return source == "all" and rule.get("action") == "unreachable" and "table" not in rule
        return ((number(rule.get("table")) == self.role["table"] and rule.get("action", "to_tbl") == "to_tbl")
                or (rule.get("action") == "unreachable" and "table" not in rule))

    def host_preflight(self, bearer):
        interface = bearer["interface"]
        require(network_driver(interface) == "qmi_wwan",
                "Expected a dedicated qmi_wwan interface; inspect its driver before configuration")
        require(self.device not in (None, "", "--"), "Missing selected modem physical device path")
        require(network_device(interface) == Path(self.device).resolve(),
                "WWAN physical device changed; rediscover modem ownership before host configuration")
        require(not any(interface in net_ports and imei != self.role["imei"]
                        for _, imei, net_ports, _ in self.inventory), "WWAN is shared with another modem")
        pool = ipaddress.IPv4Network(self.role["pool"])
        for device in ip_json("addr", "show"):
            for address in device.get("addr_info", []):
                in_pool = ipaddress.IPv4Address(address["local"]) in pool
                require(not in_pool or device["ifname"] == interface, "Role pool exists on another interface; inspect it manually")
                require(device["ifname"] != interface or in_pool, "Selected WWAN has another network's IPv4 address")
        require(not json.loads(read("ip", "-j", "-6", "route", "show", "default", "dev", interface)),
                "Selected WWAN has an IPv6 default route; inspect its connection owner")
        ssh_peer = os.environ.get("SSH_CONNECTION", "").split()
        if ssh_peer:
            routes = json.loads(read("ip", "-j", "route", "get", ssh_peer[0]))
            require(all(route.get("dev") != interface for route in routes), "Current SSH session uses this WWAN; configure locally")
        rules = ip_json("rule", "show")
        for rule in rules:
            if rule.get("priority") in self.role["priorities"] or number(rule.get("table")) == self.role["table"]:
                require(self.owned_rule(rule), "Reserved UE policy slot/table contains a foreign rule; refusing to delete it")
            elif 0 < rule.get("priority", 0) < self.role["block"]:
                # Only disjoint destination rules can be proven harmless without reproducing kernel selectors.
                dst = rule.get("dst", "all")
                try:
                    disjoint = dst != "all" and ipaddress.IPv4Address(self.role["server"]) not in ipaddress.IPv4Network(dst, strict=False)
                except ValueError:
                    disjoint = False
                require(disjoint, "An earlier policy rule may bypass UE routing/fallback guards; inspect ip -4 rule")
        for route in ip_json("route", "show", "table", str(self.role["table"])):
            require(route.get("dev") == interface and route.get("dst", "default") != "default"
                    and ipaddress.IPv4Network(route["dst"], strict=False).subnet_of(pool),
                    "Reserved UE table contains a foreign route")
        for route in ip_json("route", "show", "table", "main"):
            if (reset.WWAN.fullmatch(route.get("dev", "")) and route.get("dev") != interface
                    and route.get("dst", "default") != "default"
                    and ipaddress.IPv4Network(route["dst"], strict=False).subnet_of(pool)):
                raise ValueError("A legacy role route uses another WWAN; inspect it before automatic reset")

    def surroundings(self, bearer):
        """Compare management/other-role state, excluding only this role's owned resources."""
        interface = bearer["interface"]
        rules = [rule for rule in ip_json("rule", "show")
                 if rule.get("priority") not in (*self.role["priorities"], self.role["block"])
                 and number(rule.get("table")) != self.role["table"]]
        addresses = [device for device in ip_json("addr", "show") if device["ifname"] != interface]
        # Full address records include lifetime counters that naturally tick down.
        addresses = [dict(ifname=device["ifname"], addresses=sorted(
            (a["local"], a["prefixlen"]) for a in device.get("addr_info", []))) for device in addresses]
        main_routes = [route for route in ip_json("route", "show", "table", "main") if route.get("dev") != interface]
        other = ROLES[3 - self.ue]
        other_routes = ip_json("route", "show", "table", str(other["table"]))
        links = [dict(ifname=link["ifname"], mtu=link["mtu"], up="UP" in link.get("flags", []))
                 for link in json.loads(read("ip", "-j", "link", "show")) if link["ifname"] != interface]
        return dict(rules=rules, addresses=addresses, main_routes=main_routes, other_routes=other_routes, links=links)

    def management_state(self):
        """Keep management validation across radio waits, allowing UE activity."""
        def managed_rule(rule):
            for ue, role in ROLES.items():
                if rule.get("priority") in (*role["priorities"], role["block"]):
                    if Connection(ue).owned_rule(rule, block=rule.get("priority") == role["block"]):
                        return True
            return False

        addresses = [dict(ifname=device["ifname"], addresses=sorted(
            (item["local"], item["prefixlen"]) for item in device.get("addr_info", [])))
            for device in ip_json("addr", "show") if not reset.WWAN.fullmatch(device["ifname"])]
        rules = [rule for rule in ip_json("rule", "show") if not managed_rule(rule)]
        routes = [route for route in ip_json("route", "show", "table", "main")
                  if not reset.WWAN.fullmatch(route.get("dev", ""))]
        links = [dict(ifname=link["ifname"], mtu=link["mtu"], up="UP" in link.get("flags", []))
                 for link in json.loads(read("ip", "-j", "link", "show"))
                 if not reset.WWAN.fullmatch(link["ifname"])]
        return dict(addresses=addresses, rules=rules, routes=routes, links=links)

    def expected_rules(self, bearer):
        lookup, guard, dest_lookup, dest_guard = self.role["priorities"]
        return ((lookup, bearer["source"], self.role["table"]), (guard, bearer["source"], None),
                (dest_lookup, "all", self.role["table"]), (dest_guard, "all", None))

    def configured(self, bearer):
        devices = [device for device in ip_json("addr", "show") if device["ifname"] == bearer["interface"]]
        if len(devices) != 1 or [(a["local"], a["prefixlen"]) for a in devices[0].get("addr_info", [])] != [(bearer["source"], bearer["prefix"])]:
            return False
        links = json.loads(read("ip", "-j", "link", "show", "dev", bearer["interface"]))
        if len(links) != 1 or links[0].get("mtu") != bearer["mtu"] or "UP" not in links[0].get("flags", []):
            return False
        rules = ip_json("rule", "show")
        relevant = [rule for rule in rules if rule.get("priority") in self.role["priorities"]
                    or number(rule.get("table")) == self.role["table"]]
        if len(relevant) != 4:
            return False
        for priority, source, table in self.expected_rules(bearer):
            matching = [rule for rule in relevant if rule.get("priority") == priority]
            if len(matching) != 1 or not self.owned_rule(matching[0]):
                return False
            rule = matching[0]
            if not (rule.get("src", "all") == "all" if source == "all" else host(rule.get("src"), source)):
                return False
            if (number(rule.get("table")) if "table" in rule else None) != table:
                return False
        routes = ip_json("route", "show", "table", str(self.role["table"]))
        return (len(routes) == 1 and host(routes[0].get("dst"), self.role["server"])
                and routes[0].get("dev") == bearer["interface"] and routes[0].get("prefsrc") == bearer["source"])

    def routes(self, bearer):
        self.block(install=False)
        for bound in (True, False):
            command = ["ip", "-N", "-j", "-4", "route", "get", self.role["server"]]
            if bound:
                command.extend(["from", bearer["source"]])
            routes = json.loads(read(*command))
            require(len(routes) == 1 and routes[0].get("dev") == bearer["interface"]
                    and number(routes[0].get("table")) == self.role["table"],
                    f"{'Source-bound' if bound else 'Ordinary'} route does not use the expected WWAN/table")
            if not bound:
                require(routes[0].get("prefsrc") == bearer["source"], "Ordinary route selects the wrong UE IP")

    def configure(self, bearer):
        self.checked_modem()
        require(self.bearer() == bearer, "Bearer changed before host reset; retry discovery")
        with self.network(shared=True):
            self.host_preflight(bearer)
            if self.configured(bearer):
                self.routes(bearer)
                print("Host path already correct; reusing PDU, addresses and policy rules")
                return
        with self.host_update(bearer):
            self.host_preflight(bearer)
            if self.configured(bearer):
                self.routes(bearer)
                print("Host path already correct; reusing PDU, addresses and policy rules")
                return
            try:
                reset.reset(self.ue, inventory=self.inventory)
                self.block(install=False)
                try:
                    read("ip", "-N", "-j", "-4", "route", "get", self.role["server"])
                except subprocess.CalledProcessError:
                    pass
                else:
                    raise ValueError("Ordinary traffic is still routable after reset; Wi-Fi fallback is not blocked")
                for priority, source, table in self.expected_rules(bearer):
                    if table is None:
                        command = ["ip", "-4", "rule", "add", "pref", str(priority)]
                        if source != "all":
                            command.extend(["from", source + "/32"])
                        change(*command, "to", self.role["server"] + "/32", "unreachable")
                change("ip", "link", "set", "dev", bearer["interface"], "mtu", str(bearer["mtu"]), "up")
                change("ip", "-4", "addr", "add", f"{bearer['source']}/{bearer['prefix']}", "dev", bearer["interface"], "noprefixroute")
                change("ip", "-4", "route", "add", "table", str(self.role["table"]), self.role["server"] + "/32",
                       "dev", bearer["interface"], "scope", "link", "src", bearer["source"])
                for priority, source, table in self.expected_rules(bearer):
                    if table is not None:
                        command = ["ip", "-4", "rule", "add", "pref", str(priority)]
                        if source != "all":
                            command.extend(["from", source + "/32"])
                        change(*command, "to", self.role["server"] + "/32", "lookup", str(table))
                require(self.configured(bearer), "Installed host configuration changed unexpectedly")
                self.routes(bearer)
            except BaseException as error:
                if isinstance(error, StopRequested):
                    # Signal cleanup will reset the host path in a new network
                    # transaction after this one has unwound.
                    raise
                print("Host rebuild failed; retaining the independent destination block and clearing the partial UE path", flush=True)
                try:
                    self.host_preflight(bearer)
                    reset.reset(self.ue, inventory=self.inventory)
                except (ValueError, OSError, subprocess.SubprocessError) as cleanup_error:
                    status(f"\nCleanup incomplete: {cleanup_error}; inspect this UE before retrying", error=True)
                raise

    def run(self, check_only=False):
        with self.step(1, "Modem / SIM identity", "preflight"):
            self.discover()
        with self.step(2, "Modem registration", "registration"):
            self.registered(enable=not check_only)
        with self.step(3, "Serving cell", "serving cell"):
            self.serving_cell()
            net_ports = ports(self.checked_modem())
            require(len(net_ports) == 1, "Expected exactly one dedicated net port for the selected modem")
            before_interface = next(iter(net_ports))
            with self.network(shared=True):
                management = self.management_state()
        with self.step(4, "PDU session / serving-cell recheck", "PDU session"):
            if not check_only:
                with self.host_update(dict(interface=before_interface)):
                    self.block(install=True)
            bearer = self.bearer(connect=not check_only)
            require(bearer["interface"] == before_interface, "Selected modem net port changed while connecting")
            self.result.update(bearer)
            self.serving_cell()
            print(f"PDU PASS: APN={self.role['apn']} IP={bearer['source']}/{bearer['prefix']} WWAN={bearer['interface']} MTU={bearer['mtu']}")
        with self.step(5, "WWAN / policy routing / Wi-Fi fallback block", "host network"):
            with self.network(shared=True):
                require(self.management_state() == management, "Management configuration changed during PDU connection")
            if not check_only:
                self.configure(bearer)
            else:
                with self.network(shared=True):
                    self.host_preflight(bearer)
                    require(self.configured(bearer), "Host path is incomplete")
        with self.step(6, "Source-bound and ordinary routes", "route verification"):
            with self.network(shared=True):
                self.routes(bearer)
        if not check_only:
            for bound in (True, False):
                with self.step(7 if bound else 8, "Source-bound ping" if bound else "Ordinary ping", "ping"):
                    with self.network(shared=True):
                        self.routes(bearer)
                    command = ["ping", "-n", "-c", str(self.ping_count), "-W", "2",
                               "-w", str(max(5, self.ping_count * 3))]
                    if bound:
                        command.extend(["-I", bearer["source"]])
                    key = "source_bound_ping" if bound else "ordinary_ping"
                    try:
                        output = read(*command, self.role["server"])
                    except subprocess.CalledProcessError as error:
                        self.result[key] = error.output or ""
                        print(error.output or "Ping command failed without stdout", file=sys.stderr)
                        raise
                    print(output, end="" if output.endswith("\n") else "\n")
                    self.result[key] = output
        else:
            status("[7/9] Source-bound ping [SKIP: check-only]")
            status("[8/9] Ordinary ping [SKIP: check-only]")
        with self.step(9, "Final identity / cell / network verification", "final verification"):
            require(self.bearer() == bearer, "PDU changed during verification; rerun this UE")
            self.serving_cell()
            with self.network(shared=True):
                require(self.configured(bearer), "Host path changed during verification")
                self.routes(bearer)
                require(self.management_state() == management, "Management configuration changed during verification")
        self.result["status"] = "checked" if check_only else "connected"
        status(f"PASS: UE{self.ue} / {self.role['label']} " + ("checked (ping not run)" if check_only else "connected"),
               detail=f"PASS: UE{self.ue} / {self.role['label']} -> {self.role['server']} via {bearer['interface']} table {self.role['table']}"
               + (" (read-only checks; ping not run)" if check_only else " (source-bound and ordinary ping succeeded)"))
        return self.result

    def manual_hint(self):
        role = self.role
        status(f"""
STOP: UE{self.ue} serving cell requires manual serial checks; no serial configuration was sent.
Expected IMEI={role['imei']}, IMSI={role['imsi']}, PLMN=00101, TAC=7, n78 / NR5G-SA,
PCI={role['pci']}, NCI={role['nci']:X}, SSB ARFCN={role['ssb']}, SCS=30 kHz.
Find this modem's AT port using mmcli -m {self.modem or '<selected modem>'} and /dev/serial/by-path.
Open: sudo minicom -D <THIS_MODEM_AT_PORT> -b 115200
Read: AT+CIMI ; AT+QNWLOCK="common/5g" ; AT+QENG="servingcell" ; AT+C5GREG?
Only if needed, configure this modem manually (one command at a time):
  AT+QNWPREFCFG="mode_pref",NR5G
  AT+QNWPREFCFG="nr5g_disable_mode",2
  AT+QNWLOCK="common/5g",{role['pci']},{role['ssb']},30,78
Read back the lock, actual serving cell and registration; exit minicom, then rerun.
If GetCellInfo is unsupported, rerun with --at-port /dev/serial/by-path/<this-modem-at-port>.
That option only reads IMEI, IMSI and QENG after validating USB ownership; it does not configure the modem.
Do not stop ModemManager, reset CFUN or change the other UE to resolve a serial-port conflict.
""", error=True)


class Tee:
    def __init__(self, terminal, log, verbose=False):
        self.terminal, self.log = terminal, log
        self.verbose = verbose

    def write(self, value):
        self.log.write(value)
        if self.verbose:
            self.terminal.write(value)
        return len(value)

    def show(self, value, detail=None):
        self.log.write(value if detail is None else detail)
        self.terminal.write(detail if self.verbose and detail is not None else value)
        self.flush()

    def flush(self):
        self.log.flush()
        self.terminal.flush()


@contextlib.contextmanager
def capture_reset_output():
    """Use captured subprocess output for this launcher's existing reset helper."""
    original, original_read = reset.change, reset.read
    reset.change = change
    reset.read = read
    try:
        yield
    finally:
        reset.change = original
        reset.read = original_read


def shutdown_on_interrupt(ue, *, lock_path=None, modem_cache=None):
    """Run per-modem shutdown outside the short kernel network transactions."""
    result = dict(ue=ue, status="started", started_at=datetime.now(timezone.utc).isoformat())
    with ignore_stop_signals():
        status(f"UE{ue} shutdown: disconnect PDU, clear host path, delete bearers and disable modem ...")
        original_read = reset.read
        reset.read = read
        try:
            with capture_reset_output():
                session = Connection(ue, modem_cache=modem_cache, network_lock_path=lock_path)
                session.discover()
                info = session.checked_modem()
                net_ports = ports(info)
                require(len(net_ports) == 1, "Expected one dedicated WWAN for shutdown")
                bearer = dict(interface=next(iter(net_ports)))
                with session.host_update(bearer):
                    session.block(install=True)
                connected = info.get("modem.generic.state") in ("connected", "connecting", "disconnecting")
                for path in reset.bearer_paths(info):
                    connected = (kv("mmcli", "-b", path, "-K").get("bearer.status.connected") == "yes"
                                 or connected)
                if connected:
                    session.checked_modem()
                    change("mmcli", "-m", session.modem, "--simple-disconnect")
                info = session.checked_modem()
                for path in reset.bearer_paths(info):
                    require(kv("mmcli", "-b", path, "-K").get("bearer.status.connected") == "no",
                            "Bearer remains connected; stopping shutdown before host reset")
                session.clear_host(bearer)
                reset.shutdown_modem(session.modem, session.role["imei"])
                with session.network(shared=True):
                    session.verify_host_cleared(bearer["interface"])
            result["status"] = "completed"
            status(f"UE{ue} shutdown [OK]: bearers=0, state=disabled, role host path cleared")
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            result.update(status="failed", error=str(error))
            if isinstance(error, subprocess.CalledProcessError) and error.stderr:
                print(error.stderr.strip(), file=sys.stderr)
            status(f"UE{ue} shutdown [FAIL]: {error}; cleanup is incomplete", error=True)
        finally:
            reset.read = original_read
            result["ended_at"] = datetime.now(timezone.utc).isoformat()
    return result


def wait_for_stop():
    """Sleep in the kernel: no timer, modem reads, health checks or ping."""
    while True:
        signal.pause()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ue", type=int, required=True, choices=(1, 2))
    parser.add_argument("--verbose", action="store_true", help="Show full command/details/ping output; default shows steps and completion markers")
    parser.add_argument("--check-only", action="store_true", help="Read identities/cell/PDU/host path without startup changes or ping; Ctrl+C/SIGTERM still shuts this UE down")
    parser.add_argument("--exit-on-success", action="store_true", help="Exit after successful verification instead of holding; leaves the UE connected")
    parser.add_argument("--at-port", help="Optional owned USB AT port for read-only QENG if GetCellInfo is unavailable/incomplete")
    parser.add_argument("--registration-timeout", type=int, default=45, help="Seconds to wait for registration, default 45")
    parser.add_argument("--output-root", default="/tmp", help="Existing directory for private run logs and summary.json")
    args = parser.parse_args()
    require(1 <= args.registration_timeout <= 300, "--registration-timeout must be in 1..300")
    require(os.geteuid() == 0, "Run with sudo (including --check-only for modem access)")
    for command in ("mmcli", "ip", "ping"):
        require(shutil.which(command), f"Missing required command: {command}")
    # Each role owns its modem; only kernel network transactions share a lock.
    with role_lock(args.ue):
        directory = Path(tempfile.mkdtemp(prefix=f"falcon-ue{args.ue}-connect-", dir=args.output_root))
        session = Connection(args.ue, args.at_port, args.registration_timeout)
        with (directory / "run.log").open("w") as log, StopSignals() as stops, \
                contextlib.redirect_stdout(Tee(sys.stdout, log, args.verbose)), \
                contextlib.redirect_stderr(Tee(sys.stderr, log, args.verbose)), capture_reset_output():
            try:
                print(f"Run evidence: {directory}", flush=True)
                session.run(args.check_only)
                if not args.check_only and not args.exit_on_success:
                    session.stage = "waiting for stop"
                    session.result.update(stage=session.stage, lifecycle="waiting_for_stop",
                                          connected_at=datetime.now(timezone.utc).isoformat())
                    (directory / "summary.json").write_text(json.dumps(session.result, indent=2) + "\n")
                    status(f"UE{args.ue} connected; waiting for Ctrl+C to shut down (no polling or ping)")
                    wait_for_stop()
                return 0
            except (ValueError, OSError, subprocess.SubprocessError, KeyboardInterrupt) as error:
                interrupted = isinstance(error, KeyboardInterrupt)
                signum, reason = interruption(error) if interrupted else (None, str(error))
                if interrupted:
                    stops.signum = signum
                    session.result["verified_before_stop"] = session.result["status"] in ("connected", "checked")
                session.result.update(status="interrupted" if interrupted else
                                      "serial_check_required" if isinstance(error, CellError) else "failed",
                                      stage=session.stage, error=reason)
                status(f"STOP at {session.stage}: {reason}", error=True)
                if isinstance(error, subprocess.CalledProcessError) and error.stderr:
                    print(error.stderr.strip(), file=sys.stderr)
                if isinstance(error, CellError):
                    session.manual_hint()
                if interrupted:
                    session.result["signal"] = signum
                    session.result["lifecycle"] = "stopping"
                    session.result["shutdown"] = shutdown_on_interrupt(args.ue, modem_cache=session.modem_cache)
                    session.result["lifecycle"] = "stopped"
                return 128 + signum if interrupted else 1
            finally:
                session.result["ended_at"] = datetime.now(timezone.utc).isoformat()
                (directory / "summary.json").write_text(json.dumps(session.result, indent=2) + "\n")
                status(f"Evidence saved: {directory}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(f"STOP: {error}", file=sys.stderr)
        sys.exit(1)
