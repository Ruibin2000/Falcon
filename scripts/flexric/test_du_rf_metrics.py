#!/usr/bin/env python3
"""Stage and test the DU RF monitor against an OCUDU-generated KPM fixture.

Requires the existing FlexRIC timestamp repair and build-ocudu artifacts.
Writes only to --output-dir; never starts a RIC, xApp connection, or radio.
"""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess


BASE_REVISION = "736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8"


def run(command, **kwargs):
    return subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def compile_flags(source, build):
    target = source / "examples/xApp/c/monitor/xapp_oran_moni.c"
    records = json.loads((build / "compile_commands.json").read_text())
    record = next(item for item in records if Path(item["file"]).resolve() == target.resolve())
    args = record.get("arguments") or shlex.split(record["command"])
    result = []
    index = 0
    while index < len(args):
        item = args[index]
        if item in ("-o", "-c", "-MF", "-MT", "-MQ"):
            index += 2
            continue
        if item in ("-MD", "-MMD"):
            index += 1
            continue
        result.append(item)
        index += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flexric-source", type=Path, default=Path("/home/nyu/flexric"))
    parser.add_argument("--flexric-build", type=Path, default=Path("/home/nyu/flexric/build-ocudu"))
    parser.add_argument("--wire-fixture", type=Path, required=True)
    parser.add_argument("--ocudu-test", type=Path, help="compiled OCUDU regression executable; defaults beside fixture")
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/falcon-du-rf-flexric-check"))
    args = parser.parse_args()
    source = args.flexric_source.resolve()
    build = args.flexric_build.resolve()
    fixture = args.wire_fixture.resolve(strict=True)
    output = args.output_dir.resolve()
    if output == source or source in output.parents or output == build or build in output.parents:
        parser.error("output-dir must be outside the FlexRIC source and build")
    output.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    stage = output / "source"
    monitor_rel = Path("examples/xApp/c/monitor/xapp_oran_moni.c")
    staged_monitor = stage / monitor_rel
    staged_monitor.parent.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != BASE_REVISION:
        raise RuntimeError(f"Expected FlexRIC {BASE_REVISION}; found {revision}. Review/rebase the patch first.")
    if "KPM-v3 report_age_us" not in (source / monitor_rel).read_text():
        parser.error("apply the existing 73650812-kpm-timestamp.patch before this check")
    shutil.copy2(source / monitor_rel, staged_monitor)
    src_link = stage / "src"
    if src_link.is_symlink():
        src_link.unlink()
    elif src_link.exists():
        parser.error("staged source/src must be absent or a symlink")
    src_link.symlink_to(source / "src", target_is_directory=True)
    patch = repo / "patches/flexric/73650812-du-rf-metrics.patch"
    run(["git", "apply", "--check", patch], cwd=stage)
    run(["git", "apply", patch], cwd=stage)

    flags = compile_flags(source, build)
    monitor_object = output / "xapp_oran_moni.o"
    run([*flags, "-c", staged_monitor, "-o", monitor_object])
    monitor_build = build / "examples/xApp/c/monitor"
    common_objects = [
        monitor_build / "CMakeFiles/xapp_oran_moni.dir/__/__/__/__/src/util/alg_ds/alg/defer.c.o",
        build / "src/util/CMakeFiles/e2_time_obj.dir/time_now_us.c.o",
    ]
    sdk = build / "src/xApp/libe42_xapp.a"
    kpm = build / "src/sm/kpm_sm/kpm_sm_v03.00/libkpm_sm_static.a"
    system_libs = ["-pthread", "-lsctp", "-ldl", "-lconfig", "-lm"]
    # Link the actual monitor but do not execute it: execution would connect to RIC.
    # Production loads KPM dynamically through the SDK, matching its CMake target.
    run([flags[0], monitor_object, *common_objects, sdk, *system_libs,
         "-o", output / "xapp_oran_moni"])

    test_object = output / "flexric_du_rf_metrics_test.o"
    run([*flags, f'-DFALCON_XAPP_SOURCE="{staged_monitor}"', "-c",
         repo / "tests/flexric_du_rf_metrics_test.c", "-o", test_object])
    executable = output / "flexric_du_rf_metrics_test"
    # In this offline harness, select KPM's ASN runtime before the SDK's E2AP
    # runtime. Their same-named static functions use different descriptor layouts.
    run([flags[0], test_object, *common_objects, "-Wl,--start-group", kpm, sdk,
         "-Wl,--end-group", *system_libs, "-o", executable])
    action_wire = output / "flexric-action.bin"
    try:
        result = run([executable, fixture, repo / "configs/flexric/xapp_du_rf_metrics.conf", action_wire],
                     capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        (output / "callback.log").write_text((error.stdout or "") + (error.stderr or ""))
        raise RuntimeError(f"callback check failed; see {output / 'callback.log'}") from error
    (output / "callback.log").write_text(result.stdout + result.stderr)
    required = [
        "ue_f1ap_id=1007", "ue_f1ap_id=2091", "ue_f1ap_id=3199",
        "FALCON.PUSCH.RSRP.dBFS = -13.12 dBFS",
        "FALCON.PUSCH.RSRP.dBFS = 0.00 dBFS",
        "FALCON.PUSCH.RSRP.dBFS = n/a dBFS",
        "FALCON.PUSCH.SNR.dB = 21.75 dB",
        "FALCON.PUSCH.SNR.dB = 0.00 dB",
        "FALCON.PUSCH.SNR.dB = n/a dB",
        "RSRQ = n/a source=xapp-capability-status reason=unavailable_in_du",
        "FALCON.PUSCH.RSRP.dBFS = n/a dBFS (expected REAL)",
        "FALCON.PUSCH.SNR.dB = n/a dB (expected REAL)",
        "FALCON.PUSCH.SNR.dB = n/a dB (non-finite REAL)",
        "expected REAL", "non-finite REAL", "incomplete=true", "cu_du_id=2",
        "mismatched name/value counts", "ignoring unexpected KPM callback type",
        "PASS: OCUDU to FlexRIC",
        "PASS: real config parser and xApp builder encode seven-metric",
    ]
    missing = [fragment for fragment in required if fragment not in result.stdout + result.stderr]
    if missing:
        raise RuntimeError(f"callback log lacks expected output: {missing}")
    for obsolete in ("FALCON.PUSCH.SINR.dB", "SNR = n/a source=xapp-capability-status"):
        if obsolete in result.stdout + result.stderr:
            raise RuntimeError(f"callback log contains obsolete output: {obsolete}")
    provider_test = args.ocudu_test or fixture.parent / "ocudu_du_rf_metrics_test"
    env = os.environ.copy()
    env["FALCON_KPM_ACTION_INPUT"] = str(action_wire)
    admission = run([provider_test, "--gtest_filter=du_rf_metrics_kpm_test.flexric_seven_metric_subscription_is_accepted"],
                    env=env, capture_output=True, text=True)
    (output / "subscription.log").write_text(admission.stdout + admission.stderr)
    if "[  PASSED  ] 1 test." not in admission.stdout or "[  SKIPPED ]" in admission.stdout:
        raise RuntimeError("seven-metric subscription admission test did not run and pass")
    print("PASS: patched monitor compiles and links; actual FlexRIC decoder and callback preserve REAL/noValue")
    print(f"Offline artifacts: {output}")


if __name__ == "__main__":
    main()
