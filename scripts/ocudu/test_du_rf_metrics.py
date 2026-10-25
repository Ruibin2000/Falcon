#!/usr/bin/env python3
"""Test the staged DU RSRP/SNR patch with existing OCUDU libraries, entirely offline."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess


BASE_REVISIONS = frozenset({
    "050a2bb72e1d794cd60570d809987c1fcda3e54b",
    "69801c7e9a3a72e4f29d98f14f626f156444c3ca",
    "4cffc0479f9620f668a7ac79aeb314b2e31525e4",
})
# These five blobs are identical at all three explicitly reviewed revisions.
RF_TARGET_BLOBS = {
    "include/ocudu/scheduler/scheduler_metrics.h": "4b5d9d50c77a554acdf61e88d974f3b9bd521cc8",
    "lib/scheduler/logging/scheduler_metrics_handler.cpp": "1ecce04279bd268e0a6af7cd2742307727b7089b",
    "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h": "f875ecd368bc4bbf44407742409b37504b3bc539",
    "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp": "cf8ea94656794d6ab3925772416d558f4b16d901",
    "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_impl.cpp": "055f549a778875f6f84cc78e9387a82b1f32c922",
}


def run(command, *, cwd=None, env=None):
    print("+ " + shlex.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)


def make_variable(path, name):
    match = re.search(r"^" + re.escape(name) + r"[ \t]*=[ \t]*(.*)$", path.read_text(), re.MULTILINE)
    if not match:
        raise RuntimeError(f"Missing {name} in {path}")
    return shlex.split(match.group(1))


def validate_output_path(output, forbidden):
    output = Path(os.path.abspath(Path(output).expanduser()))
    if any(part.is_symlink() for part in (output, *output.parents)):
        raise RuntimeError("output-dir must not contain a symlink component")
    output = output.resolve()
    for directory in forbidden:
        directory = directory.resolve()
        if output == directory or directory in output.parents or output in directory.parents:
            raise RuntimeError(f"output-dir overlaps a protected source/build/repository: {directory}")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise RuntimeError("output-dir must be absent or an empty directory; do not reuse old artifacts")
    return output


def validate_patch_targets(patch):
    text = patch.read_text()
    old = re.findall(r"^--- a/(.+)$", text, re.MULTILINE)
    new = re.findall(r"^\+\+\+ b/(.+)$", text, re.MULTILINE)
    headers = re.findall(r"^diff --git a/(\S+) b/(\S+)$", text, re.MULTILINE)
    expected = set(RF_TARGET_BLOBS)
    if (len(old) != 5 or len(new) != 5 or len(headers) != 5 or
            len(set(new)) != 5 or set(old) != expected or set(new) != expected or
            any(left != right or left not in expected for left, right in headers) or
            re.search(r"^(?:rename |copy |new file mode|deleted file mode|GIT binary patch)", text, re.MULTILINE)):
        raise RuntimeError("RF patch must modify exactly the five reviewed production targets")
    return new


def preflight_processes():
    for name in ("odu", "nearRT-RIC", "xapp"):
        result = subprocess.run(["pgrep", "-a", name], capture_output=True, text=True)
        if result.returncode != 1:
            detail = result.stdout.strip() or result.stderr.strip() or f"exit {result.returncode}"
            raise RuntimeError(f"Build blocked; obtain approval before compiling: pgrep -a {name}: {detail}")


def compile_or_link(command, env):
    preflight_processes()
    run(["nice", "-n", "19", *command], env=env)


def build_recipe(source, build):
    cache = (build / "CMakeCache.txt").read_text()
    home = re.search(r"^CMAKE_HOME_DIRECTORY:INTERNAL=(.+)$", cache, re.MULTILINE)
    if not home or Path(home.group(1)).resolve() != source:
        raise RuntimeError("OCUDU build CMAKE_HOME_DIRECTORY does not match --ocudu-source")
    test_build = build / "tests/unittests/e2"
    target = test_build / "CMakeFiles/e2sm_kpm_meas_provider_metrics_test.dir"
    flags_file = target / "flags.make"
    link_tokens = shlex.split((target / "link.txt").read_text())
    compiler = link_tokens[0]
    flags = make_variable(flags_file, "CXX_FLAGS") + make_variable(flags_file, "CXX_DEFINES")
    includes = make_variable(flags_file, "CXX_INCLUDES")
    libraries = []
    scheduler_build = build / "tests/unittests/scheduler"
    scheduler_target = scheduler_build / "CMakeFiles/scheduler_metrics_handler_test.dir"
    scheduler_link = shlex.split((scheduler_target / "link.txt").read_text())
    references = [build / "CMakeCache.txt", flags_file, target / "link.txt",
                  scheduler_target / "link.txt", Path(compiler)]
    for link_dir, tokens in [(test_build, link_tokens), (scheduler_build, scheduler_link)]:
        output_token = tokens.index("-o")
        for token in tokens[output_token + 2:]:
            if Path(token).name in {"libe2_test_helpers.a", "libocudu_gtest_main.a", "libsched_test_doubles.a"}:
                continue
            if token.startswith("-"):
                libraries.append(token)
                continue
            library = (link_dir / token).resolve()
            if not library.is_file():
                raise RuntimeError(f"Required existing library is missing: {library}")
            libraries.append(str(library))
            references.append(library)
    production_flags = {}
    for name in RF_TARGET_BLOBS:
        if Path(name).suffix != ".cpp":
            continue
        flags_target = ("lib/scheduler/CMakeFiles/ocudu_sched.dir/flags.make"
                        if name.startswith("lib/scheduler/") else "lib/e2/CMakeFiles/ocudu_e2.dir/flags.make")
        path = build / flags_target
        production_flags[name] = (make_variable(path, "CXX_FLAGS") + make_variable(path, "CXX_DEFINES"),
                                  make_variable(path, "CXX_INCLUDES"))
        references.append(path)
    return {"compiler": compiler, "flags": flags, "includes": includes,
            "libraries": libraries, "production_flags": production_flags, "references": references}


def validate_inputs(source, build, output, repo):
    source, build, repo = source.resolve(), build.resolve(), repo.resolve()
    output = validate_output_path(output, [source, build, repo, Path("/home/nyu/ocudu"),
                                          Path("/home/nyu/flexric"), Path("/usr/local"),
                                          Path("/home/nyu/Desktop/Falcon_repo/Falcon")])
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision not in BASE_REVISIONS:
        raise RuntimeError(f"Unsupported OCUDU revision {revision}; expected one of {sorted(BASE_REVISIONS)}")
    patch = repo / "patches/ocudu/050a2bb-du-rf-metrics.patch"
    targets = validate_patch_targets(patch)
    run(["git", "-C", source, "diff", "--exit-code", "HEAD", "--", *targets])
    run(["git", "-C", source, "diff", "--cached", "--exit-code", "HEAD", "--", *targets])
    for name, expected in RF_TARGET_BLOBS.items():
        content = (source / name).read_bytes()
        actual = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if actual != expected:
            raise RuntimeError(f"RF target differs from the reviewed baseline blob: {name}")
    run(["git", "-C", source, "apply", "--check", patch])
    return {"source": source, "build": build, "output": output, "repo": repo,
            "revision": revision, "patch": patch, "targets": targets,
            "recipe": build_recipe(source, build)}


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocudu-source", type=Path, default=Path("/home/nyu/ocudu"))
    parser.add_argument("--ocudu-build", type=Path, default=Path("/home/nyu/ocudu/build"))
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/falcon-du-rf-check"))
    parser.add_argument("--check-only", action="store_true", help="validate guards read-only, without staging or compiling")
    args = parser.parse_args()
    source = args.ocudu_source.resolve()
    build = args.ocudu_build.resolve()
    repo = Path(__file__).resolve().parents[2]
    validated = validate_inputs(source, build, args.output_dir, repo)
    output, patch = validated["output"], validated["patch"]
    relative_sources, recipe = validated["targets"], validated["recipe"]
    if args.check_only:
        print(f"PASS: OCUDU {validated['revision']} guards and existing build inputs; no files written")
        return
    preflight_processes()

    # Copy only the files changed by the reviewed patch. The source checkout and
    # existing build remain read-only; git apply runs against this private stage.
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError("output-dir changed after validation; refusing to overwrite artifacts")
    temporary = output / "tmp"
    temporary.mkdir()
    compile_env = dict(os.environ, TMPDIR=str(temporary))
    references = [*recipe["references"], patch, repo / "tests/ocudu_du_rf_metrics_test.cpp"]
    (output / "build-inputs.json").write_text(json.dumps({
        "revision": validated["revision"], "target_blobs": RF_TARGET_BLOBS,
        "sha256": {str(path): file_sha256(path) for path in dict.fromkeys(references)},
        "note": "Existing archive hashes identify inputs; they do not establish a fresh deployment build."}, indent=2) + "\n")
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
    compiler, flags, includes = recipe["compiler"], recipe["flags"], recipe["includes"]
    staged_includes = ["-I" + str(stage / "include"), "-I" + str(stage),
                       "-I" + str(stage / "lib/e2/e2sm/e2sm_kpm")]
    objects = []
    for name in relative_sources:
        if Path(name).suffix != ".cpp":
            continue
        provider_flags, provider_includes = recipe["production_flags"][name]
        obj = output / (Path(name).stem + ".o")
        compile_or_link([compiler, *provider_flags, *staged_includes, *provider_includes, "-I" + str(source),
                         "-I" + str((source / name).parent), "-c", stage / name, "-o", obj], compile_env)
        objects.append(obj)
    test_object = output / "ocudu_du_rf_metrics_test.o"
    compile_or_link([compiler, *flags, *staged_includes, *includes, "-I" + str(source),
                     "-I" + str(source / "lib/e2/e2sm/e2sm_kpm"),
                     "-c", repo / "tests/ocudu_du_rf_metrics_test.cpp", "-o", test_object], compile_env)

    # Put patched objects before the E2/scheduler archives to avoid pulling the
    # old implementations. The tests use their own F1AP ID translator and the
    # production cell configuration factory, so test-double archives are unused.
    executable = output / "ocudu_du_rf_metrics_test"
    compile_or_link([compiler, *flags, *objects, test_object, "-o", executable, *recipe["libraries"]], compile_env)
    wire = output / "du-rf-indication.bin"
    env = os.environ.copy()
    env["FALCON_KPM_WIRE_OUTPUT"] = str(wire)
    run([executable], env=env)
    if not wire.is_file() or wire.stat().st_size == 0:
        raise RuntimeError("Tests passed without the required Style 4 APER fixture")
    print(f"PASS: scheduler counter, RF provider and actual Style 4 KPM codec; fixture={wire} ({wire.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
