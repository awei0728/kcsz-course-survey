"""Offline routing checks for candidate exports and original-version compatibility."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import survey_export  # noqa: E402
import teachclaw_entry  # noqa: E402
from survey_data import DataError, make_result_envelope  # noqa: E402


class CandidateEntryTests(unittest.TestCase):
    def _candidate_module(self, *, blocked=False):
        module = ModuleType("candidate_survey")
        envelope = make_result_envelope(
            "export", {"selection": {"mode": "single_all"}, "artifacts": []},
            DataError("SURVEY_BLOCKED", "所选候选题尚未批准施测。") if blocked else None,
            request_id="candidate-request")
        module.run_request = Mock(return_value=(envelope, 4 if blocked else 0))
        return module, envelope

    def _run_cli(self, entry, args, module):
        stream = StringIO()
        with patch.dict(sys.modules, {"candidate_survey": module}), redirect_stdout(stream):
            code = entry.main(args)
        return code, json.loads(stream.getvalue())

    def test_public_exporter_passes_repeated_goals_and_format(self):
        module, expected = self._candidate_module()
        code, envelope = self._run_cli(survey_export, [
            "--goal", "创造力", "--goal", "批判性思维", "--format", "chaoxing",
            "--purpose", "review", "--dimensions-file", "维度.json",
            "--request-id", "entry-01", "--output-dir", "候选输出",
        ], module)
        self.assertEqual(code, 0)
        self.assertEqual(envelope, expected)
        module.run_request.assert_called_once_with(
            goals=["创造力", "批判性思维"], output_format="chaoxing", output_dir="候选输出",
            request_id="entry-01", purpose="review", dimensions_path="维度.json",
            question_count=None, seed=0)

    def test_explicit_format_selects_candidate_workflow_for_single_project(self):
        for entry in (survey_export, teachclaw_entry):
            with self.subTest(entry=entry.__name__):
                module, expected = self._candidate_module()
                code, envelope = self._run_cli(entry, [
                    "--project", "创造力", "--format", "wjx", "--request-id", "single-01",
                ], module)
                self.assertEqual((code, envelope), (0, expected))
                keywords = module.run_request.call_args.kwargs
                self.assertEqual(keywords["goals"], ["创造力"])
                self.assertEqual(keywords["output_format"], "wjx")
                self.assertEqual(keywords["purpose"], "review")
                self.assertEqual(keywords["request_id"], "single-01")

    def test_goal_only_defaults_to_wjx_review_without_requiring_project(self):
        for entry in (survey_export, teachclaw_entry):
            with self.subTest(entry=entry.__name__):
                module, _ = self._candidate_module()
                code, envelope = self._run_cli(entry, ["--goal", "创造力"], module)
                self.assertEqual(code, 0)
                self.assertTrue(envelope["ok"])
                self.assertEqual(module.run_request.call_args.kwargs["goals"], ["创造力"])
                self.assertEqual(module.run_request.call_args.kwargs["output_format"], "wjx")

    def test_public_exporter_rejects_incompatible_arguments_before_delegation(self):
        for extra in (["--version", "A"], ["--source-item-id", "q001"],
                      ["--course", "课程"], ["--scenario", "前测"], ["--project", "创造力"]):
            with self.subTest(extra=extra):
                module, _ = self._candidate_module()
                code, envelope = self._run_cli(survey_export, ["--goal", "创造力", *extra], module)
                self.assertEqual(code, 2)
                self.assertEqual(envelope["error"]["code"], "INVALID_REQUEST")
                self.assertEqual(envelope["artifacts"], [])
                module.run_request.assert_not_called()

    def test_teachclaw_rejects_source_version_and_mixed_goal_parameters(self):
        for keywords in ({"version": "A"}, {"project": "创造力"}):
            with self.subTest(keywords=keywords):
                module, _ = self._candidate_module()
                with patch.dict(sys.modules, {"candidate_survey": module}):
                    envelope, code = teachclaw_entry.run_request(goals=["创造力"], **keywords)
                self.assertEqual(code, 2)
                self.assertEqual(envelope["error"]["code"], "INVALID_REQUEST")
                self.assertEqual(envelope["artifacts"], [])
                module.run_request.assert_not_called()

    def test_teachclaw_candidate_api_forwards_store_without_legacy_catalog_lookup(self):
        module, expected = self._candidate_module()
        store = object()
        with patch.dict(sys.modules, {"candidate_survey": module}):
            envelope, code = teachclaw_entry.run_request(
                goals=["创造力", "文化认同"], output_format="chaoxing", purpose="review",
                dimensions_path="维度.json", output_dir="候选输出", request_id="api-01", store=store)
        self.assertEqual((envelope, code), (expected, 0))
        module.run_request.assert_called_once_with(
            goals=["创造力", "文化认同"], output_format="chaoxing", output_dir="候选输出",
            request_id="api-01", purpose="review", dimensions_path="维度.json", store=store,
            question_count=None, seed=0)

    def test_question_count_and_seed_forwarded_by_both_entry_clis(self):
        for entry in (survey_export, teachclaw_entry):
            with self.subTest(entry=entry.__name__):
                module, expected = self._candidate_module()
                code, envelope = self._run_cli(entry, [
                    "--goal", "爱国主义态度", "--goal", "创造力", "--goal", "学习自我效能感",
                    "--question-count", "10", "--seed", "23", "--format", "chaoxing",
                ], module)
                self.assertEqual((code, envelope), (0, expected))
                self.assertEqual(module.run_request.call_args.kwargs["question_count"], 10)
                self.assertEqual(module.run_request.call_args.kwargs["seed"], 23)

    def test_question_count_with_single_project_selects_candidate_path(self):
        for entry in (survey_export, teachclaw_entry):
            with self.subTest(entry=entry.__name__):
                module, expected = self._candidate_module()
                code, envelope = self._run_cli(entry, [
                    "--project", "创造力", "--question-count", "8",
                ], module)
                self.assertEqual((code, envelope), (0, expected))
                self.assertEqual(module.run_request.call_args.kwargs["goals"], ["创造力"])
                self.assertEqual(module.run_request.call_args.kwargs["question_count"], 8)
                self.assertEqual(module.run_request.call_args.kwargs["seed"], 0)

    def test_seed_without_count_is_not_ignored_or_forwarded(self):
        for entry in (survey_export, teachclaw_entry):
            with self.subTest(entry=entry.__name__):
                module, _ = self._candidate_module()
                code, envelope = self._run_cli(entry, ["--project", "创造力", "--seed", "0"], module)
                self.assertEqual(code, 2)
                self.assertEqual(envelope["error"]["code"], "INVALID_REQUEST")
                self.assertEqual(envelope["artifacts"], [])
                module.run_request.assert_not_called()

    def test_teachclaw_api_forwards_explicit_count_and_seed(self):
        module, expected = self._candidate_module()
        with patch.dict(sys.modules, {"candidate_survey": module}):
            envelope, code = teachclaw_entry.run_request("创造力", question_count=8, seed=12)
        self.assertEqual((envelope, code), (expected, 0))
        self.assertEqual(module.run_request.call_args.kwargs["goals"], ["创造力"])
        self.assertEqual(module.run_request.call_args.kwargs["question_count"], 8)
        self.assertEqual(module.run_request.call_args.kwargs["seed"], 12)

    def test_count_flags_reject_legacy_version_and_invalid_cli_integer(self):
        for entry in (survey_export, teachclaw_entry):
            for extra in (["--version", "original"], ["--question-count", "abc"]):
                with self.subTest(entry=entry.__name__, extra=extra):
                    module, _ = self._candidate_module()
                    argv = ["--project", "创造力", "--question-count", "8", *extra]
                    code, envelope = self._run_cli(entry, argv, module)
                    self.assertEqual(code, 2)
                    self.assertEqual(envelope["error"]["code"], "INVALID_REQUEST")
                    module.run_request.assert_not_called()

    def test_real_entry_clis_generate_identical_ten_question_selection_in_both_formats(self):
        reference_ids = None
        with TemporaryDirectory() as directory:
            for entry in (survey_export, teachclaw_entry):
                for output_format in ("wjx", "chaoxing"):
                    with self.subTest(entry=entry.__name__, output_format=output_format):
                        completed = subprocess.run(
                            [sys.executable, "-B", entry.__file__, "--goal", "爱国主义态度",
                             "--goal", "创造力", "--goal", "学习自我效能感", "--format", output_format,
                             "--question-count", "10", "--seed", "9", "--output-dir", directory],
                            cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=30)
                        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                        envelope = json.loads(completed.stdout)
                        self.assertTrue(envelope["ok"])
                        self.assertEqual(envelope["model_trace"], [])
                        data = envelope["summary"]["content"]["data"]
                        self.assertEqual(data["counts"]["candidate_count"], 10)
                        self.assertEqual(data["counts"]["core_count"], 10)
                        self.assertEqual(data["counts"]["backup_count"], 0)
                        self.assertEqual(data["selection"]["question_count_requested"], 10)
                        self.assertEqual(data["selection"]["sampling_seed"], 9)
                        identities = data["selection"]["candidate_ids"]
                        if reference_ids is None:
                            reference_ids = identities
                        self.assertEqual(identities, reference_ids)
                        paths = {artifact["role"]: Path(artifact["path"]) for artifact in data["artifacts"]}
                        manifest = json.loads(paths["mapping"].read_text(encoding="utf-8"))
                        self.assertEqual(len(manifest["candidates"]), 10)
                        self.assertEqual(len({c["project_slug"] for c in manifest["candidates"]}), 3)
                        if output_format == "wjx":
                            self.assertEqual(paths["primary"].read_text(encoding="utf-8").count("[单选题]"), 10)
                        else:
                            self.assertEqual(paths["primary"].read_bytes()[:8], bytes.fromhex("d0cf11e0a1b11ae1"))

    def test_candidate_error_envelope_and_exit_code_are_preserved(self):
        for entry in (survey_export, teachclaw_entry):
            with self.subTest(entry=entry.__name__):
                module, expected = self._candidate_module(blocked=True)
                code, envelope = self._run_cli(entry, ["--goal", "创造力", "--purpose", "survey"], module)
                self.assertEqual((code, envelope), (4, expected))
                self.assertFalse(envelope["ok"])
                self.assertEqual(envelope["artifacts"], [])

    def test_invalid_candidate_cli_choice_uses_structured_error(self):
        for entry in (survey_export, teachclaw_entry):
            with self.subTest(entry=entry.__name__):
                module, _ = self._candidate_module()
                code, envelope = self._run_cli(entry, ["--goal", "创造力", "--format", "csv"], module)
                self.assertEqual(code, 2)
                self.assertEqual(envelope["error"]["code"], "INVALID_REQUEST")
                module.run_request.assert_not_called()

    def test_original_teachclaw_positional_api_stays_on_source_version_path(self):
        module, _ = self._candidate_module()
        with TemporaryDirectory() as directory, patch.dict(sys.modules, {"candidate_survey": module}):
            envelope, code = teachclaw_entry.run_request("创造力", None, "legacy-01", directory)
            self.assertEqual(code, 0)
            data = envelope["summary"]["content"]["data"]
            self.assertEqual(data["questionnaire_id"], "creativity--original")
            self.assertEqual(data["attachment_filename"], "创造力问卷.txt")
            self.assertEqual(envelope["request_id"], "legacy-01")
            self.assertEqual(len(envelope["artifacts"]), 3)
            module.run_request.assert_not_called()

    def test_original_exporter_cli_stays_on_source_version_path(self):
        module, _ = self._candidate_module()
        with TemporaryDirectory() as directory:
            code, envelope = self._run_cli(survey_export, [
                "--project", "creativity", "--version", "original", "--output-dir", directory,
            ], module)
            self.assertEqual(code, 0)
            self.assertEqual(envelope["summary"]["content"]["data"]["questionnaire_id"],
                             "creativity--original")
            module.run_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
