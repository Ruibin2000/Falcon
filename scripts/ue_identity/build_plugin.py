#!/usr/bin/env python3
"""Relink an isolated KPM plugin with the retained 40-bit decoder fix.

Reads the pinned, already-built SDK. Never writes its source/build/install tree.
Other objects (including the accepted timestamp fix) come from that exact build.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, build, output = (p.resolve() for p in (args.source, args.build, args.output))
    if output.is_relative_to(source):
        parser.error("candidate plugin must be outside the FlexRIC source/build tree")
    plugin_dir = build / "src/sm/kpm_sm/kpm_sm_v03.00"
    link = shlex.split((plugin_dir / "CMakeFiles/kpm_sm.dir/link.txt").read_text())
    original = source / "src/lib/3gpp/dec/dec_gnb.c"
    patch = ROOT / "patches/flexric/ue_identity_amf_40bit.patch"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="identity-plugin-") as temporary:
        stage = Path(temporary)
        copied = stage / "src/lib/3gpp/dec/dec_gnb.c"
        copied.parent.mkdir(parents=True)
        shutil.copyfile(original, copied)
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(patch)], cwd=stage, check=True)
        flags_file = build / "src/lib/3gpp/dec/CMakeFiles/3gpp_derived_ie_dec_asn_obj_kpm.dir/flags.make"
        flags = {}
        for line in flags_file.read_text().splitlines():
            if " = " in line:
                key, value = line.split(" = ", 1)
                flags[key] = shlex.split(value)
        obj = stage / "dec_gnb.c.o"
        subprocess.run([link[0], *flags["C_DEFINES"], *flags["C_INCLUDES"], *flags["C_FLAGS"],
                        "-I", str(original.parent), "-c", str(copied), "-o", str(obj)], check=True)
        replaced = 0
        for index, arg in enumerate(link):
            if arg.endswith("/3gpp_derived_ie_dec_asn_obj_kpm.dir/dec_gnb.c.o"):
                link[index] = str(obj)
                replaced += 1
            elif arg.endswith(".o"):
                link[index] = str((plugin_dir / arg).resolve())
        if replaced != 1 or link.count("-o") != 1:
            raise ValueError("unexpected pinned SDK link layout")
        candidate = output / "libkpm_sm.so"
        link[link.index("-o") + 1] = str(candidate)
        subprocess.run(link, cwd=stage, check=True)
        manifest = {"source": str(source), "build": str(build), "source_sha256": digest(original),
                    "patch_sha256": digest(patch), "patched_source_sha256": digest(copied),
                    "baseline_plugin_sha256": digest(plugin_dir / "libkpm_sm.so"),
                    "candidate_plugin_sha256": digest(candidate),
                    "link_command_sha256": digest(plugin_dir / "CMakeFiles/kpm_sm.dir/link.txt")}
        # The SDK attempts dlopen on every regular file except *.conf in SM_DIR.
        # Keep metadata outside that scan directory.
        manifest_path = output.parent / (output.name + ".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built isolated candidate plugin: {candidate}")


if __name__ == "__main__":
    main()
