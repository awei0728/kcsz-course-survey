"""Real candidate composition and output transactions; no external services."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from candidate_data import CandidateStore
from candidate_survey import OPTIONS, export_candidate_survey, render_wjx, run_request
from survey_data import DataError


class CandidateSurveyTests(unittest.TestCase):
    def configured_store(self, directory):
        # Synthetic assignments exercise constraints; they are never production defaults.
        ids = [p["id"] for p in CandidateStore().list_projects()]
        config = {"schema_version": 1, "status": "confirmed", "evidence": "test fixture only",
                  "dimensions": [{"id": f"test-{n}", "name": f"测试维度{n}",
                                  "project_ids": ids[n * 6:(n + 1) * 6]} for n in range(3)]}
        path = Path(directory) / "dimensions.json"
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        return CandidateStore(dimensions_path=path)

    def test_single_goal_contains_all_twelve_candidates_in_both_banks(self):
        with TemporaryDirectory() as directory:
            result = export_candidate_survey(["创造力"], output_dir=directory)
            self.assertEqual(result["counts"], {"project_count": 1, "candidate_count": 12,
                             "core_count": 6, "backup_count": 6, "export_question_count": 12})
            text = Path(result["artifacts"][0]["path"]).read_text(encoding="utf-8")
            blocks = text.strip().split("\n\n")[1:]
            self.assertEqual(len(blocks), 12)
            expected = [c for c in CandidateStore().candidates if c["project_slug"] == "creativity"]
            for number, (block, candidate) in enumerate(zip(blocks, expected), 1):
                self.assertEqual(block.splitlines(), [f"{number}. {candidate['item_text_zh']}[单选题]", *OPTIONS])
            self.assertFalse(result["release_eligible"])
            self.assertFalse(result["verification"]["automatic_scoring"])

    def test_multiple_goals_use_core_only_with_continuous_numbering_and_full_provenance(self):
        with TemporaryDirectory() as directory:
            store = self.configured_store(directory)
            result = export_candidate_survey(["learning-self-efficacy", "critical-thinking"],
                                             output_dir=Path(directory) / "output", store=store)
            self.assertEqual(result["counts"]["candidate_count"], 26)
            self.assertEqual(result["counts"]["backup_count"], 0)
            paths = {a["role"]: Path(a["path"]) for a in result["artifacts"]}
            manifest = json.loads(paths["mapping"].read_text(encoding="utf-8"))
            self.assertEqual([m["export_question_number"] for m in manifest["mapping"]], list(range(1, 27)))
            self.assertEqual(manifest["counts"], result["counts"])
            self.assertEqual(len(manifest["mapping"]), len(manifest["candidates"]))
            self.assertTrue(all(c["bank"] == "核心候选题库" for c in manifest["candidates"]))
            for mapped, candidate in zip(manifest["mapping"], manifest["candidates"]):
                self.assertEqual(mapped["project_id"], candidate["project_id"])
                self.assertEqual(mapped["project_slug"], candidate["project_slug"])
            for source in manifest["source_records"]:
                self.assertEqual(len([k for k in source if k.startswith("raw_")]), 30)
            for candidate in manifest["candidates"]:
                self.assertEqual(candidate["release_eligible"], "否")
                for field in ("text_approval", "bank_approval", "merge_approval", "scoring_approval", "scale_approval"):
                    self.assertTrue(candidate[field])
            primary = next(f for f in manifest["files"] if f["role"] == "primary")
            self.assertEqual(primary["sha256"], hashlib.sha256(paths["primary"].read_bytes()).hexdigest())
            self.assertEqual(len(re.findall(r"(?m)^\d+\. .*\[单选题\]$", paths["primary"].read_text(encoding="utf-8"))), 26)

    def test_learning_platform_is_real_xls_and_same_selected_set(self):
        with TemporaryDirectory() as directory:
            result = export_candidate_survey(["creativity"], "chaoxing", output_dir=directory)
            primary = Path(result["artifacts"][0]["path"])
            self.assertEqual(primary.suffix, ".xls")
            self.assertEqual(primary.read_bytes()[:8], bytes.fromhex("d0cf11e0a1b11ae1"))
            manifest = json.loads(Path(result["artifacts"][2]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"]["export_question_count"], 12)
            self.assertIsNone(manifest["format_profile"]["correct_answers"])
            self.assertEqual(manifest["response_options"], list(OPTIONS))
            self.assertFalse(manifest["actual_import_verified"])

    def test_single_goal_sized_subset_can_contain_both_banks_and_keeps_selected_provenance(self):
        with TemporaryDirectory() as directory:
            result = export_candidate_survey(["创造力"], output_dir=directory, question_count=8, seed=13)
            self.assertEqual(result["counts"]["candidate_count"], 8)
            self.assertGreater(result["counts"]["core_count"], 0)
            self.assertGreater(result["counts"]["backup_count"], 0)
            policy = result["selection"]
            self.assertEqual(policy["question_count_requested"], 8)
            self.assertEqual(policy["available_candidate_count"], 12)
            self.assertEqual(policy["bank_policy"], "core_and_backup")
            paths = {a["role"]: Path(a["path"]) for a in result["artifacts"]}
            manifest = json.loads(paths["mapping"].read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["mapping"]), 8)
            self.assertEqual(len(manifest["source_records"]), 8)
            expected_source_ids = {sid for c in manifest["candidates"] for sid in c["source_record_ids"].split("|")}
            self.assertEqual({s["source_record_id"] for s in manifest["source_records"]}, expected_source_ids)
            self.assertIn("抽取8题", paths["teacher"].read_text(encoding="utf-8"))
            self.assertTrue(all(c["release_eligible"] == "否" for c in manifest["candidates"]))

    def test_sized_three_dimension_exports_match_and_contain_only_core_items(self):
        from test_chaoxing_export import read_xls
        goals = ["爱国主义态度", "创造力", "学习自我效能感"]
        with TemporaryDirectory() as directory:
            outputs = [export_candidate_survey(goals, fmt, output_dir=directory, question_count=10, seed=9)
                       for fmt in ("wjx", "chaoxing")]
            manifests = [json.loads(Path(r["artifacts"][2]["path"]).read_text(encoding="utf-8")) for r in outputs]
            self.assertEqual(outputs[0]["selection"], outputs[1]["selection"])
            self.assertEqual(manifests[0]["mapping"], manifests[1]["mapping"])
            self.assertEqual(outputs[0]["selection"]["project_question_counts"],
                             {"patriotic-attitude": 4, "creativity": 3, "learning-self-efficacy": 3})
            self.assertEqual(outputs[0]["counts"]["candidate_count"], 10)
            self.assertEqual(outputs[0]["counts"]["backup_count"], 0)
            self.assertEqual(outputs[1]["counts"], outputs[0]["counts"])
            cells = read_xls(Path(outputs[1]["artifacts"][0]["path"]).read_bytes())["cells"]
            for n, candidate in enumerate(manifests[1]["candidates"], 1):
                self.assertEqual(cells[n, 3], candidate["item_text_zh"])
                self.assertNotIn((n, 6), cells)
                self.assertEqual([cells[n, col] for col in range(12, 17)], list(OPTIONS))
            self.assertEqual(max(n for n, col in cells), 10)
            self.assertTrue(all(c["bank"] == "核心候选题库" for c in manifests[1]["candidates"]))

    def test_invalid_question_count_fails_before_writing_and_error_is_json_safe(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "must-not-exist"
            for count in (0, -1, 13, True, 2.5, "5", float("nan"), float("inf")):
                with self.subTest(count_type=type(count).__name__):
                    envelope, code = run_request(["creativity"], output_dir=target, question_count=count)
                    self.assertEqual(code, 2)
                    self.assertEqual(envelope["error"]["code"], "INVALID_QUESTION_COUNT")
                    json.dumps(envelope, allow_nan=False)
                    self.assertFalse(target.exists())
            envelope, code = run_request(["patriotic-attitude", "creativity", "learning-self-efficacy"],
                                         output_dir=target, question_count=2)
            self.assertEqual(code, 2)
            self.assertEqual(envelope["error"]["details"][0]["minimum"], 3)
            self.assertFalse(target.exists())

    def test_explicit_subset_does_not_bypass_survey_release_gate(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "must-not-exist"
            envelope, code = run_request(["creativity"], output_dir=target, purpose="survey", question_count=3)
            self.assertEqual(code, 4)
            self.assertEqual(envelope["error"]["code"], "SURVEY_RELEASE_BLOCKED")
            self.assertEqual(len(envelope["error"]["details"][0]["blockers"]), 3)
            self.assertFalse(target.exists())

    def test_formal_survey_is_blocked_as_a_whole_before_any_write(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "must-not-exist"
            envelope, code = run_request(["research-integrity"], output_dir=target, purpose="survey")
            self.assertEqual(code, 4)
            self.assertEqual(envelope["error"]["code"], "SURVEY_RELEASE_BLOCKED")
            blockers = envelope["error"]["details"][0]["blockers"]
            self.assertEqual(len(blockers), 20)
            self.assertIn("activation_blocked", next(b for b in blockers if b["candidate_id"] == "RI-L001")["reasons"])
            self.assertEqual(envelope["artifacts"], [])
            self.assertFalse(target.exists())

    def test_invalid_requests_never_create_output(self):
        with TemporaryDirectory() as directory:
            for options in ({"output_format": "pdf"}, {"purpose": "unknown"},
                            {"output_format": []}, {"purpose": []}, {"dimensions_path": 42}):
                target = Path(directory) / "must-not-exist"
                envelope, code = run_request(["creativity"], output_dir=target, **options)
                self.assertEqual(code, 2)
                self.assertEqual(envelope["error"]["code"], "INVALID_REQUEST")
                self.assertFalse(target.exists())

    def test_wjx_rejects_multiline_or_import_syntax_without_changing_source(self):
        for text in ("题文\n2. 伪造题", "题文[多选题]", "题文\u2028下一行", "<script>题文</script>"):
            with self.subTest(text=text), self.assertRaises(DataError):
                render_wjx([{"item_text_zh": text, "options": list(OPTIONS)}], "问卷")
        payload = render_wjx([{"item_text_zh": "我不赞同这一观点。", "options": list(OPTIONS)}], "问卷")
        self.assertIn("我不赞同这一观点。".encode(), payload)
        self.assertNotIn(b"6-x", payload)

    def test_failed_file_write_removes_only_its_own_staging_bundle(self):
        with TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.txt"
            existing.write_text("preserve", encoding="utf-8")
            with patch("candidate_survey.Path.write_bytes", side_effect=OSError("write failed")):
                with self.assertRaises(DataError) as caught:
                    export_candidate_survey(["creativity"], output_dir=directory)
            self.assertEqual(caught.exception.code, "OUTPUT_WRITE_FAILED")
            self.assertEqual(list(Path(directory).iterdir()), [existing])
            self.assertEqual(existing.read_text(encoding="utf-8"), "preserve")

    def test_cli_from_another_cwd_reports_actual_files_and_no_model_calls(self):
        with TemporaryDirectory() as directory:
            completed = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "candidate_survey.py"),
                                        "--goal", "creativity", "--format", "wjx", "--request-id", "candidate-cli",
                                        "--output-dir", str(Path(directory) / "问卷")],
                                       cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            envelope = json.loads(completed.stdout)
            self.assertEqual(envelope["request_id"], "candidate-cli")
            self.assertEqual(envelope["model_trace"], [])
            self.assertEqual(envelope["summary"]["content"]["data"]["counts"]["candidate_count"], 12)
            self.assertTrue(all(Path(a["path"]).is_file() for a in envelope["artifacts"]))


if __name__ == "__main__":
    unittest.main()
