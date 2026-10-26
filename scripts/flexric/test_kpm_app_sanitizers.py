#!/usr/bin/env python3
"""Build broker-owned code with ASan/UBSan separately, then run the socket suite."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/home/nyu/flexric"))
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixture-plugin", default="/usr/local/lib/flexric/libkpm_sm.so")
    args = parser.parse_args()
    source, build, output = (p.resolve() for p in (args.source, args.build, args.output_dir))
    output.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    monitor = source / "examples/xApp/c/monitor"
    sdk = build / "src/xApp/libe42_xapp.a"
    timer = build / "src/util/CMakeFiles/e2_time_obj.dir/time_now_us.c.o"
    if not sdk.is_file() or not timer.is_file():
        parser.error("Build the normal broker/fixture targets first")
    pkg_cflags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "json-c"], text=True))
    pkg_libs = shlex.split(subprocess.check_output(["pkg-config", "--libs", "json-c"], text=True))
    common = ["gcc", "-std=gnu11", "-g", "-O1", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
              "-Wall", "-Wextra", "-Werror", "-DASN", "-DE2AP_V3", "-DKPM_V3_00", "-DNONE_XAPP",
              "-I", str(source / "src"), "-I", str(monitor), *pkg_cflags]
    core = [str(monitor / "kpm_broker" / f"kpm_{part}.c") for part in ("snapshot", "protocol", "server")]
    units = [str(repo / "tests/flexric_kpm_broker_test.c"), *core]
    broker = [str(monitor / "xapp_kpm_broker.c"), *core,
              str(monitor / "kpm_broker/kpm_source.c"), str(monitor / "kpm_broker/kpm_fixture.c"), str(timer), str(sdk)]
    commands = [common + units + ["-pthread", *pkg_libs, "-o", str(output / "unit-test")],
                common + broker + ["-pthread", *pkg_libs, "-lsctp", "-ldl", "-lconfig", "-lm", "-o", str(output / "broker")]]
    for i, command in enumerate(commands):
        (output / f"compile-{i}.command.json").write_text(json.dumps(command, indent=2))
        with open(output / f"compile-{i}.stdout.txt", "wb") as out, open(output / f"compile-{i}.stderr.txt", "wb") as err:
            result = subprocess.run(command, stdout=out, stderr=err, timeout=60)
        (output / f"compile-{i}.status.json").write_text(json.dumps({"exit_code": result.returncode}))
        if result.returncode:
            return result.returncode
    command = [sys.executable, str(repo / "scripts/flexric/test_kpm_app_subscription.py"),
               "--broker", str(output / "broker"), "--unit-test", str(output / "unit-test"),
               "--fixture-generator", str(build / "examples/xApp/c/monitor/falcon_kpm_broker_fixture"),
               "--dummy", str(repo / "scripts/flexric/dummy_kpm_client.py"), "--metric-profile", "base5",
               "--fixture-plugin", args.fixture_plugin, "--output-dir", str(output / "tests")]
    env = os.environ.copy()
    env["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    (output / "suite.command.json").write_text(json.dumps(command, indent=2))
    (output / "sanitizer-options.json").write_text(json.dumps({key: env[key] for key in ("ASAN_OPTIONS", "UBSAN_OPTIONS")}, indent=2))
    with open(output / "suite.stdout.txt", "wb") as out, open(output / "suite.stderr.txt", "wb") as err:
        result = subprocess.run(command, env=env, stdout=out, stderr=err, timeout=180)
    (output / "suite.status.json").write_text(json.dumps({"exit_code": result.returncode}))
    print(f"Sanitizer suite exit={result.returncode}; results: {output / 'tests/summary.json'}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
