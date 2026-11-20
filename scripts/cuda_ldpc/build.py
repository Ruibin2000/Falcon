#!/usr/bin/env python3
"""Build and validate the optional GPU DU without starting any radio or service."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = "https://gitlab.com/ocudu/work_groups/wg1_hw_accel/cuda_accelerated_ocudu.git"
REVISION = "4df349bf66abad4047537aa519331ed79da91567"
PATCH = ROOT / "patches/ocudu/cuda_ldpc_integration.patch"
OVERLAY = ROOT / "configs/ocudu/cuda_uplink.yml"
TARGETS = (
    "odu_split_8", "ldpc_decoder_gpu_cpu_test", "pusch_codeblock_decoder_cuda_batch_test",
    "pusch_e2e_pipeline_test", "e2sm_kpm_du_expansion_test",
    "e2sm_kpm_meas_provider_test", "e2sm_kpm_meas_provider_metrics_test",
    "scheduler_metrics_handler_test", "fapi_to_mac_indications_fastpath_translator_test",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1048576), b""):
            digest.update(data)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/tmp/falcon-ocudu-cuda-upstream"))
    parser.add_argument("--build", type=Path, default=Path("/home/nyu/ocudu/build-cuda-upstream"))
    parser.add_argument("--ocudu", type=Path, default=Path("/home/nyu/ocudu"))
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--validate-only", action="store_true", help="validate existing artifacts without rebuilding")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    args.source, args.build, args.ocudu = (path.resolve() for path in (args.source, args.build, args.ocudu))
    args.build.mkdir(parents=True, exist_ok=True)
    logs = args.build / "falcon-validation"
    logs.mkdir(exist_ok=True)
    manifest = args.build / "falcon-cuda-validation.json"

    def run(argv, label, timeout=1800, cwd=None):
        print("[CUDA] " + label, flush=True)
        path = logs / (label + ".log")
        with path.open("w") as output:
            try:
                result = subprocess.run(list(map(str, argv)), cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                                        timeout=timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"{label} timed out; see {path}") from exc
        if result.returncode:
            print(path.read_text(errors="replace")[-6000:], file=sys.stderr)
            raise RuntimeError(f"{label} failed ({result.returncode}); see {path}")
        return path

    try:
        if not args.validate_only:
            if not (args.source / ".git").exists():
                if args.source.exists() and any(args.source.iterdir()):
                    raise RuntimeError("Source directory is nonempty; use a separate --source directory")
                run(["git", "init", args.source], "source-init")
                run(["git", "-C", args.source, "fetch", "--depth=1", UPSTREAM, REVISION], "source-fetch", 300)
                run(["git", "-C", args.source, "checkout", "--detach", "FETCH_HEAD"], "source-checkout")
            head = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
            if head != REVISION:
                raise RuntimeError(f"Unexpected source revision {head}; existing sources were not reset")
            reverse = subprocess.run(["git", "-C", str(args.source), "apply", "--reverse", "--check", str(PATCH)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if reverse.returncode:
                run(["git", "-C", args.source, "apply", "--check", PATCH], "patch-check")
                run(["git", "-C", args.source, "apply", PATCH], "patch-apply")
            run(["cmake", "-S", args.source, "-B", args.build,
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_CXX_COMPILER=/usr/bin/clang++-18",
                 "-DCMAKE_C_COMPILER=/usr/bin/clang-18", "-DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc",
                 "-DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++", "-DCMAKE_CUDA_ARCHITECTURES=121",
                 "-DENABLE_CUDA=ON", "-DMCPU=neoverse-v2", "-DBUILD_TESTING=ON", "-DENABLE_EXPORT=OFF"],
                "configure", 300)
            run(["nice", "-n", "15", "cmake", "--build", args.build, "--target", *TARGETS,
                 "-j", args.jobs], "build", 7200)

        binary = args.build / "apps/du_split_8/odu"
        tests = {}
        for target in TARGETS[1:]:
            if target == "pusch_e2e_pipeline_test":
                continue
            if target.startswith("e2sm_"):
                directory = "tests/unittests/e2"
            elif target == "scheduler_metrics_handler_test":
                directory = "tests/unittests/scheduler"
            elif target == "fapi_to_mac_indications_fastpath_translator_test":
                directory = "tests/unittests/fapi_adaptor/mac/p7"
            else:
                directory = "tests/unittests/phy/upper/channel_coding/ldpc"
            xml = logs / (target + ".xml")
            run([args.build / directory / target, "--gtest_color=no", "--gtest_output=xml:" + str(xml)], target, 180)
            tree = ET.parse(xml).getroot()
            cases = list(tree.iter("testcase"))
            skipped = sum(case.find("skipped") is not None for case in cases)
            failures = sum(case.find("failure") is not None or case.find("error") is not None for case in cases)
            passed = len(cases) - skipped - failures
            if failures or not passed:
                raise RuntimeError(f"{target}: {passed} passed, {failures} failed, {skipped} skipped")
            tests[target] = dict(passed=passed, skipped=skipped, failures=failures)
            print(f"[PASS] {target}: {passed} passed, {skipped} skipped", flush=True)

        benchmark = args.build / "tests/integrationtests/phy/upper/channel_processors/pusch_e2e_pipeline_test"
        benchmarks = {}
        def compare(role, prbs, label):
            # GB10 has heterogeneous CPU cores. Keep both CPU/GPU routes on
            # high-capacity cores, with disjoint groups in the concurrent run.
            preferred = range(5, 10) if role == 1 else range(15, 20)
            cpus = sorted(set(preferred) & os.sched_getaffinity(0))
            if not cpus:
                raise RuntimeError(f"No allowed GB10 high-capacity CPU cores for DU{role} comparison")
            path = run(["taskset", "-c", ",".join(map(str, cpus)), benchmark,
                        "--prb", prbs, "--sinr", "30", "--mcs", "20", "--mcs-table", "qam64",
                        "--iterations", "100", "--warmup", "20", "--layers", "1", "--ports", "1",
                        "--dmrs-type", "type1", "--dmrs-symbols", "2,11",
                        "--rx-device-grid", "direct-managed", "--require-gpu-resident", "--quiet"],
                       label, 180)
            text = path.read_text(errors="replace")
            # This upstream benchmark returns zero even for a printed FAIL.
            # Require its decoded-payload result explicitly.
            if "PASS: Both paths decoded all 100 iterations, 0 byte mismatches" not in text or "*** FAIL" in text:
                raise RuntimeError(f"PUSCH comparison did not pass for DU{role}; see {path}")
            return dict(prbs=prbs, layers=1, rx_ports=1, iterations=100, cpu_affinity=cpus,
                        result="passed", log=str(path))

        for role, prbs in ((1, 51), (2, 106)):
            benchmarks[f"du{role}"] = compare(role, prbs, f"du{role}-pusch-comparison")
        # Both real DUs are separate processes sharing GPU 0. Exercise two
        # independent CUDA contexts as well as the single-process comparisons.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {role: pool.submit(compare, role, prbs, f"du{role}-pusch-concurrent")
                       for role, prbs in ((1, 51), (2, 106))}
            for role, future in futures.items():
                benchmarks[f"du{role}_concurrent"] = future.result()

        for role in (1, 2):
            argv = [binary, "--dryrun", "-c", args.ocudu / "configs" /
                    ("du1_b210_n78_3660mhz.yml" if role == 1 else "du2_b210_n78_40mhz.yml")]
            if role == 2:
                argv += ["-c", args.ocudu / "configs/du2_flexric.yml"]
            run([*argv, "-c", OVERLAY, "log", "--filename", "stdout"], f"du{role}-config-parse", 30)

        value = dict(status="passed", source_revision=REVISION, integration_patch_sha256=sha256(PATCH),
                     du_sha256=sha256(binary), overlay_sha256=sha256(OVERLAY), cuda_architecture=121,
                     tests=tests, benchmarks=benchmarks, live_acceptance="pending")
        temporary = manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2) + "\n")
        os.replace(temporary, manifest)
        print(f"[PASS] CUDA DU offline validation: {manifest}")
        print("No services/radios started. Live uplink throughput and stability still require an A/B run.")
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError, ET.ParseError) as exc:
        manifest.unlink(missing_ok=True)
        print("[FAILED] " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
