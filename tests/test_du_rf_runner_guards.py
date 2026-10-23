#!/usr/bin/env python3
"""Exercise RF runner rejection paths without Git mutations, builds, or services."""

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]


def load_runner(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, REPO / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OCUDU = load_runner("ocudu_du_rf_guard_test_runner", "scripts/ocudu/test_du_rf_metrics.py")
FLEXRIC = load_runner("flexric_du_rf_guard_test_runner", "scripts/flexric/test_du_rf_metrics.py")


class OcuduRunnerGuardTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="falcon-rf-runner-guards-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.build = self.source / "build"
        self.output = self.root / "output"
        self.patch = REPO / "patches/ocudu/050a2bb-du-rf-metrics.patch"
        self.blobs = {}
        # Ordinary temporary files, not a Git checkout: all Git operations below are mocked.
        for name in OCUDU.RF_TARGET_BLOBS:
            payload = ("guard fixture: " + name + "\n").encode()
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            self.blobs[name] = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()

    @contextlib.contextmanager
    def preflight(self, revision, *, reject_diff=False, reject_cached=False, reject_apply=False):
        def git_read_only(command, **kwargs):
            tokens = list(map(str, command))
            if tokens[:3] != ["git", "-C", str(self.source)]:
                raise AssertionError(f"Unexpected preflight command: {tokens}")
            if tokens[3:7] == ["diff", "--exit-code", "HEAD", "--"]:
                if reject_diff:
                    raise subprocess.CalledProcessError(1, tokens, output="modified RF target")
            elif tokens[3:8] == ["diff", "--cached", "--exit-code", "HEAD", "--"]:
                if reject_cached:
                    raise subprocess.CalledProcessError(1, tokens, output="index-only RF target change")
            elif tokens[3:5] == ["apply", "--check"]:
                if reject_apply:
                    raise subprocess.CalledProcessError(1, tokens, stderr="patch does not apply")
            else:
                raise AssertionError(f"Unexpected Git operation: {tokens}")

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(OCUDU, "RF_TARGET_BLOBS", self.blobs))
            head = stack.enter_context(mock.patch.object(OCUDU.subprocess, "check_output", return_value=revision + "\n"))
            git = stack.enter_context(mock.patch.object(OCUDU, "run", side_effect=git_read_only))
            recipe = stack.enter_context(mock.patch.object(OCUDU, "build_recipe", return_value={"compiler": "/never-run"}))
            compile_call = stack.enter_context(mock.patch.object(OCUDU, "compile_or_link"))
            copy_call = stack.enter_context(mock.patch.object(OCUDU.shutil, "copyfile"))
            yield SimpleNamespace(head=head, git=git, recipe=recipe, compile=compile_call, copy=copy_call)

    def run_main(self, *, check_only=False):
        command = [str(REPO / "scripts/ocudu/test_du_rf_metrics.py"),
                   "--ocudu-source", str(self.source), "--ocudu-build", str(self.build),
                   "--output-dir", str(self.output)]
        if check_only:
            command.append("--check-only")
        with mock.patch.object(sys, "argv", command), contextlib.redirect_stdout(io.StringIO()):
            OCUDU.main()

    def assert_no_staging(self, calls):
        calls.compile.assert_not_called()
        calls.copy.assert_not_called()
        self.assertFalse(self.output.exists(), "a rejected/check-only run must not create output")

    def test_allowlist_contains_only_the_three_deliberately_reviewed_full_revisions(self):
        self.assertEqual(OCUDU.BASE_REVISIONS, {
            "050a2bb72e1d794cd60570d809987c1fcda3e54b",
            "69801c7e9a3a72e4f29d98f14f626f156444c3ca",
            "4cffc0479f9620f668a7ac79aeb314b2e31525e4",
        })

    def test_each_approved_revision_still_checks_payload_diff_and_patch_without_writing(self):
        for revision in sorted(OCUDU.BASE_REVISIONS):
            with self.subTest(revision=revision), self.preflight(revision) as calls:
                self.run_main(check_only=True)
                self.assertEqual(calls.git.call_count, 3)
                self.assertEqual(list(map(str, calls.git.call_args_list[0].args[0]))[3:7],
                                 ["diff", "--exit-code", "HEAD", "--"])
                self.assertEqual(list(map(str, calls.git.call_args_list[1].args[0]))[3:8],
                                 ["diff", "--cached", "--exit-code", "HEAD", "--"])
                self.assertEqual(list(map(str, calls.git.call_args_list[2].args[0]))[3:5], ["apply", "--check"])
                calls.recipe.assert_called_once_with(self.source.resolve(), self.build.resolve())
                self.assert_no_staging(calls)

    def test_unknown_revision_is_rejected_before_diff_staging_or_compile(self):
        with self.preflight("f" * 40) as calls:
            with self.assertRaisesRegex(RuntimeError, "Unsupported OCUDU revision"):
                self.run_main()
            calls.git.assert_not_called()
            calls.recipe.assert_not_called()
            self.assert_no_staging(calls)

    def test_dirty_targets_are_rejected_before_blob_recipe_staging_or_compile(self):
        with self.preflight("4cffc0479f9620f668a7ac79aeb314b2e31525e4", reject_diff=True) as calls:
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_main()
            self.assertEqual(calls.git.call_count, 1)
            calls.recipe.assert_not_called()
            self.assert_no_staging(calls)

    def test_changed_target_payload_is_rejected_even_if_git_diff_reports_clean(self):
        target = self.source / next(iter(self.blobs))
        target.write_bytes(target.read_bytes() + b"unreviewed change\n")
        with self.preflight("4cffc0479f9620f668a7ac79aeb314b2e31525e4") as calls:
            with self.assertRaisesRegex(RuntimeError, "reviewed baseline blob"):
                self.run_main()
            self.assertEqual(calls.git.call_count, 2)
            calls.recipe.assert_not_called()
            self.assert_no_staging(calls)

    def test_failed_patch_check_stops_before_recipe_staging_or_compile(self):
        with self.preflight("69801c7e9a3a72e4f29d98f14f626f156444c3ca", reject_apply=True) as calls:
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_main()
            self.assertEqual(calls.git.call_count, 3)
            calls.recipe.assert_not_called()
            self.assert_no_staging(calls)

    def test_index_only_change_is_rejected_even_when_working_bytes_match_head(self):
        with self.preflight("4cffc0479f9620f668a7ac79aeb314b2e31525e4", reject_cached=True) as calls:
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_main()
            self.assertEqual(calls.git.call_count, 2)
            calls.recipe.assert_not_called()
            self.assert_no_staging(calls)

    def test_real_candidate_modifies_exactly_the_reviewed_five_targets(self):
        targets = OCUDU.validate_patch_targets(self.patch)
        self.assertEqual(len(targets), 5)
        self.assertEqual(set(targets), set(OCUDU.RF_TARGET_BLOBS))

    def test_unsafe_extra_missing_duplicate_and_renamed_patch_targets_are_rejected(self):
        original = self.patch.read_text()
        sections = ["diff --git " + part for part in original.split("diff --git ")[1:]]
        target = next(iter(OCUDU.RF_TARGET_BLOBS))
        candidates = {
            "unsafe": original.replace(target, "../" + target),
            "extra": original + "diff --git a/extra.cpp b/extra.cpp\n--- a/extra.cpp\n+++ b/extra.cpp\n",
            "missing": "".join(sections[:-1]),
            "duplicate": "".join(sections[:-1] + [sections[0]]),
            "rename_metadata": original + "rename from extra.cpp\nrename to other.cpp\n",
        }
        for name, content in candidates.items():
            with self.subTest(case=name):
                patch = self.root / (name + ".patch")
                patch.write_text(content)
                with self.assertRaisesRegex(RuntimeError, "exactly the five reviewed"):
                    OCUDU.validate_patch_targets(patch)
        self.assertFalse(self.output.exists())


class FlexricRunnerGuardTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="falcon-flexric-runner-guards-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.build = self.source / "build-ocudu"
        self.build.mkdir(parents=True)
        self.output = self.root / "output"
        self.patch = REPO / "patches/flexric/73650812-du-rf-metrics.patch"
        self.canonical = {}
        for name in FLEXRIC.TIMESTAMP_TARGETS:
            payload = ("canonical timestamp guard fixture: " + str(name) + "\n").encode()
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            self.canonical[str(name)] = payload
        artifacts = (
            "examples/xApp/c/monitor/CMakeFiles/xapp_oran_moni.dir/__/__/__/__/src/util/alg_ds/alg/defer.c.o",
            "src/util/CMakeFiles/e2_time_obj.dir/time_now_us.c.o",
            "src/xApp/libe42_xapp.a", "src/sm/kpm_sm/kpm_sm_v03.00/libkpm_sm_static.a",
        )
        for name in artifacts:
            artifact = self.build / name
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"guard-only input, never linked")

    @contextlib.contextmanager
    def preflight(self, *, revision=None, changes=b"", reject_apply=False):
        def git_read_only(source, *arguments):
            self.assertEqual(source, self.source.resolve())
            tokens = tuple(map(str, arguments))
            if tokens == ("rev-parse", "HEAD"):
                return (revision or FLEXRIC.BASE_REVISION).encode() + b"\n"
            if tokens[:2] == ("status", "--porcelain=v1"):
                return changes
            if tokens[:1] == ("show",):
                return self.canonical[tokens[1].split(":", 1)[1]]
            if tokens[:2] == ("apply", "--check"):
                if reject_apply:
                    raise subprocess.CalledProcessError(1, tokens, stderr="patch does not apply")
                return b""
            raise AssertionError(f"Unexpected Git operation: {tokens}")

        with contextlib.ExitStack() as stack:
            git = stack.enter_context(mock.patch.object(FLEXRIC, "git_output", side_effect=git_read_only))
            flags = stack.enter_context(mock.patch.object(FLEXRIC, "compile_flags", return_value=["/never-run"]))
            compile_call = stack.enter_context(mock.patch.object(FLEXRIC, "run_build"))
            copy_call = stack.enter_context(mock.patch.object(FLEXRIC.shutil, "copy2"))
            yield SimpleNamespace(git=git, flags=flags, compile=compile_call, copy=copy_call)

    def run_main(self, *, check_only=False):
        command = [str(REPO / "scripts/flexric/test_du_rf_metrics.py"),
                   "--flexric-source", str(self.source), "--flexric-build", str(self.build),
                   "--output-dir", str(self.output)]
        if check_only:
            command.append("--check-only")
        with mock.patch.object(sys, "argv", command), contextlib.redirect_stdout(io.StringIO()):
            FLEXRIC.main()

    def assert_no_staging(self, calls):
        calls.compile.assert_not_called()
        calls.copy.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_only_committed_timestamp_baseline_is_deliberately_accepted(self):
        self.assertEqual(FLEXRIC.BASE_REVISION, "10b8ec79d0f011902d329b2ed37f33f8b101b591")
        with self.preflight() as calls:
            self.run_main(check_only=True)
            shown = [str(call.args[2]) for call in calls.git.call_args_list if call.args[1] == "show"]
            self.assertEqual(set(shown), {f"{FLEXRIC.BASE_REVISION}:{name}" for name in FLEXRIC.TIMESTAMP_TARGETS})
            self.assertEqual(sum(call.args[1:3] == ("apply", "--check") for call in calls.git.call_args_list), 1)
            calls.flags.assert_called_once_with(self.source.resolve(), self.build.resolve())
            self.assert_no_staging(calls)

    def test_unknown_and_old_unrepaired_revisions_are_rejected_without_staging(self):
        for revision in ("f" * 40, "736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8"):
            with self.subTest(revision=revision), self.preflight(revision=revision) as calls:
                with self.assertRaisesRegex(RuntimeError, "Expected FlexRIC"):
                    self.run_main()
                self.assertEqual(calls.git.call_count, 1)
                calls.flags.assert_not_called()
                self.assert_no_staging(calls)

    def test_dirty_monitor_or_timestamp_helper_is_rejected_before_staging(self):
        for name in (FLEXRIC.MONITOR, FLEXRIC.TIMESTAMP_TARGETS[-1]):
            with self.subTest(target=name), self.preflight(changes=f" M {name}\n".encode()) as calls:
                with self.assertRaisesRegex(RuntimeError, "must be unmodified"):
                    self.run_main()
                self.assertEqual(calls.git.call_count, 2)
                calls.flags.assert_not_called()
                self.assert_no_staging(calls)

    def test_changed_canonical_content_is_rejected_even_if_status_reports_clean(self):
        for name in FLEXRIC.TIMESTAMP_TARGETS:
            with self.subTest(target=name):
                target = self.source / name
                target.write_bytes(self.canonical[str(name)] + b"unexpected change")
                with self.preflight() as calls:
                    with self.assertRaisesRegex(RuntimeError, "Canonical committed timestamp input differs"):
                        self.run_main()
                    calls.flags.assert_not_called()
                    self.assert_no_staging(calls)
                target.write_bytes(self.canonical[str(name)])

    def test_canonical_input_symlink_is_rejected_even_with_matching_bytes(self):
        name = FLEXRIC.TIMESTAMP_TARGETS[-1]
        target = self.source / name
        backup = self.root / "timestamp-content"
        target.rename(backup)
        target.symlink_to(backup)
        with self.preflight() as calls:
            with self.assertRaisesRegex(RuntimeError, "Canonical committed timestamp input differs"):
                self.run_main()
            self.assert_no_staging(calls)

    def test_failed_patch_check_stops_before_compile_flags_staging_or_compile(self):
        with self.preflight(reject_apply=True) as calls:
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_main()
            calls.flags.assert_not_called()
            self.assert_no_staging(calls)

    def test_real_candidate_modifies_only_monitor(self):
        self.assertEqual(FLEXRIC.validate_patch_targets(self.patch), [FLEXRIC.MONITOR.as_posix()])

    def test_extra_unsafe_missing_duplicate_or_mode_patch_changes_are_rejected(self):
        original = self.patch.read_text()
        target = FLEXRIC.MONITOR.as_posix()
        candidates = {
            "unsafe": original.replace(target, "../" + target),
            "extra": original + "--- a/extra.c\n+++ b/extra.c\n",
            "missing": original.replace(f"+++ b/{target}", "+++ /dev/null"),
            "duplicate": original + f"--- a/{target}\n+++ b/{target}\n",
            "mode": original + "old mode 100644\nnew mode 100755\n",
        }
        for name, content in candidates.items():
            with self.subTest(case=name):
                patch = self.root / (name + ".patch")
                patch.write_text(content)
                with self.assertRaisesRegex(RuntimeError, "modify only the reviewed monitor"):
                    FLEXRIC.validate_patch_targets(patch)
        self.assertFalse(self.output.exists())

    def test_required_offline_archive_missing_stops_without_output(self):
        (self.build / "src/xApp/libe42_xapp.a").unlink()
        with self.preflight() as calls:
            with self.assertRaisesRegex(RuntimeError, "Required offline input is missing"):
                self.run_main(check_only=True)
            self.assert_no_staging(calls)

    def test_normal_run_requires_a_fixture_before_staging(self):
        with self.preflight() as calls:
            with self.assertRaisesRegex(RuntimeError, "wire-fixture is required"):
                self.run_main()
            self.assert_no_staging(calls)


class FlexricCompilerRecordGuardTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="falcon-flexric-command-guards-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.build = self.root / "build"
        self.source.mkdir()
        self.build.mkdir()
        self.target = self.source / FLEXRIC.MONITOR
        self.compiler = self.root / "never-run-gcc"
        self.compiler.write_bytes(b"guard placeholder, not an executable compiler")
        self.flags = [str(self.compiler), "-DE2AP_V3", "-DKPM_V3_00", "-DNONE_XAPP", '-DServiceModel="KPM"']

    def record(self, arguments, *, shell_command=False):
        result = {"file": str(self.target), "directory": str(self.build)}
        result["command" if shell_command else "arguments"] = shlex.join(arguments) if shell_command else arguments
        return result

    def write_records(self, records):
        (self.build / "compile_commands.json").write_text(json.dumps(records))

    def test_single_parse_preserves_quoted_defines_and_removes_only_source_and_outputs(self):
        arguments = [*self.flags, "-MD", "-MT", "obj.o", "-MF", "obj.d", "-c", str(self.target), "-o", "obj.o"]
        for shell_command in (False, True):
            with self.subTest(shell_command=shell_command):
                self.write_records([self.record(arguments, shell_command=shell_command)])
                with mock.patch.object(FLEXRIC.shutil, "which", return_value=str(self.compiler)):
                    self.assertEqual(FLEXRIC.compile_flags(self.source, self.build), self.flags)

    def test_duplicate_or_missing_monitor_record_is_rejected(self):
        record = self.record(self.flags)
        for records in ([], [record, record]):
            with self.subTest(records=len(records)):
                self.write_records(records)
                with self.assertRaisesRegex(RuntimeError, "exactly one monitor"):
                    FLEXRIC.compile_flags(self.source, self.build)

    def test_wrong_protocol_or_database_macros_are_rejected(self):
        for required in ("-DE2AP_V3", "-DKPM_V3_00", "-DNONE_XAPP"):
            with self.subTest(missing=required):
                self.write_records([self.record([flag for flag in self.flags if flag != required])])
                with self.assertRaisesRegex(RuntimeError, "must select E2AP v3"):
                    FLEXRIC.compile_flags(self.source, self.build)

    def test_unavailable_monitor_compiler_is_rejected_without_execution(self):
        self.write_records([self.record(self.flags)])
        with mock.patch.object(FLEXRIC.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Monitor compiler is unavailable"):
                FLEXRIC.compile_flags(self.source, self.build)


class FlexricAcceptanceGuardTest(unittest.TestCase):
    def callback_output(self):
        lines = [*FLEXRIC.CALLBACK_PASSES, FLEXRIC.RF_FIXTURE_BEGIN]
        for metric, unit, values, readable in (
            ("FALCON.PUSCH.RSRP.dBFS", "dBFS", ("-13.125", "0", "n/a"), ("-13.12", "0.00", "n/a")),
            ("FALCON.PUSCH.SNR.dB", "dB", ("21.75", "0", "n/a"), ("21.75", "0.00", "n/a")),
        ):
            for ue, value, normal in zip(("1007", "2091", "3199"), values, readable):
                context = (f"plmn=001-01 mnc_digits=2 node_type=7 node_id=411 node_id_unused=0 cu_du_id=1 "
                           f"ue_f1ap_id={ue} header_time_us=123456 sample_idx=0")
                record_type = "noValue" if ue == "3199" else "REAL"
                lines.append(f"RF_TRACE {context} metric={metric} record_type={record_type} value={value} unit={unit} incomplete=false")
                lines.append(f"{context} {metric} = {normal} {unit}")
        lines.extend((
            "RSRQ = n/a source=xapp-capability-status reason=unavailable_in_du",
            FLEXRIC.RF_FIXTURE_END,
            "FALCON.PUSCH.RSRP.dBFS = n/a dBFS (expected REAL)",
            "FALCON.PUSCH.SNR.dB = n/a dB (expected REAL)",
            "FALCON.PUSCH.SNR.dB = n/a dB (non-finite REAL)",
            "incomplete=true cu_du_id=2",
        ))
        return "\n".join(lines) + "\n", "mismatched name/value counts\nignoring unexpected KPM callback type\n"

    def full_callback_output(self):
        stdout, stderr = self.callback_output()
        lines = []
        # The C harness reuses UE 1007 for eight diagnostic cases per metric.
        # These sixteen rows follow the six original fixture rows in real output.
        for metric, unit in (("FALCON.PUSCH.RSRP.dBFS", "dBFS"), ("FALCON.PUSCH.SNR.dB", "dB")):
            context = ("plmn=001-01 mnc_digits=2 node_type=7 node_id=411 node_id_unused=0 cu_du_id=1 "
                       "ue_f1ap_id=1007 header_time_us=123456 sample_idx=0")
            for index, value in enumerate((-13.123456789012345, 0.12345678901234566, -0.0)):
                lines.append(f"CASE: verified {metric} precise REAL {index}")
                lines.append(f"RF_TRACE {context} metric={metric} record_type=REAL value={value:.17g} unit={unit} incomplete=false")
            for index in range(3):
                lines.append(f"CASE: verified {metric} non-finite REAL {index}")
                lines.append(f"RF_TRACE {context} metric={metric} record_type=REAL value=n/a unit={unit} incomplete=false reason=non_finite_REAL")
            lines.append(f"CASE: verified {metric} rejected INTEGER")
            lines.append(f"RF_TRACE {context} metric={metric} record_type=INTEGER value=n/a unit={unit} incomplete=false reason=expected_REAL")
            lines.append(f"CASE: verified {metric} unsupported value type")
            lines.append(f"RF_TRACE {context} metric={metric} record_type=unsupported value=n/a unit={unit} incomplete=false reason=unsupported_value_type")
        return stdout + "\n".join(lines) + "\n", stderr

    def test_exact_per_ue_values_and_single_markers_are_accepted(self):
        stdout, stderr = self.callback_output()
        FLEXRIC.validate_callback_output(stdout, stderr)

    def test_swapped_per_ue_values_are_rejected_even_with_all_readable_values_present(self):
        stdout, stderr = self.callback_output()
        lines = stdout.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("RF_TRACE ") and "metric=FALCON.PUSCH.RSRP.dBFS " in line:
                if "ue_f1ap_id=1007 " in line:
                    lines[index] = line.replace("value=-13.125 ", "value=0 ")
                elif "ue_f1ap_id=2091 " in line:
                    lines[index] = line.replace("value=0 ", "value=-13.125 ")
        with self.assertRaisesRegex(RuntimeError, "all six per-UE fixture"):
            FLEXRIC.validate_callback_output("\n".join(lines) + "\n", stderr)

    def test_duplicate_or_missing_rf_trace_rows_are_rejected(self):
        stdout, stderr = self.callback_output()
        trace = next(line for line in stdout.splitlines() if line.startswith("RF_TRACE "))
        duplicate = stdout.replace(FLEXRIC.RF_FIXTURE_END + "\n", trace + "\n" + FLEXRIC.RF_FIXTURE_END + "\n", 1)
        for mutated in (duplicate, stdout.replace(trace + "\n", "", 1)):
            with self.subTest(duplicate=len(mutated) > len(stdout)), self.assertRaises(RuntimeError):
                FLEXRIC.validate_callback_output(mutated, stderr)

    def test_complete_harness_replay_accepts_six_fixture_and_sixteen_diagnostic_traces(self):
        stdout, stderr = self.full_callback_output()
        self.assertEqual(sum(line.startswith("RF_TRACE ") for line in stdout.splitlines()), 22)
        self.assertEqual(stdout.splitlines().count(FLEXRIC.RF_FIXTURE_BEGIN), 1)
        self.assertEqual(stdout.splitlines().count(FLEXRIC.RF_FIXTURE_END), 1)
        FLEXRIC.validate_callback_output(stdout, stderr)

    def test_missing_duplicate_reversed_nested_or_nonstandalone_fixture_markers_are_rejected(self):
        stdout, stderr = self.full_callback_output()
        begin, end = FLEXRIC.RF_FIXTURE_BEGIN, FLEXRIC.RF_FIXTURE_END
        mutations = {
            "missing_begin": stdout.replace(begin + "\n", "", 1),
            "missing_end": stdout.replace(end + "\n", "", 1),
            "duplicate_begin": begin + "\n" + stdout,
            "duplicate_end": stdout + end + "\n",
            "reversed": stdout.replace(begin, "TEMP_FIXTURE_MARKER").replace(end, begin).replace("TEMP_FIXTURE_MARKER", end),
            "nested": stdout.replace(begin + "\n", begin + "\n" + begin + "\n", 1).replace(end + "\n", end + "\n" + end + "\n", 1),
            "nonstandalone": stdout.replace(begin + "\n", "CASE: " + begin + "\n", 1),
        }
        for name, mutated in mutations.items():
            with self.subTest(case=name), self.assertRaisesRegex(RuntimeError, "fixture frame"):
                FLEXRIC.validate_callback_output(mutated, stderr)

    def test_in_frame_ue_value_type_unit_identity_header_reason_and_field_checks_remain_strict(self):
        stdout, stderr = self.full_callback_output()
        trace = next(line for line in stdout.splitlines() if line.startswith("RF_TRACE "))
        mutations = {
            "wrong_ue": trace.replace("ue_f1ap_id=1007 ", "ue_f1ap_id=9999 "),
            "wrong_value": trace.replace("value=-13.125 ", "value=-1 "),
            "wrong_type": trace.replace("record_type=REAL ", "record_type=INTEGER "),
            "wrong_unit": trace.replace("unit=dBFS ", "unit=dB "),
            "wrong_identity": trace.replace("cu_du_id=1 ", "cu_du_id=2 "),
            "zero_header": trace.replace("header_time_us=123456 ", "header_time_us=0 "),
            "mixed_header": trace.replace("header_time_us=123456 ", "header_time_us=123457 "),
            "reason": trace + " reason=non_finite_REAL",
            "duplicate_field": trace + " value=-13.125",
            "malformed_field": trace + " malformed",
        }
        for name, changed in mutations.items():
            with self.subTest(case=name), self.assertRaises(RuntimeError):
                FLEXRIC.validate_callback_output(stdout.replace(trace + "\n", changed + "\n", 1), stderr)

    def test_correct_rows_outside_frame_cannot_replace_missing_or_wrong_fixture_rows(self):
        stdout, stderr = self.full_callback_output()
        trace = next(line for line in stdout.splitlines() if line.startswith("RF_TRACE "))
        for changed in ("", trace.replace("value=-13.125 ", "value=-1 ") + "\n"):
            with self.subTest(missing=not changed):
                mutated = stdout.replace(trace + "\n", changed, 1) + trace + "\n"
                with self.assertRaises(RuntimeError):
                    FLEXRIC.validate_callback_output(mutated, stderr)

    def test_missing_or_duplicate_callback_pass_marker_is_rejected(self):
        stdout, stderr = self.full_callback_output()
        for marker in FLEXRIC.CALLBACK_PASSES:
            for mutated in (stdout.replace(marker + "\n", "", 1), stdout + marker + "\n"):
                with self.subTest(marker=marker, duplicate=len(mutated) > len(stdout)):
                    with self.assertRaisesRegex(RuntimeError, "exactly one callback acceptance marker"):
                        FLEXRIC.validate_callback_output(mutated, stderr)

    def test_action_xml_requires_one_executed_correctly_named_case_without_skips(self):
        suite, name = FLEXRIC.ACTION_TEST.split(".", 1)
        testcase = f'<testcase classname="{suite}" name="{name}" status="run" result="completed"/>'
        valid = f'<testsuites tests="1"><testsuite tests="1">{testcase}</testsuite></testsuites>'
        with tempfile.TemporaryDirectory(prefix="falcon-action-xml-guards-") as directory:
            path = Path(directory) / "subscription.xml"
            path.write_text(valid)
            FLEXRIC.validate_action_xml(path)
            malformed = {
                "zero_tests": '<testsuites tests="0"><testsuite tests="0"/></testsuites>',
                "wrong_name": valid.replace(f'name="{name}"', 'name="different_case"'),
                "skipped": valid.replace('/>', '><skipped/></testcase>', 1),
                "not_run": valid.replace('status="run"', 'status="notrun"'),
                "missing_result": valid.replace(' result="completed"', ''),
                "suite_skip": valid.replace('<testsuite tests="1">', '<testsuite tests="1" skipped="1">'),
                "inconsistent_count": valid.replace('<testsuites tests="1">', '<testsuites tests="0">'),
            }
            for reason, xml in malformed.items():
                with self.subTest(reason=reason):
                    path.write_text(xml)
                    with self.assertRaises(RuntimeError):
                        FLEXRIC.validate_action_xml(path)


class OutputPathGuardTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="falcon-rf-output-guards-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.protected = [self.root / name for name in ("ocudu", "ocudu-build", "Falcon", "flexric", "flexric-build")]
        for path in self.protected:
            path.mkdir()

    def test_output_inside_each_source_build_or_falcon_repository_is_refused(self):
        for runner in (OCUDU, FLEXRIC):
            for protected in self.protected:
                with self.subTest(runner=runner.__name__, protected=protected):
                    output = protected / "evidence"
                    with self.assertRaisesRegex(RuntimeError, "overlap"):
                        runner.validate_output_path(output, self.protected)
                    self.assertFalse(output.exists())

    def test_source_ancestor_is_not_an_output_directory(self):
        for runner in (OCUDU, FLEXRIC):
            with self.subTest(runner=runner.__name__), self.assertRaisesRegex(RuntimeError, "overlap"):
                runner.validate_output_path(self.root, self.protected)

    def test_nonempty_output_is_refused_without_deleting_existing_artifacts(self):
        output = self.root / "old-output"
        output.mkdir()
        retained = output / "du-rf-indication.bin"
        retained.write_bytes(b"old fixture must never count as a fresh pass")
        for runner in (OCUDU, FLEXRIC):
            with self.subTest(runner=runner.__name__), self.assertRaisesRegex(RuntimeError, "absent or an empty directory"):
                runner.validate_output_path(output, self.protected)
        self.assertEqual(retained.read_bytes(), b"old fixture must never count as a fresh pass")

    def test_symlink_output_and_symlink_ancestor_are_refused(self):
        actual = self.root / "actual"
        actual.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        for runner in (OCUDU, FLEXRIC):
            for output in (alias, alias / "new-output"):
                with self.subTest(runner=runner.__name__, output=output), self.assertRaisesRegex(RuntimeError, "symlink"):
                    runner.validate_output_path(output, self.protected)
        self.assertEqual(list(actual.iterdir()), [])

    def test_new_or_empty_external_output_is_accepted_without_creation(self):
        absent = self.root / "new-output"
        empty = self.root / "empty-output"
        empty.mkdir()
        for runner in (OCUDU, FLEXRIC):
            with self.subTest(runner=runner.__name__):
                self.assertEqual(runner.validate_output_path(absent, self.protected), absent)
                self.assertFalse(absent.exists())
                self.assertEqual(runner.validate_output_path(empty, self.protected), empty)
        self.assertEqual(list(empty.iterdir()), [])


class ProcessAndCompilerGuardTest(unittest.TestCase):
    def test_running_process_or_pgrep_error_blocks_compilation_for_every_service(self):
        for runner, build_call in ((OCUDU, OCUDU.compile_or_link), (FLEXRIC, FLEXRIC.run_build)):
            for name in ("odu", "nearRT-RIC", "xapp"):
                for returncode in (0, 2):
                    def pgrep(command, **kwargs):
                        code = returncode if command[-1] == name else 1
                        return subprocess.CompletedProcess(command, code,
                                                           stdout="123 running service\n" if code == 0 else "",
                                                           stderr="pgrep failed\n" if code == 2 else "")
                    with self.subTest(runner=runner.__name__, service=name, exit_code=returncode):
                        with mock.patch.object(runner.subprocess, "run", side_effect=pgrep), mock.patch.object(runner, "run") as compile_call:
                            with self.assertRaisesRegex(RuntimeError, "Build blocked|Cannot establish"):
                                build_call(["/never-run", "input.cpp"], {})
                            compile_call.assert_not_called()

    def test_compiler_command_is_nice_19_only_after_all_three_process_checks_pass(self):
        env = {"TMPDIR": "/unused-guard-test-temp"}
        for runner, build_call in ((OCUDU, OCUDU.compile_or_link), (FLEXRIC, FLEXRIC.run_build)):
            with self.subTest(runner=runner.__name__):
                with mock.patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "")) as pgrep:
                    with mock.patch.object(runner, "run") as compile_call:
                        build_call(["/never-run", "-c", "input.cpp", "-o", "output.o"], env)
                        self.assertEqual([call.args[0] for call in pgrep.call_args_list],
                                         [["pgrep", "-a", "odu"], ["pgrep", "-a", "nearRT-RIC"], ["pgrep", "-a", "xapp"]])
                        compile_call.assert_called_once_with(["nice", "-n", "19", "/never-run", "-c", "input.cpp", "-o", "output.o"], env=env)


if __name__ == "__main__":
    unittest.main()
