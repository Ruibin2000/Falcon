#!/usr/bin/env python3
"""Verify both GDB launch configurations with a stub console, without radios/sudo."""

import json
import os
from pathlib import Path
import pty
import shlex
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class DebugLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="falcon-du-debug-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "OCUDU fixture"
        self.scripts = self.root / "scripts with spaces"
        self.scripts.mkdir()
        self.binary = self.source / "build-integrated/apps/du_split_8/odu"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_text("Fixture binary; never executed.\n")
        self.configs = self.source / "configs"
        self.configs.mkdir()
        self.values = {"du1_b210_n78_3660mhz.yml": "DU1 radio 3271233\n",
                       "du2_b210_n78_20mhz.yml": "DU2 radio 328B021\n",
                       "du2_flexric.yml": "DU2 E2 overlay\n"}
        for name, value in self.values.items():
            (self.configs / name).write_text(value)
        for name in ("debug_du.sh", "debug_du1.sh", "debug_du2.sh", "capture_du_crash.gdb"):
            content = (REPO / "scripts/dual_fr1" / name).read_text()
            if name == "debug_du.sh":
                old = "DU_DEBUG_SOURCE=/home/nyu/ocudu"
                self.assertEqual(content.count(old), 1)
                content = content.replace(old, "DU_DEBUG_SOURCE=" + shlex.quote(str(self.source)))
            (self.scripts / name).write_text(content)
        # This stub only records argv. It never runs sudo, GDB, a DU or any radio.
        (self.scripts / "run_du_console.sh").write_text("""#!/usr/bin/env bash
python3 - "$@" <<'PY'
import json, os, sys
from pathlib import Path
Path(os.environ['FALCON_TEST_LAUNCH_ARGS']).write_text(json.dumps(sys.argv[1:]))
PY
""")
        self.args_file = self.root / "argv.json"
        self.env = dict(os.environ, FALCON_TEST_LAUNCH_ARGS=str(self.args_file))
        bindir = self.root / "bin"
        bindir.mkdir()
        fake_gdb = bindir / "gdb"
        fake_gdb.write_text("#!/bin/sh\nexit 99\n")
        fake_gdb.chmod(0o755)
        self.env["PATH"] = str(bindir) + os.pathsep + os.environ["PATH"]

    def retain_for_cleanup(self, root):
        self.addCleanup(shutil.rmtree, root, True)

    def test_both_roles_forward_only_their_own_configs_and_identity(self):
        for role in (1, 2):
            with self.subTest(role=role):
                master, slave = pty.openpty()
                try:
                    child = subprocess.Popen(["bash", str(self.scripts / f"debug_du{role}.sh")],
                                             stdin=slave, stdout=slave, stderr=slave, env=self.env)
                    try:
                        code = child.wait(timeout=10)
                    finally:
                        if child.poll() is None:
                            child.kill()
                            child.wait()
                    self.assertEqual(code, 0)
                finally:
                    os.close(master)
                    os.close(slave)
                args = json.loads(self.args_file.read_text())
                root = Path(args[0]).parent
                self.retain_for_cleanup(root)
                self.assertTrue(root.name.startswith(f"falcon-du{role}-crash."))
                self.assertEqual(args[1:3], ["sudo", "env"])
                self.assertIn(f"FALCON_DU_CRASH_DIR={root}", args)
                self.assertIn(f"FALCON_DU_CRASH_ROLE=DU{role}", args)
                duargs = args[args.index("--args")+1:]
                expected = [str(self.binary), "-c", str(root / f"du{role}.yml")]
                if role == 2:
                    expected += ["-c", str(root / "e2.yml")]
                expected += ["log", "--filename", str(root / "du.log")]
                self.assertEqual(duargs, expected)
                source = "du1_b210_n78_3660mhz.yml" if role == 1 else "du2_b210_n78_20mhz.yml"
                self.assertEqual((root / f"du{role}.yml").read_text(), self.values[source])
                self.assertEqual((root / "e2.yml").exists(), role == 2)
                if role == 2:
                    self.assertEqual((root / "e2.yml").read_text(), self.values["du2_flexric.yml"])
                self.assertTrue((root / "binary.sha256").is_file())
                self.assertEqual((root / "capture.gdb").read_bytes(), (self.scripts / "capture_du_crash.gdb").read_bytes())

    def test_prepare_only_both_roles_needs_no_tty_or_launch(self):
        for role in (1, 2):
            result = subprocess.run(["bash", str(self.scripts / f"debug_du{role}.sh"), "--prepare-only"],
                                    capture_output=True, text=True, env=self.env, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            root = Path(result.stdout.split("debug directory: ", 1)[1].splitlines()[0])
            self.retain_for_cleanup(root)
            self.assertIn("Prepared only", result.stdout)
            self.assertFalse(self.args_file.exists())
            self.assertFalse((root / "startup.log").exists())

    def test_normal_launch_without_tty_is_rejected(self):
        for role in (1, 2):
            result = subprocess.run(["bash", str(self.scripts / f"debug_du{role}.sh")],
                                    capture_output=True, text=True, env=self.env, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn(f"DU{role} interactive terminal", result.stderr)
        self.assertFalse(self.args_file.exists())

    def test_fixed_role_cannot_be_overridden(self):
        for role in (1, 2):
            result = subprocess.run(["bash", str(self.scripts / f"debug_du{role}.sh"), str(3-role)],
                                    capture_output=True, text=True, env=self.env, timeout=10)
            self.assertEqual(result.returncode, 2)
        self.assertFalse(self.args_file.exists())

    def test_missing_du2_overlay_rejects_before_launch(self):
        (self.configs / "du2_flexric.yml").unlink()
        result = subprocess.run(["bash", str(self.scripts / "debug_du2.sh"), "--prepare-only"],
                                capture_output=True, text=True, env=self.env, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("du2_flexric.yml", result.stderr)
        self.assertFalse(self.args_file.exists())


if __name__ == "__main__":
    unittest.main()
