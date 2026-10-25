set pagination off
set confirm off
set width 0
set print thread-events off
set debuginfod enabled off
set startup-with-shell off
set disable-randomization off
handle SIGPIPE nostop noprint pass
handle SIGINT nostop noprint pass
handle SIGSEGV stop print nopass
handle SIGABRT stop print nopass
handle SIGBUS stop print nopass
handle SIGILL stop print nopass
handle SIGFPE stop print nopass

python
import datetime
import gdb
import hashlib
import json
import os
from pathlib import Path

trace_dir = Path(os.environ["FALCON_DU_CRASH_DIR"])
stop_state = {}
def record_stop(event):
    stop_state["signal"] = getattr(event, "stop_signal", None)
def record_exit(event):
    stop_state["exit_code"] = getattr(event, "exit_code", None)
gdb.events.stop.connect(record_stop)
gdb.events.exited.connect(record_exit)
end

python
try:
    gdb.execute("run")
except gdb.error as error:
    stop_state["launch_error"] = str(error)
end

python
inferior = gdb.selected_inferior()
result = {"recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "role": os.environ.get("FALCON_DU_CRASH_ROLE", "unknown"),
          "pid": inferior.pid, **stop_state}
parts = ["DU debugger capture\n", json.dumps(result, indent=2) + "\n"]
if inferior.pid:
    result["status"] = "stopped"
    for command in ("info program", "thread apply all bt 30", "info registers", "x/i $pc"):
        parts.append("\n(gdb) " + command + "\n")
        try:
            parts.append(gdb.execute(command, to_string=True))
        except gdb.error as error:
            parts.append(str(error) + "\n")
    try:
        with open("/proc/%s/exe" % inferior.pid, "rb") as binary:
            result["mapped_binary_sha256"] = hashlib.file_digest(binary, "sha256").hexdigest()
    except OSError as error:
        result["binary_hash_error"] = str(error)
else:
    result["status"] = "launch_failed" if "launch_error" in result else "exited"
    parts.append("Inferior exited; no stopped threads to inspect.\n")
trace_dir.joinpath("backtrace.txt").write_text("".join(parts))
trace_dir.joinpath("status.json").write_text(json.dumps(result, indent=2) + "\n")
if os.geteuid() == 0:
    owner = trace_dir.stat()
    for name in ("backtrace.txt", "status.json"):
        os.chown(trace_dir / name, owner.st_uid, owner.st_gid)
print("DU debugger evidence: " + str(trace_dir))
# A stopped crashed inferior is terminated when GDB quits; no services are restarted.
code = {"SIGSEGV": 139, "SIGABRT": 134, "SIGBUS": 135, "SIGILL": 132, "SIGFPE": 136}.get(result.get("signal"), result.get("exit_code", 1))
if "launch_error" in result:
    code = 1
gdb.execute("quit %d" % (code if isinstance(code, int) else 1))
end
