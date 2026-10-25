#!/usr/bin/env python3
"""Exercise the finite traffic schedule, recovery evidence and child cleanup offline."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/dual_fr1"))
SPEC = importlib.util.spec_from_file_location("stability", ROOT / "scripts/dual_fr1/run_dual_stability.py")
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)


class Clock:
    seconds = 0.0
    interrupt_at = None

    def monotonic(self):
        return self.seconds

    def sleep(self, seconds):
        if self.interrupt_at is not None and self.seconds >= self.interrupt_at:
            raise KeyboardInterrupt
        self.seconds += seconds


class Child:
    def __init__(self, clock, never_finishes=False, needs_kill=False):
        self.clock = clock
        self.deadline = clock.seconds + 50
        self.never_finishes = never_finishes
        self.needs_kill = needs_kill
        self.returncode = None
        self.pid = 9000
        self.terminated = self.killed = False

    def poll(self):
        if self.returncode is None and not self.never_finishes and self.clock.seconds >= self.deadline:
            self.returncode = 0
        return self.returncode

    def wait(self, timeout=None):
        if self.needs_kill and not self.killed:
            raise subprocess.TimeoutExpired("fixture", timeout)
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.needs_kill:
            self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


class StabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="falcon-stability-test-")
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.roles = [dict(ue=n, source=f"10.{44+n}.0.7", interface=f"wwan{n-1}",
                           apn="internet" if n == 1 else "internet2", server=f"10.{44+n}.0.1", port=5200+n)
                      for n in (1, 2)]
        self.commands, self.children = [], []
        self.bad_json = self.fail_spawn = None
        self.never_finishes = self.needs_kill = False
        self.patches = [patch.object(S.time, "monotonic", self.clock.monotonic),
                        patch.object(S.time, "sleep", self.clock.sleep),
                        patch.object(S, "snapshot", side_effect=lambda _: copy.deepcopy(self.roles)),
                        patch.object(S.subprocess, "Popen", side_effect=self.popen),
                        contextlib.redirect_stdout(io.StringIO())]
        for item in self.patches:
            item.__enter__()
            self.addCleanup(item.__exit__, None, None, None)

    def popen(self, command, **kwargs):
        self.commands.append(command)
        if len(self.commands) == self.fail_spawn:
            raise OSError("second concurrent spawn failed")
        child = Child(self.clock, self.never_finishes, self.needs_kill)
        self.children.append(child)
        result = dict(end=dict(sum_received=dict(bytes=1000000, seconds=50, bits_per_second=160000)),
                      intervals=[dict(sum=dict(bits_per_second=160000))])
        if len(self.commands) == self.bad_json:
            result = dict(error="server closed the connection")
        kwargs["stdout"].write(json.dumps(result))
        kwargs["stdout"].flush()
        return child

    def run_schedule(self):
        return S.run(wait_for_start=False, output_root=self.temp.name)

    def result(self):
        summaries = list(Path(self.temp.name).glob("*/summary.json"))
        self.assertEqual(len(summaries), 1)
        return json.loads(summaries[0].read_text())

    def test_two_rounds_of_alternating_and_concurrent_clients(self):
        self.assertEqual(self.run_schedule(), 0)
        self.assertEqual([c[c.index("-B")+1] for c in self.commands],
                         [self.roles[n-1]["source"] for n in (1, 2, 1, 2, 1, 2, 1, 2)])
        summary = self.result()
        self.assertEqual(summary["status"], "completed")
        phases = summary["phases"]
        self.assertEqual([p["active_ues"] for p in phases], [[1], [2], [1, 2]] * 2)
        self.assertEqual([len(p["links"]) for p in phases], [1, 1, 2] * 2)
        self.assertGreaterEqual(summary["elapsed_seconds"], 300)
        self.assertLess(summary["elapsed_seconds"], 302)
        self.assertTrue(all(p["status"] == "completed" for p in phases))
        self.assertTrue(all(c["receiver"]["bytes"] > 0 for p in phases for c in p["links"]))
        self.assertTrue(all(not c.terminated for c in self.children))

    def test_ip_change_uses_new_address_but_does_not_pass_stability(self):
        calls = 0
        def current(_):
            nonlocal calls
            calls += 1
            roles = copy.deepcopy(self.roles)
            if calls >= 8:
                roles[0]["source"] = "10.45.0.99"
            return roles
        with patch.object(S, "snapshot", side_effect=current):
            self.assertEqual(self.run_schedule(), 1)
        result = self.result()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["allocation_changes"])
        self.assertEqual(result["phases"][3]["links"][0]["source"], "10.45.0.99")
        self.assertEqual(self.commands[4][self.commands[4].index("-B")+1], "10.45.0.99")

    def test_broken_preflight_starts_no_new_client_and_retains_evidence(self):
        with patch.object(S, "snapshot", side_effect=[self.roles, self.roles, ValueError("Wi-Fi route selected")]):
            self.assertEqual(self.run_schedule(), 1)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.result()["status"], "aborted")
        self.assertIn("Wi-Fi", self.result()["error"])

    def test_interrupted_concurrent_phase_reaps_both_owned_clients(self):
        self.clock.interrupt_at = 101
        self.needs_kill = True
        # Finished children do not need cancellation; only the live pair needs kill.
        original = Child.wait
        def wait(child, timeout=None):
            if child.poll() == 0:
                return 0
            return original(child, timeout)
        with patch.object(Child, "wait", wait):
            self.assertEqual(self.run_schedule(), 1)
        self.assertEqual(len(self.children), 4)
        self.assertTrue(all(c.killed for c in self.children[2:]))
        self.assertEqual(self.result()["status"], "interrupted")
        self.assertTrue(all(link["exit_code"] == -9 for link in self.result()["phases"][-1]["links"]))

    def test_second_concurrent_spawn_failure_cleans_up_first(self):
        self.fail_spawn = 4
        self.assertEqual(self.run_schedule(), 1)
        self.assertTrue(self.children[-1].terminated)
        self.assertEqual(self.result()["status"], "aborted")

    def test_stuck_client_is_bounded_and_failure_is_saved(self):
        self.never_finishes = True
        self.assertEqual(self.run_schedule(), 1)
        self.assertLess(self.clock.seconds, 56)
        self.assertTrue(self.children[0].terminated)
        self.assertIn("time budget", self.result()["error"])

    def test_zero_exit_with_iperf_error_cannot_pass(self):
        self.bad_json = 1
        self.assertEqual(self.run_schedule(), 1)
        result = self.result()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["phases"]), 6)
        self.assertIn("server closed", result["phases"][0]["links"][0]["error"])

    def test_receiver_requires_duration_and_positive_payload(self):
        p = Path(self.temp.name) / "short.json"
        p.write_text(json.dumps(dict(end=dict(sum_received=dict(bytes=0, seconds=50, bits_per_second=0)))))
        with self.assertRaisesRegex(ValueError, "full, positive-byte"):
            S.receiver_result(p)
        p.write_text(json.dumps(dict(end=dict(sum_received=dict(bytes=1000, seconds=2, bits_per_second=4000)))))
        with self.assertRaisesRegex(ValueError, "full, positive-byte"):
            S.receiver_result(p)

    def test_closing_ready_prompt_starts_no_traffic(self):
        with patch("builtins.input", side_effect=EOFError):
            with self.assertRaises(EOFError):
                S.run(output_root=self.temp.name)
        self.assertEqual(self.commands, [])
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])


class QueryTest(unittest.TestCase):
    def test_read_timeout_restores_the_shared_helper(self):
        previous = S.ul.read
        def discover():
            return S.ul.read("mmcli", "-L")
        with patch.object(S.ul, "discover_roles", side_effect=discover), \
             patch.object(S.subprocess, "check_output", side_effect=subprocess.TimeoutExpired("mmcli", 5)) as query:
            with self.assertRaises(subprocess.TimeoutExpired):
                S.snapshot()
        self.assertGreater(query.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(query.call_args.kwargs["timeout"], 5)
        self.assertIs(S.ul.read, previous)

    def test_expired_run_budget_does_not_start_a_query(self):
        previous = S.ul.read
        with patch.object(S.ul, "discover_roles", side_effect=lambda: S.ul.read("mmcli", "-L")), \
             patch.object(S.time, "monotonic", return_value=10), \
             patch.object(S.subprocess, "check_output") as query:
            with self.assertRaisesRegex(TimeoutError, "335-second"):
                S.snapshot(deadline=9)
        query.assert_not_called()
        self.assertIs(S.ul.read, previous)


if __name__ == "__main__":
    unittest.main()
