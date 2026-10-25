#!/usr/bin/env python3
"""Stage and test the DU RF monitor against an OCUDU-generated KPM fixture.

Requires the committed FlexRIC timestamp repair and build-ocudu artifacts.
Retains artifacts in --output-dir; never starts a RIC, xApp connection, or radio.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET


BASE_REVISION = "10b8ec79d0f011902d329b2ed37f33f8b101b591"
MONITOR = Path("examples/xApp/c/monitor/xapp_oran_moni.c")
TIMESTAMP_TARGETS = (
    MONITOR,
    Path("examples/xApp/c/monitor/xapp_all_moni.c"),
    Path("src/sm/kpm_sm/kpm_sm_v03.00/dec/dec_asn/dec_ric_ind_hdr_frm_1.c"),
    Path("src/sm/kpm_sm/kpm_sm_v03.00/enc/enc_asn/enc_ric_ind_hdr_frm_1.c"),
    Path("src/sm/kpm_sm/kpm_sm_v03.00/ie/kpm_data_ie/kpm_ric_info/kpm_ric_ind_hdr_frm_1.h"),
    Path("src/sm/kpm_sm/kpm_sm_v03.00/ie/kpm_data_ie/kpm_ric_info/kpm_timestamp.h"),
)
ACTION_TEST = "du_rf_metrics_kpm_test.flexric_seven_metric_subscription_is_accepted"
RF_FIXTURE_BEGIN = "FALCON_RF_FIXTURE_BEGIN"
RF_FIXTURE_END = "FALCON_RF_FIXTURE_END"
CALLBACK_PASSES = (
    "PASS: real config parser and xApp builder encode seven-metric Format 4 subscription",
    "PASS: bounded multi-configuration subscription capacity without SDK calls",
    "PASS: exact opt-in RF trace, full identity, REAL precision/zero, noValue, and invalid values",
    "PASS: malformed callback/list/name/type guards preserve decoded ownership",
    "PASS: Format 1 raw-output compatibility and malformed list/record guards",
    "PASS: OCUDU to FlexRIC RF REAL/noValue payload and patched xApp callback",
)


def run(command, **kwargs):
    print("+ " + shlex.join(map(str, command)), flush=True)
    return subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def git_output(source, *arguments):
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.check_output(["git", "-C", str(source), *map(str, arguments)], env=env)


def validate_output_path(output, forbidden):
    raw = Path(output).expanduser().absolute()
    if any(part.is_symlink() for part in (raw, *raw.parents)):
        raise RuntimeError("output-dir and its ancestors must not be symlinks")
    output = raw.resolve()
    protected = {Path(path).resolve() for path in forbidden} | {
        Path("/home/nyu/Desktop/Falcon_repo/Falcon").resolve(),
        Path("/home/nyu/ocudu").resolve(), Path("/home/nyu/ocudu/build").resolve(),
        Path("/home/nyu/flexric").resolve(), Path("/home/nyu/flexric/build-ocudu").resolve(),
        Path("/usr/local").resolve(),
    }
    if any(output == path or path in output.parents or output in path.parents for path in protected):
        raise RuntimeError("output-dir must not overlap a Falcon, OCUDU, FlexRIC, build, or install path")
    if output.exists() and (not output.is_dir() or next(output.iterdir(), None) is not None):
        raise RuntimeError("output-dir must be absent or an empty directory")
    return output


def validate_patch_targets(patch):
    text = Path(patch).read_text()
    old = re.findall(r"^--- (.+)$", text, re.MULTILINE)
    new = re.findall(r"^\+\+\+ (.+)$", text, re.MULTILINE)
    headers = re.findall(r"^diff --git (.+)$", text, re.MULTILINE)
    if (old != [f"a/{MONITOR.as_posix()}"] or new != [f"b/{MONITOR.as_posix()}"] or
            (headers and headers != [f"a/{MONITOR.as_posix()} b/{MONITOR.as_posix()}"]) or
            re.search(r"^(?:rename |copy |old mode|new mode|new file mode|deleted file mode|GIT binary patch)",
                      text, re.MULTILINE)):
        raise RuntimeError("The cumulative FlexRIC RF patch must modify only the reviewed monitor")
    return [MONITOR.as_posix()]


def compile_flags(source, build):
    target = source / MONITOR
    records = json.loads((build / "compile_commands.json").read_text())
    matches = []
    for item in records:
        directory = Path(item["directory"])
        recorded_source = Path(item["file"])
        if not recorded_source.is_absolute():
            recorded_source = directory / recorded_source
        if recorded_source.resolve() == target.resolve():
            matches.append(item)
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one monitor compile-command record")
    record = matches[0]
    # Parse shell quoting once: the resulting -D argument retains C string quotes.
    args = record.get("arguments") or shlex.split(record["command"])
    if not args or not all(isinstance(item, str) for item in args):
        raise RuntimeError("Invalid monitor compiler argument vector")
    result = []
    index = 0
    while index < len(args):
        item = args[index]
        if item in ("-o", "-MF", "-MT", "-MQ"):
            if index + 1 == len(args):
                raise RuntimeError(f"Missing compiler argument after {item}")
            index += 2
            continue
        if item in ("-c", "-MD", "-MMD"):
            index += 1
            continue
        if index > 0 and not item.startswith("-"):
            path = Path(item)
            if not path.is_absolute():
                path = Path(record["directory"]) / path
            if path.resolve() == target.resolve():
                index += 1
                continue
        if item.startswith(("-MF", "-MT", "-MQ")) or (item.startswith("-o") and item != "-o"):
            index += 1
            continue
        result.append(item)
        index += 1
    if not {"-DE2AP_V3", "-DKPM_V3_00", "-DNONE_XAPP"}.issubset(result):
        raise RuntimeError("Monitor compile flags must select E2AP v3, KPM v3.00, and NONE_XAPP")
    compiler = shutil.which(result[0])
    if compiler is None or not Path(compiler).is_file():
        raise RuntimeError(f"Monitor compiler is unavailable: {result[0]}")
    result[0] = compiler
    return result


def validate_inputs(source, build, output, repo, fixture=None, ocudu_test=None, check_only=False):
    source, build, repo = Path(source).resolve(strict=True), Path(build).resolve(strict=True), Path(repo).resolve(strict=True)
    output = validate_output_path(output, [source, build, repo])
    revision = git_output(source, "rev-parse", "HEAD").decode().strip()
    if revision != BASE_REVISION:
        raise RuntimeError(f"Expected FlexRIC {BASE_REVISION}; found {revision}. Review/rebase the patch first.")
    changes = git_output(source, "status", "--porcelain=v1", "--untracked-files=all", "--", *TIMESTAMP_TARGETS)
    if changes:
        raise RuntimeError(f"Timestamp/RF inputs must be unmodified at HEAD:\n{changes.decode()}")
    for path in TIMESTAMP_TARGETS:
        expected = git_output(source, "show", f"{BASE_REVISION}:{path.as_posix()}")
        if (source / path).is_symlink() or (source / path).read_bytes() != expected:
            raise RuntimeError(f"Canonical committed timestamp input differs: {path}")
    patch = repo / "patches/flexric/73650812-du-rf-metrics.patch"
    validate_patch_targets(patch)
    git_output(source, "apply", "--check", patch)
    flags = compile_flags(source, build)
    monitor_build = build / "examples/xApp/c/monitor"
    common_objects = [
        monitor_build / "CMakeFiles/xapp_oran_moni.dir/__/__/__/__/src/util/alg_ds/alg/defer.c.o",
        build / "src/util/CMakeFiles/e2_time_obj.dir/time_now_us.c.o",
    ]
    sdk = build / "src/xApp/libe42_xapp.a"
    kpm = build / "src/sm/kpm_sm/kpm_sm_v03.00/libkpm_sm_static.a"
    for artifact in (*common_objects, sdk, kpm, repo / "tests/flexric_du_rf_metrics_test.c",
                     repo / "configs/flexric/xapp_du_rf_metrics.conf"):
        if not artifact.is_file():
            raise RuntimeError(f"Required offline input is missing: {artifact}")
    if not check_only:
        if fixture is None:
            raise RuntimeError("--wire-fixture is required unless --check-only is selected")
        fixture = Path(fixture).resolve(strict=True)
        if not fixture.is_file() or fixture.stat().st_size == 0:
            raise RuntimeError("wire-fixture must be a nonempty regular file")
        ocudu_test = Path(ocudu_test).resolve(strict=True) if ocudu_test else fixture.parent / "ocudu_du_rf_metrics_test"
        if not ocudu_test.is_file() or not os.access(ocudu_test, os.X_OK):
            raise RuntimeError(f"OCUDU regression executable is missing or not executable: {ocudu_test}")
    return {"source": source, "build": build, "repo": repo, "output": output, "patch": patch, "revision": revision,
            "flags": flags, "common_objects": common_objects, "sdk": sdk, "kpm": kpm,
            "fixture": fixture, "ocudu_test": ocudu_test}


def preflight_processes():
    active, errors = [], []
    for name in ("odu", "nearRT-RIC", "xapp"):
        result = subprocess.run(["pgrep", "-a", name], capture_output=True, text=True)
        if result.returncode == 0:
            active.append(f"pgrep -a {name}:\n{result.stdout.rstrip()}")
        elif result.returncode != 1:
            errors.append(f"pgrep -a {name}: exit {result.returncode}: {result.stderr.rstrip()}")
    if errors:
        raise RuntimeError("Cannot establish the required build process preflight:\n" + "\n".join(errors))
    if active:
        raise RuntimeError("Build blocked: request user approval while DU/RIC/xApp processes are running.\n" + "\n".join(active))


def run_build(command, env):
    preflight_processes()
    return run(["nice", "-n", "19", *command], env=env)


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_callback_output(stdout, stderr):
    lines = stdout.splitlines()
    for marker in CALLBACK_PASSES:
        if lines.count(marker) != 1:
            raise RuntimeError(f"Expected exactly one callback acceptance marker: {marker}")
    if lines.count(RF_FIXTURE_BEGIN) != 1 or lines.count(RF_FIXTURE_END) != 1:
        raise RuntimeError("Expected exactly one complete decoded RF fixture frame")
    begin, end = lines.index(RF_FIXTURE_BEGIN), lines.index(RF_FIXTURE_END)
    if begin >= end:
        raise RuntimeError("Decoded RF fixture frame markers are out of order")
    # Precision and invalid-value cases emit additional traces outside this frame.
    # Only the original cross-codec fixture supplies these six acceptance rows.
    fixture_traces = [line for line in lines[begin + 1:end] if line.startswith("RF_TRACE ")]
    if len(fixture_traces) != 6:
        raise RuntimeError("Decoded RF fixture frame must contain exactly six trace rows")
    expected = {}
    for metric, unit, values in (
        ("PUSCH.RSRP.dBFS", "dBFS", ("-13.125", "0", "n/a")),
        ("PUSCH.SNR.dB", "dB", ("21.75", "0", "n/a")),
    ):
        for ue, value in zip(("1007", "2091", "3199"), values):
            expected[(ue, metric)] = {"record_type": "noValue" if ue == "3199" else "REAL",
                                      "value": value, "unit": unit}
    actual, header_times = {}, set()
    for line in fixture_traces:
        fields = {}
        for token in line.split()[1:]:
            if "=" not in token:
                raise RuntimeError(f"Malformed decoded RF trace token: {token}")
            name, value = token.split("=", 1)
            if name in fields:
                raise RuntimeError(f"Duplicate decoded RF trace field: {name}")
            fields[name] = value
        identity = {"plmn": "001-01", "mnc_digits": "2", "node_type": "7", "node_id": "411",
                    "node_id_unused": "0", "cu_du_id": "1", "sample_idx": "0", "incomplete": "false"}
        if any(fields.get(key) != value for key, value in identity.items()) or "reason" in fields:
            raise RuntimeError(f"Unexpected fixture trace context: {line}")
        header = fields.get("header_time_us", "")
        if not header.isdecimal() or int(header) == 0:
            raise RuntimeError("Decoded fixture trace must retain a positive KPM header time")
        header_times.add(header)
        key = fields.get("ue_f1ap_id"), fields.get("metric")
        if key not in expected or key in actual:
            raise RuntimeError(f"Unexpected or duplicate decoded RF fixture row: {key}")
        actual[key] = {field: fields.get(field) for field in ("record_type", "value", "unit")}
    if actual != expected or len(header_times) != 1:
        raise RuntimeError("Decoded RF traces do not preserve all six per-UE fixture values/types/units")
    combined = stdout + stderr
    required = (
        "PUSCH.RSRP.dBFS = -13.12 dBFS", "PUSCH.RSRP.dBFS = 0.00 dBFS",
        "PUSCH.RSRP.dBFS = n/a dBFS", "PUSCH.SNR.dB = 21.75 dB",
        "PUSCH.SNR.dB = 0.00 dB", "PUSCH.SNR.dB = n/a dB",
        "RSRQ = n/a source=xapp-capability-status reason=unavailable_in_du",
        "PUSCH.RSRP.dBFS = n/a dBFS (expected REAL)",
        "PUSCH.SNR.dB = n/a dB (expected REAL)",
        "PUSCH.SNR.dB = n/a dB (non-finite REAL)", "incomplete=true", "cu_du_id=2",
        "mismatched name/value counts", "ignoring unexpected KPM callback type",
    )
    missing = [fragment for fragment in required if fragment not in combined]
    if missing:
        raise RuntimeError(f"callback log lacks expected output: {missing}")
    for obsolete in ("FALCON.PUSCH.SINR.dB", "SNR = n/a source=xapp-capability-status"):
        if obsolete in combined:
            raise RuntimeError(f"callback log contains obsolete output: {obsolete}")


def validate_action_xml(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if len(cases) != 1 or f"{cases[0].get('classname')}.{cases[0].get('name')}" != ACTION_TEST:
        raise RuntimeError("Action admission XML must contain exactly the requested test")
    for suite in root.iter():
        if suite.tag in ("testsuite", "testsuites"):
            if int(suite.get("tests", "0")) != len(list(suite.iter("testcase"))):
                raise RuntimeError("Inconsistent action admission XML test count")
            if any(int(suite.get(key, "0")) != 0 for key in ("failures", "errors", "disabled", "skipped")):
                raise RuntimeError("Action admission XML reports failures, errors, disabled cases, or skips")
    if cases[0].get("status") != "run" or cases[0].get("result") != "completed" or any(
        element.tag in ("failure", "error", "skipped") for element in cases[0].iter()
    ):
        raise RuntimeError("Action admission test did not execute successfully")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flexric-source", type=Path, default=Path("/home/nyu/flexric"))
    parser.add_argument("--flexric-build", type=Path, default=Path("/home/nyu/flexric/build-ocudu"))
    parser.add_argument("--wire-fixture", type=Path)
    parser.add_argument("--ocudu-test", type=Path, help="compiled OCUDU regression executable; defaults beside fixture")
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/falcon-du-rf-flexric-check"))
    parser.add_argument("--check-only", action="store_true", help="validate inputs without staging, compiling, or running tests")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    inputs = validate_inputs(args.flexric_source, args.flexric_build, args.output_dir, repo,
                             args.wire_fixture, args.ocudu_test, args.check_only)
    if args.check_only:
        print("PASS: FlexRIC revision, timestamp, unmodified inputs, patch, output, and build-input guards")
        return
    source, output, fixture = inputs["source"], inputs["output"], inputs["fixture"]
    output.mkdir(parents=True, exist_ok=True)
    if next(output.iterdir(), None) is not None:
        raise RuntimeError("output-dir changed after validation; refusing to overwrite artifacts")
    temporary = output / "tmp"
    temporary.mkdir()
    compile_env = dict(os.environ, TMPDIR=str(temporary))
    references = [*(source / path for path in TIMESTAMP_TARGETS), inputs["build"] / "compile_commands.json",
                  inputs["patch"], repo / "tests/flexric_du_rf_metrics_test.c",
                  repo / "configs/flexric/xapp_du_rf_metrics.conf", *inputs["common_objects"],
                  inputs["sdk"], inputs["kpm"], Path(inputs["flags"][0])]
    (output / "build-inputs.json").write_text(json.dumps({
        "revision": inputs["revision"], "timestamp_targets": [str(path) for path in TIMESTAMP_TARGETS],
        "compile_argv": inputs["flags"],
        "sha256": {str(path.resolve()): file_sha256(path) for path in dict.fromkeys(references)},
        "note": "The committed timestamp repair is verified, not reapplied. Existing archive hashes identify reused inputs; they do not establish a fresh deployment build."
    }, indent=2) + "\n")
    stage = output / "source"
    stage.mkdir()
    staged_monitor = stage / MONITOR
    staged_monitor.parent.mkdir(parents=True)
    shutil.copy2(source / MONITOR, staged_monitor)
    src_link = stage / "src"
    src_link.symlink_to(source / "src", target_is_directory=True)
    patch = inputs["patch"]
    run(["git", "apply", "--check", patch], cwd=stage)
    run(["git", "apply", patch], cwd=stage)

    flags = inputs["flags"]
    monitor_object = output / "xapp_oran_moni.o"
    run_build([*flags, "-c", staged_monitor, "-o", monitor_object], compile_env)
    common_objects, sdk, kpm = inputs["common_objects"], inputs["sdk"], inputs["kpm"]
    system_libs = ["-pthread", "-lsctp", "-ldl", "-lconfig", "-lm"]
    # Link the actual monitor but do not execute it: execution would connect to RIC.
    # Production loads KPM dynamically through the SDK, matching its CMake target.
    run_build([flags[0], monitor_object, *common_objects, sdk, *system_libs,
               "-o", output / "xapp_oran_moni"], compile_env)

    test_object = output / "flexric_du_rf_metrics_test.o"
    run_build([*flags, f'-DFALCON_XAPP_SOURCE="{staged_monitor}"', "-c",
               repo / "tests/flexric_du_rf_metrics_test.c", "-o", test_object], compile_env)
    executable = output / "flexric_du_rf_metrics_test"
    # In this offline harness, select KPM's ASN runtime before the SDK's E2AP
    # runtime. Their same-named static functions use different descriptor layouts.
    run_build([flags[0], test_object, *common_objects, "-Wl,--start-group", kpm, sdk,
               "-Wl,--end-group", *system_libs, "-o", executable], compile_env)
    action_wire = output / "flexric-action.bin"
    env = compile_env.copy()
    env["FALCON_KPM_RF_TRACE"] = "0"
    try:
        result = run([executable, fixture, repo / "configs/flexric/xapp_du_rf_metrics.conf", action_wire],
                     env=env, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        (output / "callback.log").write_text((error.stdout or "") + (error.stderr or ""))
        raise RuntimeError(f"callback check failed; see {output / 'callback.log'}") from error
    (output / "callback.log").write_text(result.stdout + result.stderr)
    validate_callback_output(result.stdout, result.stderr)
    if not action_wire.is_file() or action_wire.stat().st_size == 0:
        raise RuntimeError("Callback harness did not produce the required nonempty seven-metric action")
    provider_test = inputs["ocudu_test"]
    env["FALCON_KPM_ACTION_INPUT"] = str(action_wire)
    action_xml = output / "subscription.xml"
    try:
        admission = run([provider_test, f"--gtest_filter={ACTION_TEST}", f"--gtest_output=xml:{action_xml}"],
                        env=env, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        (output / "subscription.log").write_text((error.stdout or "") + (error.stderr or ""))
        raise RuntimeError(f"action admission failed; see {output / 'subscription.log'}") from error
    (output / "subscription.log").write_text(admission.stdout + admission.stderr)
    if "[  PASSED  ] 1 test." not in admission.stdout or "[  SKIPPED ]" in admission.stdout:
        raise RuntimeError("seven-metric subscription admission test did not run and pass")
    validate_action_xml(action_xml)
    (output / "offline-results.json").write_text(json.dumps({
        "result": "Passed", "revision": inputs["revision"], "callback_pass_markers": CALLBACK_PASSES,
        "decoded_fixture_trace_rows": 6, "action_test": ACTION_TEST, "action_xml": str(action_xml),
        "wire_fixture_sha256": file_sha256(fixture), "rf_patch_sha256": file_sha256(patch),
        "scope": "Offline codec, callback, and action admission only; no monitor connection, services, or radio."
    }, indent=2) + "\n")
    print("PASS: patched monitor compiles and links; actual FlexRIC decoder and callback preserve REAL/noValue")
    print(f"Offline artifacts: {output}")


if __name__ == "__main__":
    main()
