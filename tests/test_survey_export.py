"""Offline presentation and export boundaries; these are not WJX import tests."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCRIPT = SCRIPTS / "survey_export.py"
sys.path.insert(0, str(SCRIPTS))
from survey_data import DataError, SurveyStore  # noqa: E402
from survey_presentation import prepare_questionnaire  # noqa: E402
from survey_export import _format_limits, export_questionnaire, render_questionnaire  # noqa: E402


ENGINEERING_TEXT_INSTRUCTIONS = {
    "q003": "请只填写您认为属于工程伦理范畴的项目代码，按重要性从高到低排列，代码之间用中文逗号分隔。每个代码只出现一次，不并列；未选中的项目不要填写。若选择‘其他’，请将其代码列入排序，并在同一回答末尾补充其他内容的具体说明。如认为均不属于，请填写‘无’。",
    "q004": "请将以上五个项目的代码全部按重要性从高到低排列，代码之间用中文逗号分隔。每个代码恰好出现一次，不遗漏、不重复、不并列。",
}


class SurveyExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in (SKILL_ROOT / "data" / "questionnaires").glob("*.json")
        }

    def setUp(self):
        self.store = SurveyStore()

    def assert_data_error(self, expected, operation):
        with self.assertRaises(DataError) as caught:
            operation()
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    @staticmethod
    def records(document):
        return document["basic_information"] + document["items"]

    def run_cli(self, cwd, *arguments):
        environment = os.environ.copy()
        environment.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        process = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *arguments], cwd=cwd,
            env=environment, capture_output=True, text=True, encoding="utf-8",
            timeout=60, check=False,
        )
        return process, json.loads(process.stdout)

    def test_all_source_versions_are_preserved_by_presentation(self):
        self.assertEqual(len(self.documents), 16)
        for identity, original in self.documents.items():
            with self.subTest(version=identity):
                source = deepcopy(original)
                prepared = prepare_questionnaire(source)
                self.assertEqual(source, original)
                self.assertEqual(prepared["source_questionnaire"], original)
                self.assertEqual(prepared["groups"], original["groups"])
                mappings = prepared["source_mappings"]
                self.assertEqual(
                    {record["id"] for record in self.records(original)},
                    {entry["source_item_id"] for entry in mappings},
                )
                targets = [target for entry in mappings for target in entry["presentation_item_ids"]]
                self.assertEqual(len(targets), len(set(targets)))
                self.assertEqual(set(targets), {record["id"] for record in self.records(prepared)})
                if original["project_id"] != "engineering-ethics":
                    originals = {item["id"]: item for item in self.records(original)}
                    for item in self.records(prepared):
                        old = originals[item["source_item_id"]]
                        self.assertEqual(item["group_id"], old["group_id"])
                        self.assertEqual(item["raw_text"], old["raw_text"])
                        if original["project_id"] == "core-literacy":
                            self.assertEqual([option["value"] for option in item["response"]["options"]],
                                             [1, 2, 3, 4, 5])
                            self.assertEqual([option["label"] for option in item["response"]["options"]],
                                             [None] * 5)
                        else:
                            self.assertEqual(item["response"]["options"], old["response"]["options"])

    def test_reverse_words_and_order_remain_without_student_markers(self):
        checked = 0
        for original in self.documents.values():
            if original["source"]["volume"] != 1:
                continue
            prepared = prepare_questionnaire(original)
            for old, item in zip(original["items"], prepared["items"]):
                if old["reverse"]["marked"] is not True:
                    continue
                checked += 1
                self.assertEqual(item["student_text"], old["student_text"])
                self.assertNotIn("反向检测题", item["student_text"])
                self.assertEqual(item["response"]["options"], old["response"]["options"])
                self.assertEqual([option["value"] for option in item["response"]["options"]],
                                 [1, 2, 3, 4, 5])
                self.assertTrue(item["reverse"]["marked"])
            text = render_questionnaire(prepared)["text"]
            self.assertNotIn("反向检测题", text)
            self.assertNotIn("[反向", text)
            self.assertNotIn("[分值", text)
        self.assertEqual(checked, 51)

    def test_patriotism_keeps_all_groups_and_only_hides_concept_marks(self):
        original = self.documents["patriotism--original"]
        prepared = prepare_questionnaire(original)
        self.assertEqual(len(prepared["items"]), 15)
        self.assertEqual([item["group_id"] for item in prepared["items"]],
                         [item["group_id"] for item in original["items"]])
        for old, item in zip(original["items"], prepared["items"]):
            self.assertEqual(item["student_text"], old["student_text"])
            self.assertIsNone(item["reverse"]["marked"])
        rendered = render_questionnaire(prepared)
        self.assertNotIn("盲目爱国主义", rendered["text"])
        self.assertEqual(sum("盲目爱国主义" in item["raw_text"] for item in prepared["items"]), 4)

    def test_self_efficacy_open_slots_and_yes_no_are_not_demographics(self):
        for version in ("A", "B"):
            prepared = prepare_questionnaire(self.documents[f"learning-self-efficacy--{version}"])
            with self.subTest(version=version):
                self.assertEqual(prepared["basic_information"], [])
                opens = [item for item in prepared["items"] if item["kind"] == "open"]
                self.assertEqual(len(opens), 2)
                self.assertEqual([item["response"]["slots"] for item in opens], [3, 3])
                self.assertEqual(prepared["counts"]["independent_answer_items"], 27)
                choice = next(item for item in prepared["items"] if item["kind"] == "choice")
                self.assertEqual([option["label"] for option in choice["response"]["options"]], ["是", "否"])
                self.assertEqual(choice["role"], "measurement")

    def test_rating_instruction_does_not_cover_self_efficacy_open_and_yes_no_questions(self):
        for version in ("A", "B"):
            with self.subTest(version=version):
                prepared = prepare_questionnaire(self.documents[f"learning-self-efficacy--{version}"])
                rendered = render_questionnaire(prepared)
                instruction = next(note["student_text"] for note in prepared["instructions"]
                                   if note["role"] == "response")
                yes_no = next(item for item in prepared["items"] if item["kind"] == "choice")
                first_rating = next(item for item in prepared["items"] if item["kind"] == "rating")
                self.assertGreater(rendered["text"].index(instruction),
                                   rendered["text"].index(yes_no["student_text"]))
                self.assertLess(rendered["text"].index(instruction),
                                rendered["text"].index(first_rating["student_text"]))

    def test_second_volume_ten_levels_and_blank_basic_fields_are_not_invented(self):
        for original in self.documents.values():
            if original["source"]["volume"] != 2 or original["project_id"] == "engineering-ethics":
                continue
            with self.subTest(project=original["project_id"]):
                prepared = prepare_questionnaire(original)
                self.assertEqual(len(prepared["basic_information"]), 3)
                for item in prepared["basic_information"]:
                    self.assertEqual(item["kind"], "open")
                    self.assertEqual(item["response"]["options"], [])
                    self.assertIsNone(item["response"]["minimum"])
                    self.assertIsNone(item["response"]["maximum"])
                for item in prepared["items"]:
                    options = item["response"]["options"]
                    self.assertEqual([option["value"] for option in options], list(range(1, 11)))
                    self.assertEqual([option["label"] for option in options[1:9]], [None] * 8)

    def test_core_literacy_purpose_warning_is_teacher_only(self):
        original = self.documents["core-literacy--original"]
        prepared = prepare_questionnaire(original)
        response = next(note for note in original["instructions"] if note["role"] == "response")
        self.assertIn(response["student_text"], render_questionnaire(prepared)["text"])
        notes = "\n".join(note["text"] for note in prepared["teacher_notes"])
        self.assertIn("合理性", notes)
        self.assertIn("个人素养", notes)
        self.assertEqual([item["student_text"] for item in prepared["items"]],
                         [item["student_text"] for item in original["items"]])

    def test_engineering_rules_are_derived_not_a_new_source_version(self):
        original = self.documents["engineering-ethics--original"]
        prepared = prepare_questionnaire(original)
        self.assertEqual(prepared["source_questionnaire"], original)
        self.assertEqual((prepared["id"], prepared["version_id"]), (original["id"], "original"))
        self.assertIn("作答规则补全版", prepared["title"]["student_text"])
        self.assertEqual(prepared["counts"]["source_question_blocks"], 11)
        self.assertEqual(prepared["counts"]["source_item_records"], 13)
        self.assertEqual(prepared["counts"]["presentation_item_records"], 19)
        self.assertEqual(prepared["counts"]["presentation_measurement_records"], 17)
        self.assertEqual(prepared["counts"]["independent_answer_items"], 19)
        self.assertEqual(prepared["counts"]["conditional_auxiliary_fields"], 0)
        self.assertIsNone(prepared["counts"]["source_counts"]["measurement_items"])
        for item in prepared["items"][:2]:
            self.assertEqual(item["kind"], "choice")
            self.assertEqual(item["response"]["cardinality"], "single")
            self.assertEqual(len(item["response"]["options"]), 3)
        for suffix, expected_codes in (("q003", list("ABCDEFG")), ("q004", list("ABCDE"))):
            item = next(item for item in prepared["items"] if item["id"].endswith(suffix))
            old = next(item for item in original["items"] if item["id"].endswith(suffix))
            self.assertEqual(item["kind"], "open")
            self.assertEqual(item["response"]["slots"], 1)
            self.assertEqual(item["response"]["options"], [])
            self.assertIsNone(item["response"]["ranking"])
            self.assertNotIn("selection", item["response"])
            self.assertFalse(item["response"].get("auxiliary_fields"))
            self.assertEqual([{key: value for key, value in option.items() if key != "order"}
                              for option in item["reference_options"]], old["response"]["options"])
            self.assertEqual([option["order"] for option in item["reference_options"]],
                             list(range(1, len(expected_codes) + 1)))
            self.assertEqual([option["id"] for option in item["reference_options"]], expected_codes)
            self.assertEqual(item["student_text"], old["student_text"])
            self.assertEqual(item["student_response_instruction"], ENGINEERING_TEXT_INSTRUCTIONS[suffix])
            self.assertFalse(item["text_answer_adaptation"]["automatic_validation"])
            self.assertTrue(item["text_answer_adaptation"]["manual_review_required"])
            self.assertFalse(item["text_answer_adaptation"]["paid_feature_dependency"])
            self.assertFalse(item["text_answer_adaptation"]["score_responses"])
            self.assertFalse(item["text_answer_adaptation"]["analyze_responses"])
            self.assertEqual(item["text_answer_adaptation"]["answer_separator"], "，")
            self.assertEqual(item["text_answer_adaptation"]["reference_layout"], "paragraph_before_question")
            self.assertEqual(item["text_answer_adaptation"]["reference_code_style"], "bracketed")
            self.assertEqual(item["text_answer_adaptation"]["reference_code_template"], "【{code}】")
        adaptations = prepared["response_adaptations"]
        self.assertEqual({adaptation["source_item_id"] for adaptation in adaptations},
                         {f"engineering-ethics--original.{suffix}" for suffix in ENGINEERING_TEXT_INSTRUCTIONS})
        for adaptation in adaptations:
            self.assertEqual(adaptation["target_kind"], "open")
            self.assertEqual(adaptation["input_fields"], 1)
            self.assertFalse(adaptation["automatic_validation"])
            self.assertTrue(adaptation["manual_review_required"])
            self.assertEqual(adaptation["answer_separator"], "，")
            self.assertEqual(adaptation["reference_layout"], "paragraph_before_question")
            self.assertEqual(adaptation["reference_code_style"], "bracketed")
        old_rules = {"P2-E-2", "P2-E-3", "P2-E-4", "P2.1-E-2-3", "P2.1-E-4"}
        self.assertEqual({entry["rule_id"] for entry in prepared["rule_history"]}, old_rules)
        self.assertTrue(all(entry["status"] == "superseded" for entry in prepared["rule_history"]))
        self.assertFalse(old_rules.intersection(entry["rule_id"] for entry in prepared["rule_applications"]))
        self.assertTrue({"P2.1-R-E-2-3", "P2.1-R-E-4"}.issubset(
            entry["rule_id"] for entry in prepared["rule_applications"]
        ))
        for source_number, labels in (
            (9, ["完全不认可", "比较不认可", "中立", "比较认可", "完全认可"]),
            (10, ["完全不同意", "比较不同意", "中立", "比较同意", "完全同意"]),
            (12, ["完全不同意", "比较不同意", "中立", "比较同意", "完全同意"]),
        ):
            stem = f"engineering-ethics--original.q{source_number:03d}"
            items = [item for item in prepared["items"] if item["source_item_id"] == stem]
            self.assertEqual([item["source_option_id"] for item in items], ["A", "B", "C"])
            for item in items:
                self.assertEqual([option["label"] for option in item["response"]["options"]], labels)
                self.assertEqual([option["value"] for option in item["response"]["options"]], [None] * 5)
                self.assertFalse(item["response"]["assign_score_values"])
        final_open = next(item for item in prepared["items"] if item["source_item_id"].endswith("q013"))
        self.assertIn("三句话", final_open["student_text"])
        self.assertEqual(final_open["kind"], "open")
        self.assertIn("的的", next(item for item in prepared["items"] if item["id"].endswith("q006"))["student_text"])

    def test_every_unblocked_version_has_complete_mapping_and_honest_verification(self):
        checked = 0
        for original in self.documents.values():
            checked += 1
            with self.subTest(version=original["id"]):
                prepared = prepare_questionnaire(original)
                rendered = render_questionnaire(prepared, course="Python课程", scenario="前测")
                mapping = rendered["mapping"]
                expected = []
                for item in self.records(prepared):
                    expected.extend([item["source_item_id"]] * (item["response"]["slots"] or 1))
                self.assertEqual([entry["source_item_id"] for entry in mapping], expected)
                self.assertEqual(len(mapping), rendered["counts"]["source_mapping_count"])
                self.assertEqual(len(mapping), prepared["counts"]["independent_answer_items"])
                for item in self.records(prepared):
                    self.assertIn(item["student_text"], rendered["text"])
                self.assertIn("Python课程", rendered["title"])
                self.assertIn("前测", rendered["title"])
                self.assertNotIn("反向检测题", rendered["text"])
                self.assertNotIn("盲目爱国主义", rendered["text"])
                verification = rendered["verification"]
                self.assertEqual(verification["wjx_import"], "pending_user_validation")
                self.assertEqual(verification["workbuddy"], "not_verified")
                self.assertEqual(verification["teach_claw"], "not_verified")
                self.assertFalse(verification["reverse_scoring_applied"])
                self.assertEqual(verification["syntax_evidence"], "official_images_pending_review")
        self.assertEqual(checked, 16)

    def test_matrix_row_mapping_and_column_text_have_source_order(self):
        """Check our emitted lines and manifest, without claiming platform parsing."""
        for original in self.documents.values():
            with self.subTest(version=original["id"]):
                prepared = prepare_questionnaire(original)
                rendered = render_questionnaire(prepared)
                items = {item["id"]: item for item in self.records(prepared)}
                lines = rendered["text"].splitlines()
                matrices = {}
                for entry in rendered["mapping"]:
                    if entry["matrix_row_number"] is not None:
                        matrices.setdefault(entry["export_question_number"], []).append(entry)
                for question, rows in matrices.items():
                    start = next(index for index, line in enumerate(lines)
                                 if line.startswith(f"{question}. "))
                    self.assertIn("[矩阵题]", lines[start])
                    first = items[rows[0]["presentation_item_id"]]
                    columns = [option["label"] if option["value"] is None
                               else str(option["value"]) if option["label"] is None
                               else f"{option['value']}（{option['label']}）"
                               for option in first["response"]["options"]]
                    self.assertEqual(lines[start + 1], " ".join(columns))
                    self.assertEqual([entry["matrix_row_number"] for entry in rows],
                                     list(range(1, len(rows) + 1)))
                    for row in rows:
                        item = items[row["presentation_item_id"]]
                        self.assertEqual(lines[start + 1 + row["matrix_row_number"]], item["student_text"])
                for entry in rendered["mapping"]:
                    if entry["subquestion_number"] is not None:
                        item = items[entry["presentation_item_id"]]
                        emitted = next(line for line in lines
                                       if line.startswith(f"{entry['export_question_number']}. "))
                        self.assertIn(item["student_text"], emitted)
                        self.assertIn(f"（{entry['subquestion_number']}）", emitted)

    def test_prepared_rating_with_a_missing_endpoint_is_rejected(self):
        prepared = prepare_questionnaire(self.documents["creativity--original"])
        prepared["items"][0]["response"]["options"].pop()
        self.assert_data_error("INVALID_DATA", lambda: render_questionnaire(prepared))

    def test_export_unknown_missing_version_and_ambiguous_name_are_explicit(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "must-not-be-created"
            for code, project, version in (
                ("PROJECT_NOT_FOUND", "not-a-recorded-project", None),
                ("VERSION_REQUIRED", "critical-thinking", None),
                ("VERSION_NOT_FOUND", "critical-thinking", "missing"),
            ):
                with self.subTest(code=code):
                    self.assert_data_error(code, lambda p=project, v=version: export_questionnaire(
                        p, version=v, output_dir=output, store=self.store,
                    ))
                    self.assertFalse(output.exists())
            for project in self.store.catalog["projects"][:2]:
                project["aliases"].append("故意歧义别名")
            error = self.assert_data_error("AMBIGUOUS_PROJECT", lambda: export_questionnaire(
                "故意歧义别名", output_dir=output, store=self.store,
            ))
            self.assertEqual(len(error.candidates), 2)
            self.assertFalse(output.exists())

    def test_engineering_text_adaptation_preserves_reference_text_and_generates_whole_candidate(self):
        original = self.documents["engineering-ethics--original"]
        prepared = prepare_questionnaire(original)
        rendered = render_questionnaire(prepared)
        self.assertEqual(rendered["counts"]["export_question_count"], 11)
        self.assertEqual(rendered["counts"]["source_mapping_count"], 19)
        self.assertEqual(rendered["counts"]["export_paragraph_count"], 4)
        self.assertTrue(rendered["selection"]["full_questionnaire"])
        self.assertEqual(rendered["text"].count("[单选题]"), 2)
        self.assertEqual(rendered["text"].count("[矩阵题]"), 6)
        self.assertEqual(rendered["text"].count("[填空题]"), 3)
        for group in original["groups"]:
            self.assertIn(group["raw_name"], rendered["text"])
        for forbidden in ("[排序题]", "[多选题]", "选项引用", "条件必填"):
            self.assertNotIn(forbidden, rendered["text"])
        for forbidden in (">", "&gt;", "&g", "G："):
            self.assertNotIn(forbidden, rendered["text"])
        lines = rendered["text"].splitlines()
        for question_number, suffix in ((3, "q003"), (4, "q004")):
            item = next(item for item in prepared["items"] if item["id"].endswith(suffix))
            line = f"{question_number}. {item['student_text']}[填空题]"
            self.assertIn(line, lines)
            header_index = lines.index(line)
            paragraph = lines[header_index - 2]
            self.assertEqual(lines[header_index - 1], "")
            self.assertEqual(lines[header_index + 1], "")
            self.assertEqual(paragraph.count("[段落说明]"), 1)
            self.assertTrue(paragraph.endswith("[段落说明]"))
            self.assertNotIn("[填空题]", paragraph)
            self.assertIn("参考项目：", paragraph)
            self.assertIn(ENGINEERING_TEXT_INSTRUCTIONS[suffix], paragraph)
            self.assertNotIn("参考项目", line)
            self.assertNotIn("作答说明", line)
            positions = []
            for option in item["reference_options"]:
                fragment = f"【{option['id']}】{option['label']}"
                self.assertIn(fragment, paragraph)
                self.assertNotIn(f"{option['id']}：", paragraph)
                positions.append(paragraph.index(fragment))
            self.assertEqual(positions, sorted(positions))
            mapping = [entry for entry in rendered["mapping"] if entry["source_item_id"] == item["source_item_id"]]
            self.assertEqual(len(mapping), 1)
            self.assertEqual(mapping[0]["kind"], "open")
            self.assertIsNone(mapping[0]["matrix_row_number"])
            self.assertIsNone(mapping[0]["subquestion_number"])
            self.assertEqual(mapping[0]["text_answer_adaptation"], item["text_answer_adaptation"])
            self.assertTrue(mapping[0]["combined_into_single_text_answer"])
            self.assertEqual(mapping[0]["information_components"],
                             item["text_answer_adaptation"]["information_components"])
            self.assertEqual(mapping[0]["reference_paragraph_number"], question_number - 1)
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "工程伦理候选文件"
            process, envelope = self.run_cli(
                temporary, "--project", "engineering-ethics", "--output-dir", str(output),
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIsNone(envelope["error"])
            self.assertEqual(envelope["model_trace"], [])
            data = envelope["summary"]["content"]["data"]
            self.assertEqual(data["counts"]["export_question_count"], 11)
            self.assertEqual(data["counts"]["independent_answer_items"], 19)
            self.assertEqual(data["verification"]["wjx_import"], "pending_user_validation")
            self.assertTrue(data["verification"]["manual_review_required"])
            self.assertFalse(data["verification"]["automatic_text_answer_validation"])
            self.assertEqual(data["verification"]["free_account_import"], "not_verified")
            self.assertEqual(len(data["artifacts"]), 3)
            primary = next(artifact for artifact in data["artifacts"] if artifact["role"] == "primary")
            self.assertIn("pending-import", primary["name"])
            self.assertEqual(Path(primary["path"]).read_text(encoding="utf-8"), rendered["text"])
            manifest_file = next(artifact for artifact in data["artifacts"] if artifact["role"] == "mapping")
            manifest = json.loads(Path(manifest_file["path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["response_adaptations"], prepared["response_adaptations"])
            self.assertEqual(manifest["rule_history"], prepared["rule_history"])
            self.assertEqual(manifest["mapping"], rendered["mapping"])
            self.assertEqual(manifest["selection"], rendered["selection"])
            teacher_file = next(artifact for artifact in data["artifacts"] if artifact["role"] == "teacher")
            teacher_text = Path(teacher_file["path"]).read_text(encoding="utf-8")
            for required_text in ("人工", "重复", "漏项", "未知代码", "G"):
                self.assertIn(required_text, teacher_text)
            self.assertIn("中文逗号", teacher_text)
            self.assertIn("参考项目代码展示为【A】", teacher_text)

    def test_engineering_import_subset_uses_same_reference_paragraphs_and_short_fill_headers(self):
        original = self.documents["engineering-ethics--original"]
        prepared = prepare_questionnaire(original)
        prepared_before = deepcopy(prepared)
        ids = [f"engineering-ethics--original.{suffix}" for suffix in ("q003", "q004")]
        whole = render_questionnaire(prepared)
        sample = render_questionnaire(prepared, source_item_ids=list(reversed(ids)))
        self.assertEqual(prepared, prepared_before)
        self.assertEqual(prepared["source_questionnaire"], original)
        self.assertFalse(sample["selection"]["full_questionnaire"])
        self.assertEqual(sample["selection"]["source_item_ids"], list(reversed(ids)))
        self.assertEqual(sample["selection"]["order"], "source_order")
        self.assertIn("题目导入测试", sample["title"])
        self.assertEqual(sample["counts"]["export_question_count"], 2)
        self.assertEqual(sample["counts"]["export_paragraph_count"], 2)
        self.assertEqual(sample["counts"]["independent_answer_items"], 2)
        self.assertEqual(sample["counts"]["source_mapping_count"], 2)
        self.assertEqual(sample["counts"]["conditional_auxiliary_fields"], 0)
        self.assertEqual(sample["text"].count("[填空题]"), 2)
        self.assertEqual(sample["text"].count("[段落说明]"), 2)
        for forbidden in ("[单选题]", "[矩阵题]", "[排序题]", "[多选题]", ">", "&gt;", "G："):
            self.assertNotIn(forbidden, sample["text"])
        sample_blocks = sample["text"].rstrip("\n").split("\n\n")[1:]
        whole_blocks = whole["text"].rstrip("\n").split("\n\n")[1:]
        self.assertEqual(len(sample_blocks), 4)
        self.assertEqual([entry["source_item_id"] for entry in sample["mapping"]], ids)
        for number, item_id in enumerate(ids, 1):
            old = next(item for item in original["items"] if item["id"] == item_id)
            sample_paragraph, sample_question = sample_blocks[(number - 1) * 2:number * 2]
            self.assertIn(sample_paragraph, whole_blocks)
            self.assertEqual(sample_question, f"{number}. {old['student_text']}[填空题]")
            whole_question = f"{number + 2}. {old['student_text']}[填空题]"
            whole_question_index = whole_blocks.index(whole_question)
            self.assertEqual(whole_blocks[whole_question_index - 1], sample_paragraph)
            mapping = sample["mapping"][number - 1]
            self.assertEqual(mapping["export_question_number"], number)
            self.assertEqual(mapping["reference_paragraph_number"], number)
            self.assertEqual(mapping["kind"], "open")
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "两题导入测试"
            process, envelope = self.run_cli(
                temporary, "--project", "engineering-ethics", "--output-dir", str(output),
                "--source-item-id", ids[0], "--source-item-id", ids[1],
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            data = envelope["summary"]["content"]["data"]
            self.assertFalse(data["selection"]["full_questionnaire"])
            self.assertEqual(data["counts"]["independent_answer_items"], 2)
            self.assertEqual(data["verification"]["wjx_import"], "pending_user_validation")
            primary = next(entry for entry in data["artifacts"] if entry["role"] == "primary")
            self.assertEqual(Path(primary["path"]).read_text(encoding="utf-8"),
                             render_questionnaire(prepared, source_item_ids=ids)["text"])
            mapping_file = next(entry for entry in data["artifacts"] if entry["role"] == "mapping")
            manifest = json.loads(Path(mapping_file["path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["selection"]["source_item_ids"], ids)
            self.assertEqual(manifest["counts"]["export_question_count"], 2)
            self.assertEqual(len(manifest["mapping"]), 2)

    def test_import_subset_invalid_ids_fail_before_creating_files(self):
        prepared = prepare_questionnaire(self.documents["engineering-ethics--original"])
        q003 = "engineering-ethics--original.q003"
        for ids in ([], "q003", [""], [q003, q003], ["engineering-ethics--original.unknown"]):
            with self.subTest(ids=ids):
                self.assert_data_error("INVALID_REQUEST", lambda selected=ids: render_questionnaire(
                    prepared, source_item_ids=selected,
                ))
                with TemporaryDirectory() as temporary:
                    output = Path(temporary) / "must-not-be-created"
                    self.assert_data_error("INVALID_REQUEST", lambda selected=ids: export_questionnaire(
                        "engineering-ethics", output_dir=output, source_item_ids=selected,
                    ))
                    self.assertFalse(output.exists())
        mutated = deepcopy(prepared)
        first_rating = next(item for item in mutated["items"] if item["kind"] == "rating")
        first_rating["response"]["options"].pop()
        self.assert_data_error("INVALID_DATA", lambda: render_questionnaire(mutated, source_item_ids=[q003]))

    def test_unadapted_ranking_and_unknown_types_keep_format_limits(self):
        prepared = prepare_questionnaire(self.documents["engineering-ethics--original"])
        mutated = deepcopy(prepared)
        first = mutated["items"][0]
        first["kind"] = "ranking"
        first["response"]["ranking"] = {"complete": True, "ties_allowed": False}
        self.assertIn("FULL_RANKING_SETTINGS_NOT_CONFIRMED", {issue["code"] for issue in _format_limits(mutated)})
        self.assert_data_error("INVALID_DATA", lambda: render_questionnaire(mutated))
        first["kind"] = "unrecognized-response"
        self.assertIn("UNSUPPORTED_RESPONSE_KIND", {issue["code"] for issue in _format_limits(mutated)})

    def test_chinese_output_unrelated_cwd_and_repeat_exports_do_not_overwrite(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "中文输出目录"
            cwd = root / "不相关工作目录"
            cwd.mkdir()
            arguments = ["--project", "大学生创造力问卷", "--course", "Python / .. : * ? 基础",
                         "--scenario", "后测", "--output-dir", str(output),
                         "--request-id", "离线验证请求"]
            first_process, first_envelope = self.run_cli(cwd, *arguments)
            self.assertEqual(first_process.returncode, 0, first_process.stderr)
            self.assertEqual(first_envelope["request_id"], "离线验证请求")
            self.assertEqual(first_envelope["model_trace"], [])
            first = first_envelope["summary"]["content"]["data"]
            artifacts = first["artifacts"]
            self.assertEqual(len(artifacts), 3)
            first_contents = {entry["path"]: Path(entry["path"]).read_bytes() for entry in artifacts}
            for filename in first_contents:
                path = Path(filename)
                self.assertTrue(path.is_relative_to(output.resolve()))
                path.read_text(encoding="utf-8")
                self.assertNotIn("..", path.name)
            primary = next(entry for entry in artifacts if entry["role"] == "primary")
            self.assertEqual(Path(primary["path"]).suffix, ".txt")
            self.assertIn("pending-import", primary["name"])
            text = Path(primary["path"]).read_text(encoding="utf-8")
            self.assertNotIn("反向检测题", text)
            self.assertNotIn("疑点", text)
            second_process, second_envelope = self.run_cli(cwd, *arguments)
            self.assertEqual(second_process.returncode, 0, second_process.stderr)
            second = second_envelope["summary"]["content"]["data"]
            self.assertNotEqual(first["output_directory"], second["output_directory"])
            for filename, content in first_contents.items():
                self.assertEqual(Path(filename).read_bytes(), content)
            self.assertEqual(list(cwd.iterdir()), [])

    def test_omitted_output_directory_uses_skill_root_and_empty_is_invalid(self):
        with TemporaryDirectory() as temporary:
            relocated_root = Path(temporary) / "中文技能目录"
            with patch("survey_export.SKILL_ROOT", relocated_root):
                result = export_questionnaire("creativity", request_id="default-directory", store=self.store)
                self.assertEqual(result["version_id"], "original")
                self.assertTrue(Path(result["output_directory"]).is_relative_to(relocated_root / "output"))
                self.assertNotIn(" — ", result["title"])
                for artifact in result["artifacts"]:
                    self.assertTrue(Path(artifact["path"]).is_file())
                manifest = json.loads(next(Path(a["path"]) for a in result["artifacts"]
                                           if a["role"] == "mapping").read_text(encoding="utf-8"))
                self.assertEqual(manifest["verification"]["wjx_import"], "pending_user_validation")
                existing = {p: p.read_bytes() for p in (relocated_root / "output").rglob("*") if p.is_file()}
                self.assert_data_error("INVALID_REQUEST", lambda: export_questionnaire(
                    "creativity", output_dir="", store=self.store,
                ))
                self.assertEqual(existing, {p: p.read_bytes() for p in (relocated_root / "output").rglob("*") if p.is_file()})

    def test_title_and_request_id_injection_are_rejected_before_files(self):
        bad_values = ["课程\n\n1.额外题目[填空题]", "课程\r额外题目", "课程\t额外题目", "[多选题]"]
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "no-output"
            for field in ("course", "scenario", "request_id"):
                for value in bad_values:
                    with self.subTest(field=field, value=repr(value)):
                        self.assert_data_error("INVALID_REQUEST", lambda key=field, text=value: export_questionnaire(
                            "creativity", output_dir=output, **{key: text},
                        ))
                        self.assertFalse(output.exists())

    def test_invalid_data_and_cli_parameters_fail_without_files(self):
        self.store.catalog["projects"][0]["versions"][0]["file"] = "questionnaires/missing.json"
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "no-output"
            self.assert_data_error("INVALID_DATA", lambda: export_questionnaire(
                "creativity", output_dir=output, store=self.store,
            ))
            self.assertFalse(output.exists())
            process, envelope = self.run_cli(
                temporary, "--project", "creativity", "--output-dir", str(output),
                "--unsupported-argument",
            )
            self.assertEqual(process.returncode, 2)
            self.assertEqual(envelope["error"]["code"], "INVALID_REQUEST")
            self.assertEqual(envelope["artifacts"], [])
            self.assertFalse(output.exists())

    def test_failed_bundle_write_rolls_back_and_never_modifies_sources(self):
        originals = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (SKILL_ROOT / "data").rglob("*.json")}
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            calls = []
            actual_write = Path.write_text

            def failed_second_write(path, *args, **kwargs):
                calls.append(path)
                if len(calls) == 2:
                    raise OSError("offline simulated write failure")
                return actual_write(path, *args, **kwargs)

            with patch.object(Path, "write_text", failed_second_write):
                with self.assertRaises(DataError):
                    export_questionnaire("creativity", output_dir=output)
            self.assertGreaterEqual(len(calls), 2)
            if output.exists():
                self.assertEqual(list(output.iterdir()), [])
        self.assertEqual(originals, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in originals})
        result = self.store.validate_all()
        self.assertTrue(result["structure_valid"])
        self.assertEqual((result["projects"], result["versions"]), (12, 16))

    def test_staging_collision_preserves_preexisting_files(self):
        token = uuid.UUID("a" * 32)
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            staging = output / (".partial-" + token.hex)
            staging.mkdir()
            originals = {staging / name: f"previous user content: {name}".encode("utf-8")
                         for name in ("survey.pending-import.txt", "teacher-notes.md", "manifest.json")}
            for path, content in originals.items():
                path.write_bytes(content)
            with patch("survey_export.uuid.uuid4", return_value=token):
                self.assert_data_error("OUTPUT_WRITE_FAILED", lambda: export_questionnaire(
                    "creativity", output_dir=output, request_id="collision-check",
                ))
            self.assertTrue(staging.is_dir())
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)


if __name__ == "__main__":
    unittest.main()
