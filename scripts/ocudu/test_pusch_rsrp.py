#!/usr/bin/env python3
"""Test the staged PUSCH RSRP patch with existing OCUDU libraries, entirely offline."""

import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess


BASE_REVISION = "050a2bb72e1d794cd60570d809987c1fcda3e54b"


def run(command, *, cwd=None, env=None):
    print("+ " + shlex.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)


def make_variable(path, name):
    match = re.search(r"^" + re.escape(name) + r"[ \t]*=[ \t]*(.*)$", path.read_text(), re.MULTILINE)
    if not match:
        raise RuntimeError(f"Missing {name} in {path}")
    return shlex.split(match.group(1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocudu-source", type=Path, default=Path("/home/nyu/ocudu"))
    parser.add_argument("--ocudu-build", type=Path, default=Path("/home/nyu/ocudu/build"))
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/falcon-rsrp-check"))
    args = parser.parse_args()
    source = args.ocudu_source.resolve()
    build = args.ocudu_build.resolve()
    output = args.output_dir.resolve()
    if output == source or source in output.parents or output == build or build in output.parents:
        parser.error("output-dir must be outside the OCUDU source and build")
    repo = Path(__file__).resolve().parents[2]
    patch = repo / "patches/ocudu/050a2bb-pusch-rsrp.patch"
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != BASE_REVISION:
        raise RuntimeError(f"Expected OCUDU {BASE_REVISION}; found {revision}. Review/rebase the patch first.")

    # Copy only the files changed by the reviewed patch. The source checkout and
    # existing build remain read-only; git apply runs against this private stage.
    relative_sources = re.findall(r"^\+\+\+ b/(.+)$", patch.read_text(), re.MULTILINE)
    if not relative_sources or any(Path(name).is_absolute() or ".." in Path(name).parts for name in relative_sources):
        raise RuntimeError("Patch has no supported, safely relative source paths")
    run(["git", "-C", source, "diff", "--exit-code", "HEAD", "--", *relative_sources])
    output.mkdir(parents=True, exist_ok=True)
    stage = output / "staged-source"
    for name in relative_sources:
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    run(["git", "apply", "--check", patch], cwd=stage)
    run(["git", "apply", patch], cwd=stage)

    # Reuse the compiler/flags and link dependencies recorded by this build.
    # compile_commands.json is optional and absent in the verified host build;
    # CMake's flags.make/link.txt provide the same compile and link information.
    test_build = build / "tests/unittests/e2"
    test_target = test_build / "CMakeFiles/e2sm_kpm_meas_provider_metrics_test.dir"
    flags_file = test_target / "flags.make"
    link_tokens = shlex.split((test_target / "link.txt").read_text())
    compiler = link_tokens[0]
    flags = make_variable(flags_file, "CXX_FLAGS") + make_variable(flags_file, "CXX_DEFINES")
    includes = make_variable(flags_file, "CXX_INCLUDES")
    provider_flags = build / "lib/e2/CMakeFiles/ocudu_e2.dir/flags.make"
    objects = []
    for name in relative_sources:
        obj = output / (Path(name).stem + ".o")
        run([compiler, *make_variable(provider_flags, "CXX_FLAGS"),
             *make_variable(provider_flags, "CXX_DEFINES"),
             *make_variable(provider_flags, "CXX_INCLUDES"), "-I" + str(source),
             "-I" + str((source / name).parent), "-c", stage / name, "-o", obj])
        objects.append(obj)
    test_object = output / "ocudu_pusch_rsrp_test.o"
    run([compiler, *flags, *includes, "-c", repo / "tests/ocudu_pusch_rsrp_test.cpp", "-o", test_object])

    # Put the patched objects before the E2 archive so the linker does not pull
    # the old provider/implementation objects. The original test helper library
    # is not needed: this test has its own sparse F1AP ID translator.
    output_token = link_tokens.index("-o")
    libraries = []
    for token in link_tokens[output_token + 2:]:
        if Path(token).name == "libe2_test_helpers.a":
            continue
        if token.startswith("-"):
            libraries.append(token)
            continue
        library = (test_build / token).resolve()
        if not library.is_file():
            raise RuntimeError(f"Required existing library is missing: {library}")
        libraries.append(str(library))
    executable = output / "ocudu_pusch_rsrp_test"
    run([compiler, *flags, *objects, test_object, "-o", executable, *libraries])
    wire = output / "rsrp-indication.bin"
    env = os.environ.copy()
    env["FALCON_KPM_WIRE_OUTPUT"] = str(wire)
    run([executable], env=env)
    if not wire.is_file() or wire.stat().st_size == 0:
        raise RuntimeError("Tests passed without the required Style 4 APER fixture")
    print(f"PASS: provider and actual Style 4 KPM codec; fixture={wire} ({wire.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
