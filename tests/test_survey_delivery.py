"""Physical central-delivery checks; never a survey-platform import test."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import survey_delivery
from survey_data import DataError


class SurveyDeliveryTests(unittest.TestCase):
    def test_full_delivery_has_16_real_utf8_files_matching_manifests_and_indexes(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "集中中文目录"
            first = survey_delivery.export_all_candidates(output, "delivery-test-01")
            directory = Path(first["output_directory"])
            index = json.loads((directory / "交付清单.json").read_text(encoding="utf-8"))
            self.assertEqual(index["coverage"], {"projects": 12, "source_versions": 16, "generated": 16})
            self.assertEqual(len(list(directory.glob("*.txt"))), 16)
            self.assertFalse((directory / "_current_exports").exists())
            self.assertEqual(len(index["entries"]), 16)
            self.assertEqual(len({e["questionnaire_id"] for e in index["entries"]}), 16)
            self.assertEqual(sum(e["counts"]["export_question_count"] for e in index["entries"]), 89)
            self.assertEqual(sum(e["counts"]["source_mapping_count"] for e in index["entries"]), 387)
            self.assertTrue((directory / "创造力_原版_待导入核对.txt").is_file())
            self.assertTrue((directory / "学习自我效能感_A卷_待导入核对.txt").is_file())
            self.assertTrue((directory / "学生核心素养_原版_待导入核对.txt").is_file())
            self.assertTrue((directory / "工程伦理_作答规则补全_基础题型适配_待导入核对.txt").is_file())
            for entry in index["entries"]:
                with self.subTest(version=entry["questionnaire_id"]):
                    manifest = json.loads(Path(entry["manifest_path"]).read_text(encoding="utf-8"))
                    self.assertEqual(manifest["questionnaire_id"], entry["questionnaire_id"])
                    self.assertEqual(manifest["counts"], entry["counts"])
                    self.assertEqual(manifest["presentation_rules_sha256"], index["presentation_rules_sha256"])
                    self.assertEqual(manifest["files"][0]["path"], entry["txt_path"])
                    self.assertEqual(manifest["verification"]["wjx_import"], "pending_user_validation")
                    self.assertTrue(manifest["delivery"]["identity_and_primary_sha256_checked"])
            original_files = {a["path"]: Path(a["path"]).read_bytes() for a in first["artifacts"]}
            for artifact in first["artifacts"]:
                path = Path(artifact["path"])
                self.assertTrue(path.is_relative_to(directory))
                path.read_text(encoding="utf-8")
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"])
                self.assertNotIn(".partial-", str(path))
            second = survey_delivery.export_all_candidates(output, "delivery-test-02")
            self.assertNotEqual(first["output_directory"], second["output_directory"])
            for path, data in original_files.items():
                self.assertEqual(Path(path).read_bytes(), data)
            self.assertEqual(len(list(output.iterdir())), 2)

    def test_producer_identity_mismatch_rolls_back_whole_delivery(self):
        original = survey_delivery.export_questionnaire

        def wrong_identity(*args, **kwargs):
            result = original(*args, **kwargs)
            result["project_id"] = "a-different-project"
            return result

        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            sentinel = output / "旧交付.txt"
            sentinel.write_text("保留", encoding="utf-8")
            with patch.object(survey_delivery, "export_questionnaire", wrong_identity):
                with self.assertRaises(DataError) as caught:
                    survey_delivery.export_all_candidates(output)
            self.assertEqual(caught.exception.code, "INVALID_DATA")
            self.assertEqual(list(output.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "保留")

    def test_copy_failure_never_exposes_a_partial_final_directory(self):
        original = survey_delivery._copy_file_exact
        calls = []

        def broken_copy(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("offline simulated delivery copy failure")
            original(source, destination)

        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            with patch.object(survey_delivery, "_copy_file_exact", broken_copy):
                with self.assertRaises(DataError) as caught:
                    survey_delivery.export_all_candidates(output)
            self.assertEqual(caught.exception.code, "OUTPUT_WRITE_FAILED")
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
