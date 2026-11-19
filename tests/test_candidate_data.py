"""Offline checks for lossless handoff import and goal-selection boundaries."""
from __future__ import annotations

from collections import Counter
import io
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import zipfile


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
from candidate_data import BACKUP_BANK, CORE_BANK, CandidateStore, DATA_ROOT  # noqa: E402
from import_candidate_handoff import RETAINED_FILES, import_handoff, read_verified_archive, sha256  # noqa: E402
from survey_data import DataError  # noqa: E402


def test_dimensions(projects):
    """An explicitly artificial fixture, never a production classification."""
    return {"schema_version": 1, "status": "confirmed", "evidence": "test fixture only",
            "dimensions": [{"id": f"fixture-{index + 1}", "name": f"测试维度{index + 1}",
                            "project_ids": [project["id"] for project in projects[index * 6:(index + 1) * 6]]}
                           for index in range(3)]}


class CandidateDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = CandidateStore()

    def assert_code(self, code, function, *args):
        with self.assertRaises(DataError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)

    def fixture_store(self, folder, config=None):
        config_path = Path(folder) / "fixture-dimensions.json"
        config_path.write_text(json.dumps(config or test_dimensions(self.store.list_projects()), ensure_ascii=False), encoding="utf-8")
        return CandidateStore(dimensions_path=config_path)

    def test_verified_counts_provenance_and_five_approvals_are_preserved(self):
        summary = self.store.validate()
        self.assertTrue(summary["valid"])
        expected = {"projects": 18, "raw_source_rows": 505, "unified_candidates": 482,
                    "core_candidates": 188, "backup_candidates": 294, "merged_candidates": 23,
                    "teacher_events": 22, "priority_exceptions": 235, "qa_checks_passed": 5840}
        for key, value in expected.items():
            self.assertEqual(summary["counts"][key], value)
        self.assertEqual(len({row["candidate_id"] for row in self.store.candidates}), 482)
        self.assertEqual(Counter(int(row["source_count"]) for row in self.store.candidates), {1: 459, 2: 23})
        for candidate in self.store.candidates:
            self.assertTrue(all(candidate[field] for field in ("text_approval", "bank_approval", "merge_approval", "scoring_approval", "scale_approval")))
            sources = self.store.source_records_for(candidate["candidate_id"])
            self.assertEqual([source["source_record_id"] for source in sources], candidate["source_record_ids"].split("|"))
            self.assertTrue(all(source["mapped_candidate_id"] == candidate["candidate_id"] for source in sources))
            self.assertEqual(len([key for key in sources[0] if key.startswith("raw_")]), 30)
            self.assertEqual([event["decision_event_id"] for event in self.store.decision_records_for(candidate["candidate_id"])],
                             list(filter(None, candidate["teacher_decision_ids"].split("|"))))

    def test_each_single_goal_uses_all_core_and_backup_without_filtering(self):
        for project in self.store.list_projects():
            with self.subTest(project=project["id"]):
                result = self.store.select_projects([project["id"]])
                self.assertEqual(result["selection"]["mode"], "single_all")
                self.assertEqual(result["selection"]["sampling_method"], "all")
                self.assertIsNone(result["selection"]["question_count_requested"])
                self.assertIsNone(result["selection"]["sampling_seed"])
                self.assertEqual(result["selection"]["available_candidate_count"], project["candidate_count"])
                self.assertEqual(result["selection"]["project_question_counts"], {project["id"]: project["candidate_count"]})
                self.assertEqual(len(result["candidates"]), project["candidate_count"])
                self.assertEqual(sum(row["bank"] == CORE_BANK for row in result["candidates"]), project["core_count"])
                self.assertEqual(sum(row["bank"] == BACKUP_BANK for row in result["candidates"]), project["backup_count"])
                self.assertTrue(all(row["release_eligible"] == "否" for row in result["candidates"]))
        # The 16 known dual-scale conflicts remain in the review selection.
        integrity = self.store.select_projects(["科研诚信意识"])
        self.assertEqual(integrity["review"]["risk_counts"]["P0"], 16)
        self.assertEqual(len(integrity["candidates"]), 20)

    def test_single_count_samples_one_uniform_pool_without_bank_priority(self):
        pool = self.store.select_projects(["创造力"])["candidates"]
        original_ids = [candidate["candidate_id"] for candidate in pool]
        reference_ids = {candidate["candidate_id"] for candidate in random.Random(17).sample(pool, 7)}
        result = self.store.select_projects(["创造力"], question_count=7, seed=17)
        actual = result["candidates"]
        self.assertEqual([row["candidate_id"] for row in actual],
                         [identity for identity in original_ids if identity in reference_ids])
        self.assertNotEqual(result["selection"]["candidate_ids"], original_ids[:7])
        self.assertEqual({row["bank"] for row in actual}, {CORE_BANK, BACKUP_BANK})
        self.assertEqual(result["selection"]["mode"], "single_sample")
        self.assertEqual(result["selection"]["sampling_method"], "uniform_without_bank_priority")
        self.assertEqual(result["selection"]["question_count_requested"], 7)
        self.assertEqual(result["selection"]["sampling_seed"], 17)
        self.assertEqual(result["selection"]["available_candidate_count"], 12)
        self.assertEqual(result["selection"]["project_question_counts"], {"creativity": 7})
        self.assertTrue(all(row["release_eligible"] == "否" for row in actual))

    def test_multiple_count_is_total_balanced_across_three_goals_and_only_core(self):
        goals = ["爱国主义态度", "创造力", "学习自我效能感"]
        result = self.store.select_projects(goals, question_count=10, seed=23)
        self.assertEqual(len(result["candidates"]), 10)
        self.assertEqual(result["selection"]["candidate_count"], 10)
        self.assertEqual(result["selection"]["available_candidate_count"], 22)
        self.assertEqual(result["selection"]["mode"], "multiple_core_sample")
        self.assertEqual(result["selection"]["sampling_method"], "balanced_projects_uniform_within_project")
        self.assertEqual(result["selection"]["project_question_counts"],
                         {"patriotic-attitude": 4, "creativity": 3, "learning-self-efficacy": 3})
        self.assertEqual(Counter(row["project_slug"] for row in result["candidates"]),
                         result["selection"]["project_question_counts"])
        self.assertTrue(all(row["bank"] == CORE_BANK for row in result["candidates"]))
        minimal = self.store.select_projects(goals, question_count=3)
        self.assertEqual(set(minimal["selection"]["project_question_counts"].values()), {1})

    def test_full_project_capacity_is_redistributed_and_requested_order_is_kept(self):
        result = self.store.select_projects(["爱国主义态度", "创造力", "学习自我效能感"],
                                            question_count=20, seed=3)
        self.assertEqual(result["selection"]["project_question_counts"],
                         {"patriotic-attitude": 4, "creativity": 6, "learning-self-efficacy": 10})
        self.assertEqual(len(result["candidates"]), 20)
        self.assertEqual(len(set(result["selection"]["candidate_ids"])), 20)
        for project_id in result["selection"]["project_ids"]:
            original_ids = [row["candidate_id"] for row in self.store.candidates if row["project_slug"] == project_id]
            chosen_ids = [row["candidate_id"] for row in result["candidates"] if row["project_slug"] == project_id]
            self.assertEqual(chosen_ids, [identity for identity in original_ids if identity in chosen_ids])
        reverse = self.store.select_projects(["学习自我效能感", "创造力", "爱国主义态度"], question_count=10)
        self.assertEqual(reverse["selection"]["project_ids"],
                         ["learning-self-efficacy", "creativity", "patriotic-attitude"])
        self.assertEqual(reverse["selection"]["project_question_counts"],
                         {"learning-self-efficacy": 4, "creativity": 3, "patriotic-attitude": 3})

    def test_sampling_seed_is_reproducible_and_never_changes_global_random_state(self):
        state = random.getstate()
        first = self.store.select_projects(["科学精神"], question_count=15, seed=9)
        second = self.store.select_projects(["科学精神"], question_count=15, seed=9)
        different = self.store.select_projects(["科学精神"], question_count=15, seed=10)
        self.assertEqual(first, second)
        self.assertNotEqual(first["selection"]["candidate_ids"], different["selection"]["candidate_ids"])
        self.assertEqual(random.getstate(), state)

    def test_explicit_full_count_returns_entire_eligible_pool_in_original_order(self):
        for goals in (["创造力"], ["爱国主义态度", "创造力", "学习自我效能感"]):
            with self.subTest(goals=goals):
                full = self.store.select_projects(goals)
                explicit = self.store.select_projects(goals, len(full["candidates"]), seed=99)
                self.assertEqual(explicit["candidates"], full["candidates"])
                self.assertEqual(explicit["selection"]["mode"], full["selection"]["mode"])
                self.assertEqual(explicit["selection"]["sampling_method"], "all")
                self.assertIsNone(explicit["selection"]["sampling_seed"])

    def test_question_count_and_seed_reject_invalid_values_without_silent_clamping(self):
        for count in (0, -1, 13, True, False, 1.0, float("nan"), float("inf"), "6", [], {}):
            with self.subTest(count_type=type(count).__name__):
                self.assert_code("INVALID_QUESTION_COUNT", self.store.select_projects, ["创造力"], count)
        goals = ["爱国主义态度", "创造力", "学习自我效能感"]
        for count in (1, 2, 23):
            self.assert_code("INVALID_QUESTION_COUNT", self.store.select_projects, goals, count)
        for seed in (True, False, 1.0, "0", None, [], {}):
            with self.subTest(seed_type=type(seed).__name__):
                self.assert_code("INVALID_SAMPLING_SEED", self.store.select_projects, ["创造力"], 5, seed)
        self.assert_code("INVALID_SAMPLING_SEED", self.store.select_projects, ["创造力"], None, 1)

    def test_select_cli_requires_count_even_for_explicit_zero_seed(self):
        with TemporaryDirectory() as folder:
            completed = subprocess.run([sys.executable, "-B", str(SKILL_ROOT / "scripts" / "candidate_data.py"),
                                        "select", "--project", "creativity", "--seed", "0"],
                                       cwd=folder, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["error"]["code"], "INVALID_REQUEST")

    def test_explicit_count_keeps_project_limits_and_review_flags(self):
        self.assert_code("TOO_MANY_PROJECTS_IN_DIMENSION", self.store.select_projects,
                         ["批判性思维", "学生核心素养", "科学精神", "创造力"], 4)
        seven = ["爱国主义态度", "中华文化传播意愿", "对华友好态度", "创造力", "批判性思维", "学习自我效能感", "专业认同感"]
        self.assert_code("TOO_MANY_PROJECTS", self.store.select_projects, seven, 7)
        sampled = self.store.select_projects(["科研诚信意识"], 16)
        self.assertEqual(len(sampled["candidates"]), 16)
        self.assertFalse(sampled["review"]["release_eligible"])
        self.assertEqual(len(sampled["review"]["blocked_candidate_ids"]), 16)
        self.assertTrue(all(row["release_eligible"] == "否" for row in sampled["candidates"]))
        for row in sampled["candidates"]:
            self.assertEqual(len(self.store.source_records_for(row["candidate_id"])), int(row["source_count"]))

    def test_pending_dimension_map_blocks_multiple_but_not_single_goals(self):
        pending = {"schema_version": 1, "status": "pending_user_confirmation", "dimensions": []}
        with TemporaryDirectory() as folder:
            store = self.fixture_store(folder, pending)
            self.assertEqual(store.validate()["dimension_mapping"], "pending_user_confirmation")
            self.assert_code("DIMENSION_MAPPING_REQUIRED", store.select_projects, ["创造力", "科学精神"])
            self.assertEqual(store.select_projects(["创造力"])["selection"]["candidate_count"], 12)

    def test_confirmed_primary_dimensions_match_user_source_and_original_numbers(self):
        self.assertEqual(self.store.validate()["dimension_mapping"], "confirmed")
        projects = self.store.list_projects()
        self.assertEqual([project["number"] for project in projects], list(range(1, 19)))
        expected = {"家国认同": [4, 14, 16], "文化涵养": [1, 5, 6, 7, 10, 11, 13, 15, 17],
                    "职业素养": [2, 3, 8, 9, 12, 18]}
        actual = {name: [project["number"] for project in projects if project["dimension_name"] == name]
                  for name in expected}
        self.assertEqual(actual, expected)
        self.assertEqual(Counter(project["dimension_name"] for project in projects),
                         {"家国认同": 3, "文化涵养": 9, "职业素养": 6})
        by_number = {project["number"]: project for project in projects}
        self.assertEqual(by_number[3]["related_dimensions"], [])
        self.assertEqual(by_number[5]["primary_dimension"], {"id": "cultural-cultivation", "name": "文化涵养"})
        self.assertEqual(by_number[5]["related_dimensions"], [{"id": "professional-literacy", "name": "职业素养"}])
        expected_related = {1: "职业素养", 2: None, 3: None, 4: None, 5: "职业素养", 6: "职业素养",
                            7: "职业素养", 8: None, 9: "文化涵养", 10: "职业素养", 11: "家国认同",
                            12: "文化涵养", 13: "职业素养", 14: "文化涵养", 15: "家国认同",
                            16: "文化涵养", 17: "职业素养", 18: "文化涵养"}
        for number, name in expected_related.items():
            self.assertEqual([dimension["name"] for dimension in by_number[number]["related_dimensions"]],
                             [name] if name else [])
        source = self.store.dimension_config["mapping_source"]
        self.assertEqual(source["sha256"], sha256((DATA_ROOT / source["file"]).read_bytes()))

    def test_real_two_three_one_selection_counts_only_primary_dimensions(self):
        goals = ["爱国主义", "中华文化传播意愿", "批判性思维", "学生核心素养", "科学精神", "专业认同感"]
        result = self.store.select_projects(goals)
        self.assertEqual(result["selection"]["dimension_counts"],
                         {"national-identity": 2, "cultural-cultivation": 3, "professional-literacy": 1})
        self.assertEqual(result["selection"]["dimension_counting"], "primary_dimension_only")
        self.assertEqual(result["selection"]["project_count"], 6)
        self.assertTrue(all(candidate["bank"] == CORE_BANK for candidate in result["candidates"]))
        self.assertEqual(len(result["candidates"]), sum(project["core_count"] for project in result["projects"]))
        # All four have a related occupational dimension, but all count toward
        # their cultural primary dimension and cannot be redistributed.
        self.assert_code("TOO_MANY_PROJECTS_IN_DIMENSION", self.store.select_projects,
                         ["批判性思维", "学生核心素养", "科学精神", "创造力"])

    def test_related_dimensions_are_validated_and_never_change_primary_counting(self):
        config = json.loads(json.dumps(self.store.dimension_config))
        # Custom fixture has its own evidence context; preserve the mappings but
        # avoid making a temporary path depend on a separately located source.
        config.pop("mapping_source")
        for values in (["cultural-cultivation"], ["unknown"], ["professional-literacy", "professional-literacy"]):
            invalid = json.loads(json.dumps(config))
            invalid["project_related_dimensions"]["critical-thinking"] = values
            with TemporaryDirectory() as folder:
                self.assert_code("INVALID_DATA", self.fixture_store, folder, invalid)

    def test_six_goals_three_per_dimension_use_only_core(self):
        with TemporaryDirectory() as folder:
            store = self.fixture_store(folder)
            projects = store.list_projects()
            queries = [project["id"] for project in projects[:3] + projects[6:9]]
            result = store.select_projects(queries)
            self.assertEqual(result["selection"]["mode"], "multiple_core")
            self.assertEqual(result["selection"]["dimension_counts"], {"fixture-1": 3, "fixture-2": 3})
            self.assertTrue(all(row["bank"] == CORE_BANK for row in result["candidates"]))
            self.assertEqual(len(result["candidates"]), sum(project["core_count"] for project in result["projects"]))
            self.assertEqual(result["selection"]["project_ids"], queries)
            self.assert_code("TOO_MANY_PROJECTS_IN_DIMENSION", store.select_projects, [project["id"] for project in projects[:4]])
            self.assert_code("TOO_MANY_PROJECTS", store.select_projects, [project["id"] for project in projects[:7]])

    def test_duplicate_alias_unknown_and_empty_requests_fail(self):
        for queries in ([], None, "创造力", [""], [None], ["创造力\n"]):
            self.assert_code("INVALID_REQUEST", self.store.select_projects, queries)
        for queries in (["爱国主义", "patriotism"], ["1", "批判性思维"], ["creativity", "CREATIVITY"]):
            self.assert_code("DUPLICATE_PROJECT", self.store.select_projects, queries)
        self.assert_code("PROJECT_NOT_FOUND", self.store.select_projects, ["未知目标"])
        self.assertEqual(self.store.select_projects([" 爱国主义 "])["projects"][0]["id"], "patriotic-attitude")

    def test_review_selection_is_not_formal_release_or_scoring_authorization(self):
        result = self.store.select_projects(["科研诚信意识"])
        self.assertFalse(result["review"]["release_eligible"])
        self.assertEqual(len(result["review"]["blocked_candidate_ids"]), 20)
        self.assert_code("SURVEY_RELEASE_BLOCKED", self.store.assert_survey_eligible, result["candidates"])

    def test_returned_records_are_independent_copies(self):
        candidate = self.store.candidates[0]
        identity = candidate["candidate_id"]
        original = candidate["item_text_zh"]
        candidate["item_text_zh"] = "changed"
        sources = self.store.source_records_for(identity)
        sources[0]["mapped_candidate_id"] = "changed"
        selected = self.store.select_projects([candidate["project_slug"]])
        self.assertEqual(next(row for row in selected["candidates"] if row["candidate_id"] == identity)["item_text_zh"], original)
        self.assertEqual(self.store.source_records_for(identity)[0]["mapped_candidate_id"], identity)

    def test_dimension_config_requires_three_complete_disjoint_groups(self):
        valid = test_dimensions(self.store.list_projects())
        invalids = []
        two = json.loads(json.dumps(valid))
        two["dimensions"].pop()
        invalids.append(two)
        duplicate = json.loads(json.dumps(valid))
        duplicate["dimensions"][1]["project_ids"].append(duplicate["dimensions"][0]["project_ids"][0])
        invalids.append(duplicate)
        missing = json.loads(json.dumps(valid))
        missing["dimensions"][0]["project_ids"].pop()
        invalids.append(missing)
        for config in invalids:
            with TemporaryDirectory() as folder:
                self.assert_code("INVALID_DATA", self.fixture_store, folder, config)

    def test_local_data_corruption_cannot_be_hidden_by_rehashing_import_index(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "candidates"
            shutil.copytree(DATA_ROOT, root)
            bundle = root / "handoff-v1"
            index_path = bundle / "import-manifest.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            entry = index["files"]["candidates"]
            path = bundle / entry["file"]
            content = path.read_bytes().replace("工程伦理".encode(), "工程道德".encode())
            path.write_bytes(content)
            entry["sha256"], entry["bytes"] = sha256(content), len(content)
            index_path.write_text(json.dumps(index), encoding="utf-8")
            self.assert_code("INVALID_DATA", CandidateStore, root)


class HandoffImportTests(unittest.TestCase):
    def packaged_archive(self, path):
        """Repack only audited retained inputs for an isolated importer round trip."""
        bundle = DATA_ROOT / "handoff-v1"
        manifest = json.loads((bundle / RETAINED_FILES["upstream_manifest"]).read_text(encoding="utf-8"))
        retained_names = set(RETAINED_FILES.values())
        manifest["outputs"] = [entry for entry in manifest["outputs"] if entry["file"] in retained_names]
        manifest["source_inputs"] = [entry for entry in manifest["source_inputs"] if "sources/" + entry["file"] in retained_names]
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in retained_names:
                content = json.dumps(manifest, ensure_ascii=False).encode() if name == RETAINED_FILES["upstream_manifest"] else (bundle / name).read_bytes()
                archive.writestr(name, content)

    def test_import_roundtrip_is_idempotent_and_never_overwrites_changed_data(self):
        with TemporaryDirectory() as folder:
            archive = Path(folder) / "handoff.zip"
            output = Path(folder) / "import"
            self.packaged_archive(archive)
            self.assertFalse(import_handoff(archive, output)["unchanged"])
            self.assertTrue(import_handoff(archive, output)["unchanged"])
            candidate_path = output / RETAINED_FILES["candidates"]
            candidate_path.write_text("user data", encoding="utf-8")
            with self.assertRaises(DataError) as caught:
                import_handoff(archive, output)
            self.assertEqual(caught.exception.code, "OUTPUT_EXISTS")
            self.assertEqual(candidate_path.read_text(encoding="utf-8"), "user data")

    def test_unsafe_archive_and_hash_mismatch_are_rejected_without_output(self):
        with TemporaryDirectory() as folder:
            archive = Path(folder) / "unsafe.zip"
            output = Path(folder) / "not-created"
            with zipfile.ZipFile(archive, "w") as file:
                file.writestr("../outside.txt", "bad")
            with self.assertRaises(DataError) as caught:
                import_handoff(archive, output)
            self.assertEqual(caught.exception.code, "INVALID_HANDOFF")
            self.assertFalse(output.exists())
            self.packaged_archive(archive)
            # Rebuild without duplicate ZIP members so rejection specifically
            # exercises source-hash validation rather than duplicate detection.
            original = archive.read_bytes()
            with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(archive, "w") as target:
                for name in source.namelist():
                    target.writestr(name, b"bad" if name == RETAINED_FILES["candidates"] else source.read(name))
            with self.assertRaises(DataError) as caught:
                import_handoff(archive, output)
            self.assertEqual(caught.exception.code, "INVALID_HANDOFF")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
