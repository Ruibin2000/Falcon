"""Exercise the console launcher with real PTYs and a fake DU, without radios."""

import errno
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
LAUNCHER = REPO / "scripts/dual_fr1/run_du_console.sh"
CHILD = '''import json, os, signal, sys
assert all(os.isatty(fd) for fd in (0, 1, 2)), "Missing terminal"
assert os.getpgrp() == os.tcgetpgrp(0), "Not in terminal foreground"
if sys.argv[1] == "exit":
    print("CHILD_EXIT", flush=True)
    sys.exit(int(sys.argv[2]))
def interrupted(signum, frame):
    print("INTERRUPTED", flush=True)
    sys.exit(130)
signal.signal(signal.SIGINT, interrupted)
print("ARGV=" + json.dumps(sys.argv[2:]), flush=True)
print("READY", flush=True)
line = sys.stdin.readline()
print("RECEIVED=" + line.rstrip("\\r\\n"), flush=True)
'''


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="falcon console test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.child = self.root / "fake du.py"
        self.child.write_text(CHILD)
        self.log = self.root / "startup log.txt"

    def run_terminal(self, mode="input", arguments=(), send=b";h;\n"):
        pid, master = pty.fork()
        if pid == 0:
            # Deliberately start with a non-Bash SHELL to exercise the launcher's
            # explicit shell selection for its quoted command string.
            os.environ["SHELL"] = "/bin/sh"
            os.execv("/bin/bash", ["bash", str(LAUNCHER), str(self.log),
                                   sys.executable, str(self.child), mode, *arguments])
        output = bytearray()
        sent = False
        reaped = False
        status = None
        deadline = time.monotonic() + 8
        try:
            while time.monotonic() < deadline:
                readable, _, _ = select.select([master], [], [], 0.05)
                if readable:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b""
                    output.extend(chunk)
                if mode != "exit" and not sent and b"READY" in output:
                    # --flush must expose output while the child is still
                    # running and waiting for an interactive command.
                    self.assertIn("READY", self.log.read_text())
                    os.write(master, send)
                    sent = True
                done, status = os.waitpid(pid, os.WNOHANG)
                if done:
                    reaped = True
                    break
            self.assertTrue(reaped, output.decode(errors="replace"))
            return os.waitstatus_to_exitcode(status), output.decode(errors="replace")
        finally:
            os.close(master)
            if not reaped:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                os.waitpid(pid, 0)

    def test_foreground_terminal_input_and_live_console_log(self):
        code, output = self.run_terminal()
        self.assertEqual(code, 0, output)
        self.assertIn("RECEIVED=;h;", output)
        self.assertIn("RECEIVED=;h;", self.log.read_text())

    def test_arguments_remain_literal_through_the_command_shell(self):
        marker = self.root / "should-not-exist"
        arguments = ["path with spaces", f"$(touch '{marker}')", "quote'and\"double", "line\nbreak"]
        code, output = self.run_terminal(arguments=arguments)
        self.assertEqual(code, 0, output)
        transcript = self.log.read_text()
        line = next(line for line in transcript.splitlines() if line.startswith("ARGV="))
        self.assertEqual(json.loads(line.removeprefix("ARGV=")), arguments)
        self.assertFalse(marker.exists())

    def test_child_failure_status_is_preserved(self):
        code, output = self.run_terminal(mode="exit", arguments=["42"])
        self.assertEqual(code, 42, output)
        self.assertIn("CHILD_EXIT", self.log.read_text())

    def test_ctrl_c_reaches_the_interactive_child(self):
        code, output = self.run_terminal(send=b"\x03")
        self.assertEqual(code, 130, output)
        self.assertIn("INTERRUPTED", self.log.read_text())

    def test_noninteractive_launch_is_refused_before_running_command(self):
        marker = self.root / "must-not-run"
        result = subprocess.run(["bash", str(LAUNCHER), str(self.log), "touch", str(marker)],
                                input="", capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("interactive terminal", result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
