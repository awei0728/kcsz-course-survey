"""Offline adapter checks; not TeachClaw, message delivery, or WJX tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from survey_data import SurveyStore  # noqa: E402
from teachclaw_entry import run_request  # noqa: E402


class TeachClawEntryTests(unittest.TestCase):
    def test_empty_and_unknown_project_return_complete_catalog_without_writing(self):
        expected = [project["name"] for project in SurveyStore().catalog["projects"]]
        with TemporaryDirectory() as directory:
            output = Path(directory) / "不应创建"
            for value in (None, "", "   ", "心理韧性", "大学生创造力问卷"):
                with self.subTest(project=value):
                    envelope, code = run_request(value, output_dir=output)
                    self.assertEqual(code, 2)
                    self.assertFalse(envelope["ok"])
                    self.assertEqual(envelope["error"]["code"], "PROJECT_NOT_FOUND")
                    self.assertEqual([p["name"] for p in envelope["error"]["candidates"]], expected)
                    self.assertEqual(len(envelope["error"]["candidates"]), 12)
                    for number, name in enumerate(expected, 1):
                        self.assertIn(f"{number}. {name}", envelope["message"])
                    self.assertIn("生成课程思政调查问卷 --创造力", envelope["message"])
                    self.assertIn("生成课程思政调查问卷 --爱国主义", envelope["message"])
                    self.assertEqual(envelope["artifacts"], [])
                    self.assertEqual(envelope["model_trace"], [])
                    self.assertFalse(output.exists())

    def test_authorized_patriotism_alias_preserves_source_and_real_artifacts(self):
        with TemporaryDirectory() as directory:
            envelope, code = run_request("爱国主义", request_id="alias-01", output_dir=directory)
            self.assertEqual(code, 0)
            data = envelope["summary"]["content"]["data"]
            self.assertEqual(data["questionnaire_id"], "patriotism--original")
            self.assertEqual(data["project_name"], "爱国主义态度")
            self.assertEqual(data["attachment_filename"], "爱国主义问卷.txt")
            self.assertEqual(envelope["request_id"], "alias-01")
            self.assertEqual(data["source"]["volume"], 1)
            self.assertEqual(data["user_import_feedback"]["status"], "pending_user_feedback")
            self.assertEqual(data["verification"]["wjx_import"], "pending_user_validation")
            self.assertEqual(len(envelope["artifacts"]), 3)
            for artifact in envelope["artifacts"]:
                self.assertTrue(Path(artifact["path"]).is_file())
            manifest = json.loads(Path(envelope["artifacts"][2]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"], data["counts"])
            self.assertEqual(manifest["source"], data["source"])

    def test_multiversion_missing_and_unknown_version_do_not_write(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "不应创建"
            for version, expected in ((None, "VERSION_REQUIRED"), ("original", "VERSION_NOT_FOUND")):
                envelope, code = run_request("批判性思维", version, output_dir=output)
                self.assertEqual(code, 2)
                self.assertEqual(envelope["error"]["code"], expected)
                data = envelope["summary"]["content"]["data"]
                self.assertEqual(data["project_id"], "critical-thinking")
                self.assertEqual(data["versions"], ["A", "B"])
                self.assertEqual([candidate["version_id"] for candidate in envelope["error"]["candidates"]],
                                 ["A", "B"])
                self.assertEqual(envelope["artifacts"], [])
                self.assertFalse(output.exists())

    def test_explicit_b_version_is_respected(self):
        with TemporaryDirectory() as directory:
            envelope, code = run_request("critical-thinking", "B", output_dir=directory)
            self.assertEqual(code, 0)
            data = envelope["summary"]["content"]["data"]
            self.assertEqual(data["questionnaire_id"], "critical-thinking--B")
            self.assertEqual(data["attachment_filename"], "批判性思维问卷_B卷.txt")
            self.assertIn("B卷", envelope["message"])
            self.assertEqual(data["user_import_feedback"]["status"], "pending_user_feedback")

    def test_engineering_counts_and_current_text_adaptation_survive(self):
        with TemporaryDirectory() as directory:
            envelope, code = run_request("工程伦理", output_dir=directory)
            self.assertEqual(code, 0)
            data = envelope["summary"]["content"]["data"]
            self.assertEqual(data["counts"]["export_question_count"], 11)
            self.assertEqual(data["counts"]["independent_answer_items"], 19)
            self.assertEqual(data["counts"]["conditional_auxiliary_fields"], 0)
            self.assertEqual(data["user_import_feedback"]["status"], "user_feedback_passed")
            self.assertFalse(data["user_import_feedback"]["current_artifact_import_verified"])
            self.assertEqual(data["verification"]["teach_claw"], "not_verified")
            text = Path(envelope["artifacts"][0]["path"]).read_text(encoding="utf-8")
            self.assertIn("【A】", text)
            self.assertIn("代码之间用中文逗号分隔", text)
            self.assertNotIn("[排序题]", text)
            self.assertIn("人工核对", envelope["message"])

    def test_cli_from_unrelated_directory_emits_utf8_and_uses_actual_resources(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "中文交付"
            environment = os.environ.copy()
            environment.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
            process = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "teachclaw_entry.py"),
                 "--project", "创造力", "--request-id", "other-cwd", "--output-dir", str(output)],
                cwd=directory, env=environment, capture_output=True, text=True, encoding="utf-8",
                timeout=60, check=False)
            self.assertEqual(process.returncode, 0, process.stderr)
            envelope = json.loads(process.stdout)
            data = envelope["summary"]["content"]["data"]
            self.assertEqual(data["questionnaire_id"], "creativity--original")
            self.assertEqual(data["attachment_filename"], "创造力问卷.txt")
            self.assertEqual(data["user_import_feedback"]["status"], "user_feedback_passed")
            self.assertEqual(envelope["model_trace"], [])
            for artifact in envelope["artifacts"]:
                self.assertTrue(Path(artifact["path"]).is_relative_to(output))
                self.assertTrue(Path(artifact["path"]).is_file())

    def test_invalid_parameters_remain_structured_without_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "不应创建"
            envelope, code = run_request("创造力\n额外内容", output_dir=output)
            self.assertEqual(code, 2)
            self.assertEqual(envelope["error"]["code"], "INVALID_REQUEST")
            self.assertEqual(envelope["artifacts"], [])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
