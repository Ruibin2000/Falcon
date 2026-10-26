#!/usr/bin/env python3
"""Retain a mandatory manifest, real dummy evidence and all identity regressions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--collector", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, default=Path("/tmp/falcon-ue-identity-sm/libkpm_sm.so"))
    args = parser.parse_args()
    if not args.collector.is_file() or not args.plugin.is_file():
        parser.error("build the collector and isolated KPM plugin first; native cases may not be skipped")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ.update(FALCON_IDENTITY_COLLECTOR=str(args.collector.resolve()),
                      FALCON_IDENTITY_PLUGIN=str(args.plugin.resolve()),
                      FALCON_SUBSCRIPTION_EVIDENCE=str(output / "dummy-evidence"))
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT/"tests/ue_identity"))
    sys.path.insert(0, str(ROOT/"scripts/ue_identity"))
    suite = unittest.defaultTestLoader.discover(str(ROOT/"tests/ue_identity"))
    required = [test.id() for test in flatten(suite)]
    subscriptions = [name for name in required if name.startswith("test_subscriptions.")]
    if len(subscriptions) < 23:
        raise RuntimeError("required subscription cases are missing")
    (output/"required-tests.json").write_text(json.dumps(dict(required=required, subscription_cases=subscriptions), indent=2))
    (output/"command.json").write_text(json.dumps(sys.orig_argv, indent=2))
    outcomes = {}

    class Results(unittest.TextTestResult):
        def startTest(self, test):
            self.started = time.monotonic()
            super().startTest(test)

        def addSuccess(self, test):
            outcomes[test.id()] = dict(status="passed", seconds=time.monotonic()-self.started)
            super().addSuccess(test)

        def addFailure(self, test, error):
            outcomes[test.id()] = dict(status="failed", error=self._exc_info_to_string(error, test))
            super().addFailure(test, error)

        def addError(self, test, error):
            outcomes[test.id()] = dict(status="error", error=self._exc_info_to_string(error, test))
            super().addError(test, error)

        def addSkip(self, test, reason):
            outcomes[test.id()] = dict(status="skipped", reason=reason)
            super().addSkip(test, reason)

    with (output/"tests.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Results).run(suite)
    passed = result.wasSuccessful() and all(outcomes.get(name, {}).get("status") == "passed" for name in required)
    files = list((ROOT/"scripts/ue_identity").glob("*.py")) + [ROOT/"scripts/ue_identity/e2_collector.c",
            ROOT/"tests/ue_identity/test_subscriptions.py", ROOT/"configs/ue_identity/subscriptions.json",
            ROOT/"configs/flexric/xapp_ue_identity_expanded.conf", args.collector, args.plugin]
    hashes = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (output/"sha256.json").write_text(json.dumps(hashes, indent=2))
    (output/"heads.json").write_text(json.dumps({name: subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
         for name, path in (("falcon", ROOT), ("flexric", Path("/home/nyu/flexric")), ("ocudu", Path("/home/nyu/ocudu")))}, indent=2))
    summary = dict(status="passed" if passed else "failed", required=len(required),
                   subscription_cases=len(subscriptions), passed=sum(r["status"] == "passed" for r in outcomes.values()),
                   skipped=len(result.skipped), outcomes=outcomes, data_source="fixture/replay", metric_profile="du27_bound_v1",
                   live_acceptance="pending", thirty_minute_live_stability="pending")
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "outcomes"}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
