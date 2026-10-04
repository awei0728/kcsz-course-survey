"""Offline checks for catalogue selection and data-integrity boundaries."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "survey_data.py"
sys.path.insert(0, str(SCRIPT.parent))
from survey_data import DataError, SurveyStore, read_json, validate_questionnaire  # noqa: E402


class SurveyDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.creativity = json.loads(
            (SKILL_ROOT / "data" / "questionnaires" / "creativity--original.json")
            .read_text(encoding="utf-8")
        )

    def setUp(self):
        self.store = SurveyStore()

    def assert_data_error(self, code, operation):
        with self.assertRaises(DataError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def ab_project(self):
        return next(
            project for project in self.store.catalog["projects"]
            if len(project["versions"]) > 1
        )

    def run_cli(self, cwd, *arguments, script=SCRIPT):
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-B", str(script), *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        return completed, json.loads(completed.stdout)

    def isolated_creativity_store(self, root):
        """Copy one actual version into disposable paths, never mutate the library."""
        data_root = root / "data"
        (data_root / "questionnaires").mkdir(parents=True)
        (root / "docs").mkdir()
        document = deepcopy(self.creativity)
        catalog = deepcopy(self.store.catalog)
        catalog["projects"] = [
            project for project in catalog["projects"]
            if project["id"] == document["project_id"]
        ]
        catalog["sources"] = [
            source for source in catalog["sources"]
            if source["filename"] == document["source"]["filename"]
        ]
        catalog["coverage"] = {"projects": 1, "versions": 1}
        version = catalog["projects"][0]["versions"][0]
        (data_root / version["file"]).write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8"
        )
        (data_root / "catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False), encoding="utf-8"
        )
        filename = document["source"]["filename"]
        shutil.copyfile(SKILL_ROOT / "docs" / filename, root / "docs" / filename)
        return SurveyStore(data_root)

    def test_unknown_project_and_explicit_version_are_not_guessed(self):
        project = self.ab_project()
        cases = [
            ("PROJECT_NOT_FOUND", lambda: self.store.find_project("not-a-recorded-project")),
            ("VERSION_REQUIRED", lambda: self.store.read_version(project["id"])),
            ("VERSION_NOT_FOUND", lambda: self.store.read_version(project["id"], "not-a-version")),
        ]
        for code, operation in cases:
            with self.subTest(code=code):
                error = self.assert_data_error(code, operation)
                self.assertTrue(error.candidates)

    def test_duplicate_alias_requires_project_identity(self):
        projects = self.store.catalog["projects"]
        first, second = projects[:2]
        shared_alias = "测试用重复别名"
        first["aliases"].append(shared_alias)
        second["aliases"].append(shared_alias)
        error = self.assert_data_error(
            "AMBIGUOUS_PROJECT", lambda: self.store.find_project(shared_alias)
        )
        self.assertEqual({candidate["id"] for candidate in error.candidates},
                         {first["id"], second["id"]})
        self.assertEqual(self.store.find_project(first["id"])["id"], first["id"])

    def test_validate_keeps_confirmation_status_separate_from_structure(self):
        result = self.store.validate_all()
        self.assertTrue(result["structure_valid"])
        self.assertEqual((result["projects"], result["versions"]), (12, 16))
        engineering = next(
            summary for summary in result["questionnaires"]
            if summary["project_id"] == "engineering-ethics"
        )
        self.assertEqual(engineering["review_status"], "needs_confirmation")
        self.assertFalse(engineering["eligible_for_generation"])
        self.assertTrue(engineering["blocking_issues"])
        self.assertGreater(result["review_counts"].get("needs_confirmation", 0), 0)
        for summary in result["questionnaires"]:
            if summary["blocking_issues"]:
                self.assertEqual(summary["review_status"], "needs_confirmation")
                self.assertFalse(summary["eligible_for_generation"])

    def test_structural_mutations_cannot_pass_validation(self):
        def duplicate_id(document):
            document["items"][1]["id"] = document["items"][0]["id"]

        def unresolved_but_verified(document):
            document["issues"][0].update(category="blocking", blocking=True, resolution=None)

        mutations = [
            ("RATING_OPTIONS", lambda document: document["items"][0]["response"]["options"].pop()),
            ("DUPLICATE_ITEM_ID", duplicate_id),
            ("BLOCKER_STATUS_MISMATCH", unresolved_but_verified),
            ("SCORING_MAPPING", lambda document: document["scoring"].update(
                reverse_mapping=[{"from": 1, "to": float("nan")}]
            )),
        ]
        for expected, mutate in mutations:
            with self.subTest(code=expected):
                document = deepcopy(self.creativity)
                mutate(document)
                self.assertIn(expected, {error["code"] for error in validate_questionnaire(document)})

    def test_teacher_information_does_not_leak_into_student_content(self):
        document = deepcopy(self.creativity)
        item = document["items"][0]
        marker = "（反向检测题）"
        item["raw_text"] += marker
        item["student_text"] += marker
        item["reverse"].update(marked=True, raw_marker=marker,
                               source=deepcopy(item["source"]), reason=None)
        item["teacher_annotations"].append({
            "text": marker, "kind": "reverse", "visibility": "teacher",
            "source": deepcopy(item["source"]),
        })
        self.assertIn("TEACHER_MARKER_LEAK",
                      {error["code"] for error in validate_questionnaire(document)})

        document = deepcopy(self.creativity)
        document["instructions"].append({
            "id": "test-teacher-only", "role": "teacher",
            "raw_text": "仅供教师的计分说明", "student_text": "仅供教师的计分说明",
            "source": deepcopy(document["title"]["source"]),
        })
        self.assertIn("TEACHER_TEXT_LEAK",
                      {error["code"] for error in validate_questionnaire(document)})

    def test_wrong_source_shape_returns_errors_instead_of_crashing(self):
        document = deepcopy(self.creativity)
        document["source"] = []
        self.assertTrue(validate_questionnaire(document))

    def test_catalog_identity_and_missing_source_are_invalid_data(self):
        for case, expected in [("identity", "INDEX_IDENTITY_MISMATCH"),
                               ("missing-source", "SOURCE_MISSING")]:
            with self.subTest(case=case), TemporaryDirectory() as temporary:
                root = Path(temporary)
                store = self.isolated_creativity_store(root)
                if case == "identity":
                    store.catalog["projects"][0]["versions"][0]["questionnaire_id"] = "wrong--original"
                else:
                    (root / "docs" / self.creativity["source"]["filename"]).unlink()
                error = self.assert_data_error("INVALID_DATA", store.validate_all)
                self.assertIn(expected, {detail["code"] for detail in error.details})

    def test_cli_reads_resources_from_an_unrelated_working_directory(self):
        with TemporaryDirectory() as temporary:
            completed, envelope = self.run_cli(
                temporary, "--request-id", "offline-cwd-check", "read", "creativity"
            )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(envelope["status"], "completed")
            self.assertEqual(envelope["request_id"], "offline-cwd-check")
            self.assertEqual(envelope["summary"]["content"]["operation"], "read")
            self.assertEqual(envelope["summary"]["content"]["data"], self.creativity)
            self.assertIsNone(envelope["error"])
            self.assertEqual(envelope["artifacts"], [])
            self.assertEqual(envelope["model_trace"], [])
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_cli_selection_errors_have_json_envelopes_and_exit_two(self):
        project = self.ab_project()
        cases = [
            (["find", "not-a-recorded-project"], "PROJECT_NOT_FOUND"),
            (["read", project["id"]], "VERSION_REQUIRED"),
            (["read", project["id"], "--version", "not-a-version"], "VERSION_NOT_FOUND"),
        ]
        with TemporaryDirectory() as temporary:
            for arguments, expected in cases:
                with self.subTest(code=expected):
                    completed, envelope = self.run_cli(temporary, *arguments)
                    self.assertEqual(completed.returncode, 2)
                    self.assertEqual(envelope["status"], "failed")
                    self.assertEqual(envelope["error"]["code"], expected)
                    self.assertIsNone(envelope["summary"]["content"]["data"])

    def test_invalid_catalog_has_json_envelope_and_exit_four(self):
        invalid_json = [
            '{"schema_version": 1, "schema_version": 1}',
            '{"schema_version": NaN}',
            '{"schema_version": Infinity}',
            '{"schema_version": -Infinity}',
            '{"schema_version": 1, "extra": 1e999}',
        ]
        for text in invalid_json:
            with self.subTest(json=text), TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "scripts").mkdir()
                (root / "data").mkdir()
                script = root / "scripts" / SCRIPT.name
                shutil.copyfile(SCRIPT, script)
                (root / "data" / "catalog.json").write_text(text, encoding="utf-8")
                self.assert_data_error("INVALID_DATA",
                                       lambda: read_json(root / "data" / "catalog.json"))
                completed, envelope = self.run_cli(root, "validate", script=script)
                self.assertEqual(completed.returncode, 4)
                self.assertEqual(envelope["status"], "failed")
                self.assertEqual(envelope["error"]["code"], "INVALID_DATA")
                self.assertIsNone(envelope["summary"]["content"]["data"])


if __name__ == "__main__":
    unittest.main()
