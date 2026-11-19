"""Read the audited 18-goal candidate bank and apply questionnaire selection.

The upper-level goal dimensions are explicit configuration, independent of both
source volumes and the original within-project item dimensions. No model,
network, scoring, or release approval is involved in this module.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
import sys

from import_candidate_handoff import csv_rows, raw_signature, sha256
from survey_data import DataError, StructuredParser, make_result_envelope, read_json


DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "candidates"
CORE_BANK = "核心候选题库"
BACKUP_BANK = "备份候选题库"
APPROVAL_FIELDS = ("text_approval", "bank_approval", "merge_approval", "scoring_approval", "scale_approval")
ALIASES = {
    "patriotic-attitude": ("爱国主义", "patriotism"),
    "student-core-competencies": ("core-literacy",),
    "cooperation-social-ability": ("cooperation-social",),
}


def _invalid(message: str, **details):
    raise DataError("INVALID_DATA", message, details=[details] if details else [])


class CandidateStore:
    def __init__(self, data_root: Path | str = DATA_ROOT, dimensions_path: Path | str | None = None):
        self.root = Path(data_root).resolve()
        self.bundle = self.root / "handoff-v1"
        self.index = read_json(self.bundle / "import-manifest.json")
        if self.index.get("schema_version") != 1 or self.index.get("data_version") != "consolidation-v1":
            _invalid("候选数据导入版本不受支持。")
        self._tables = {}
        self._headers = {}
        self._files = {}
        roles = {"candidates", "sources", "decisions", "projects", "exceptions", "overlaps",
                 "validation_log", "original_rows", "upstream_manifest"}
        if set(self.index.get("files", {})) != roles:
            _invalid("候选数据导入清单不完整。")
        for role, entry in self.index["files"].items():
            path = self._path(entry.get("file"))
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise DataError("INVALID_DATA", "候选数据文件无法读取。", details=[{"role": role}]) from exc
            if len(content) != entry.get("bytes") or sha256(content) != entry.get("sha256"):
                _invalid("候选数据文件与导入清单不一致。", role=role)
            self._files[role] = content
            if path.suffix == ".csv":
                header, records = csv_rows(content, path.name)
                self._headers[role], self._tables[role] = header, records
        self.manifest = read_json(self._path(self.index["files"]["upstream_manifest"]["file"]))
        self._candidate_index = self._unique("candidates", "candidate_id")
        self._source_index = self._unique("sources", "source_record_id")
        self._decision_index = self._unique("decisions", "decision_event_id")
        self._project_index = self._unique("projects", "project_slug")
        config_path = Path(dimensions_path) if dimensions_path is not None else self.root / "dimensions.json"
        self.dimension_config_path = config_path.resolve()
        self.dimension_config = read_json(config_path)
        self._dimension_map = self._read_dimensions()
        self._related_dimensions = self._read_related_dimensions()
        self.validate()

    def _path(self, relative):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            _invalid("候选数据清单路径不合法。")
        path = (self.bundle / relative).resolve()
        if not path.is_relative_to(self.bundle.resolve()) or path == self.bundle.resolve():
            _invalid("候选数据清单路径超出数据目录。")
        return path

    def _unique(self, role, key):
        records = self._tables[role]
        values = [record.get(key) for record in records]
        if any(not value for value in values) or len(values) != len(set(values)):
            _invalid("候选数据主键为空或重复。", role=role, key=key)
        return dict(zip(values, records))

    def _read_dimensions(self):
        config = self.dimension_config
        if config.get("schema_version") != 1 or not isinstance(config.get("dimensions"), list):
            _invalid("上位维度配置结构不正确。")
        if config.get("status") == "pending_user_confirmation" and not config["dimensions"]:
            return {}
        if config.get("status") != "confirmed" or len(config["dimensions"]) != 3:
            _invalid("上位维度必须为三个且归属已经明确确认。")
        result, ids = {}, set()
        names = set()
        for dimension in config["dimensions"]:
            if not isinstance(dimension, dict):
                _invalid("上位维度记录必须为对象。")
            identity, name, project_ids = dimension.get("id"), dimension.get("name"), dimension.get("project_ids")
            if (not isinstance(identity, str) or not identity.strip() or identity in ids or
                    not isinstance(name, str) or not name.strip() or name in names or
                    not isinstance(project_ids, list) or not project_ids):
                _invalid("上位维度名称、标识或项目列表不合法。")
            ids.add(identity)
            names.add(name)
            for project_id in project_ids:
                if not isinstance(project_id, str) or project_id not in self._project_index or project_id in result:
                    _invalid("每个价值目标必须且只能归属一个上位维度。")
                result[project_id] = {"id": identity, "name": name}
        if set(result) != set(self._project_index):
            _invalid("上位维度配置必须完整覆盖18个价值目标。")
        source = config.get("mapping_source")
        if source is not None:
            if not isinstance(source, dict) or not isinstance(source.get("file"), str):
                _invalid("上位维度来源证据记录不正确。")
            path = (self.dimension_config_path.parent / source["file"]).resolve()
            if not path.is_relative_to(self.dimension_config_path.parent) or path == self.dimension_config_path.parent:
                _invalid("上位维度来源证据路径不合法。")
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise DataError("INVALID_DATA", "上位维度来源证据文件无法读取。") from exc
            if sha256(content) != source.get("sha256"):
                _invalid("上位维度来源证据与记录的校验值不一致。")
        return result

    def _read_related_dimensions(self):
        """Related dimensions are navigation metadata, never a selection quota."""
        related = self.dimension_config.get("project_related_dimensions")
        if related is None:
            return {project_id: [] for project_id in self._project_index}
        if not isinstance(related, dict) or set(related) != set(self._project_index):
            _invalid("关联维度配置必须逐项目完整记录（无关联时为空数组）。")
        dimensions = {dimension["id"]: {"id": dimension["id"], "name": dimension["name"]}
                      for dimension in self.dimension_config["dimensions"]}
        result = {}
        for project_id, values in related.items():
            if (not isinstance(values, list) or any(not isinstance(value, str) for value in values)
                    or len(values) != len(set(values)) or any(value not in dimensions for value in values)
                    or self._dimension_map.get(project_id, {}).get("id") in values):
                _invalid("关联维度必须为其他合法一级维度，不能重复或与主归属相同。")
            result[project_id] = [deepcopy(dimensions[value]) for value in values]
        return result

    @property
    def candidates(self):
        return deepcopy(self._tables["candidates"])

    @property
    def sources(self):
        return deepcopy(self._tables["sources"])

    @property
    def decisions(self):
        return deepcopy(self._tables["decisions"])

    def validate(self):
        """Verify local hashes, raw-field preservation, counts, and all edges."""
        expected = self.manifest.get("counts", {})
        if self.manifest.get("schema_version") != "kcsz-18project-consolidation-v1":
            _invalid("原始交接清单版本不受支持。")
        counts = {"projects": len(self._project_index), "raw_source_rows": len(self._source_index),
                  "unified_candidates": len(self._candidate_index), "teacher_events": len(self._decision_index),
                  "priority_exceptions": len(self._tables["exceptions"]),
                  "overlap_screen_top100": len(self._tables["overlaps"]),
                  "qa_checks_passed": len(self._tables["validation_log"])}
        banks = Counter(record.get("bank") for record in self._candidate_index.values())
        counts.update(core_candidates=banks[CORE_BANK], backup_candidates=banks[BACKUP_BANK])
        if set(banks) != {CORE_BANK, BACKUP_BANK}:
            _invalid("每道候选题必须恰好属于核心或备份题库。")
        for key, value in counts.items():
            if value != expected.get(key) or value != self.index.get("counts", {}).get(key):
                _invalid("候选数据数量与交接清单不一致。", count=key, actual=value)
        if (counts["projects"], counts["raw_source_rows"], counts["unified_candidates"]) != (18, 505, 482):
            _invalid("本数据版本必须为18个项目、505条来源、482道候选。")
        upstream = {entry["file"]: entry for entry in self.manifest.get("outputs", [])}
        upstream.update({"sources/" + entry["file"]: entry for entry in self.manifest.get("source_inputs", [])})
        for role, entry in self.index["files"].items():
            if role != "upstream_manifest":
                original = upstream.get(entry["file"])
                if original is None or original["sha256"] != sha256(self._files[role]):
                    _invalid("本地导入数据与原始交接清单不一致。", role=role)
        raw_fields = self._headers["original_rows"]
        try:
            originals = Counter(raw_signature(row, raw_fields) for row in self._tables["original_rows"])
            retained = Counter(raw_signature(row, raw_fields, "raw_") for row in self._source_index.values())
            if len(raw_fields) != 30 or originals != retained:
                _invalid("505条来源的30个原始字段未完整保留。")
            if any(raw_signature(row, raw_fields, "raw_") != row["source_integrity_sha256"]
                   for row in self._source_index.values()):
                _invalid("来源记录的原始字段校验值不一致。")
            for candidate in self._candidate_index.values():
                self._validate_candidate(candidate)
            for source in self._source_index.values():
                candidate = self._candidate_index[source["mapped_candidate_id"]]
                if source["source_record_id"] not in candidate["source_record_ids"].split("|"):
                    _invalid("来源与候选反向引用不一致。")
            for record in self._tables["exceptions"]:
                if record["candidate_id"] not in self._candidate_index:
                    _invalid("优先例外引用不存在的候选题。")
            for record in self._tables["overlaps"]:
                if any(record[key] not in self._candidate_index for key in ("candidate_id_a", "candidate_id_b")):
                    _invalid("近似筛查引用不存在的候选题。")
            self._validate_project_counts()
        except (KeyError, TypeError, ValueError) as exc:
            raise DataError("INVALID_DATA", "候选数据字段或引用格式不正确。") from exc
        if any(row["pass"] != "True" for row in self._tables["validation_log"]):
            _invalid("交接数据包含未通过的历史检查记录。")
        counts["merged_candidates"] = sum(int(row["source_count"]) == 2 for row in self._candidate_index.values())
        counts["risk_P_not_classified"] = sum(not row["risk_level"] for row in self._candidate_index.values())
        if counts["merged_candidates"] != expected.get("merged_candidates") or counts["risk_P_not_classified"] != expected.get("risk_P_not_classified"):
            _invalid("来源合并或风险缺失数量与交接清单不一致。")
        return {"valid": True, "data_version": self.index["data_version"], "counts": counts,
                "dimension_mapping": "confirmed" if self._dimension_map else "pending_user_confirmation",
                "release_eligible": False, "validation_scope": "data_integrity_only"}

    def _validate_candidate(self, candidate):
        project = self._project_index[candidate["project_slug"]]
        if (candidate["project_id"], candidate["project_name"]) != (project["project_id"], project["project_name"]):
            _invalid("候选题的项目标识与目录不一致。")
        if not candidate["item_text_zh"].strip() or not candidate["original_dimension"].strip():
            _invalid("候选题题文或原始维度缺失。")
        if any(not candidate[field].strip() for field in APPROVAL_FIELDS):
            _invalid("五类独立确认状态必须完整保留。")
        if candidate["release_eligible"] != "否":
            _invalid("当前研究交接版本不能被改为已批准正式施测。")
        if candidate["risk_level"] not in {"", "P0", "P1", "P2"}:
            _invalid("候选题风险等级不合法。")
        source_ids = candidate["source_record_ids"].split("|")
        if len(source_ids) != int(candidate["source_count"]) or len(source_ids) != len(set(source_ids)) or len(source_ids) not in {1, 2}:
            _invalid("候选题来源数量不一致。")
        for source_id in source_ids:
            source = self._source_index[source_id]
            if (source["mapped_candidate_id"], source["project_id"]) != (candidate["candidate_id"], candidate["project_id"]):
                _invalid("候选题与来源引用不一致或发生跨项目合并。")
        if not set(filter(None, candidate["teacher_decision_ids"].split("|"))).issubset(self._decision_index):
            _invalid("候选题教师确认引用不存在。")

    def _validate_project_counts(self):
        for project in self._project_index.values():
            candidates = [row for row in self._candidate_index.values() if row["project_slug"] == project["project_slug"]]
            sources = [row for row in self._source_index.values() if row["project_id"] == project["project_id"]]
            actual = {"original_source_count": len(sources), "unified_candidate_count": len(candidates),
                      "core_count": sum(row["bank"] == CORE_BANK for row in candidates),
                      "backup_count": sum(row["bank"] == BACKUP_BANK for row in candidates),
                      "merged_candidates_count": sum(int(row["source_count"]) == 2 for row in candidates),
                      "risk_not_P_classified_count": sum(not row["risk_level"] for row in candidates)}
            actual.update({level + "_count": sum(row["risk_level"] == level for row in candidates) for level in ("P0", "P1", "P2")})
            if any(value != int(project[key]) for key, value in actual.items()):
                _invalid("逐项目数量与项目汇总不一致。", project_id=project["project_slug"])

    def list_projects(self):
        result = []
        for row in sorted(self._project_index.values(), key=lambda value: int(value["project_id"])):
            dimension = self._dimension_map.get(row["project_slug"], {})
            result.append({"id": row["project_slug"], "name": row["project_name"],
                           "number": int(row["project_id"]), "dimension_id": dimension.get("id"),
                           "dimension_name": dimension.get("name"),
                           "primary_dimension": deepcopy(dimension) if dimension else None,
                           "related_dimensions": deepcopy(self._related_dimensions[row["project_slug"]]),
                           "candidate_count": int(row["unified_candidate_count"]),
                           "core_count": int(row["core_count"]), "backup_count": int(row["backup_count"]),
                           "aliases": list(ALIASES.get(row["project_slug"], ()))})
        return result

    def resolve_project(self, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 120 or any(ord(ch) < 32 for ch in query):
            raise DataError("INVALID_REQUEST", "价值目标必须是非空的项目名称或标识。")
        key = query.strip().casefold()
        matches = [project for project in self.list_projects()
                   if key in {project["id"].casefold(), project["name"].casefold(), str(project["number"]),
                              *(alias.casefold() for alias in project["aliases"])}]
        if not matches:
            raise DataError("PROJECT_NOT_FOUND", "未找到该价值目标，请从18个目标目录中选择。",
                            candidates=self.list_projects())
        if len(matches) != 1:
            raise DataError("AMBIGUOUS_PROJECT", "价值目标名称不明确。", candidates=matches)
        return matches[0]

    def select_projects(self, queries, question_count=None, seed=0):
        if not isinstance(queries, (list, tuple)) or not queries:
            raise DataError("INVALID_REQUEST", "请至少选择一个价值目标。")
        if len(queries) > 6:
            raise DataError("TOO_MANY_PROJECTS", "一次最多选择6个价值目标。")
        projects = [self.resolve_project(query) for query in queries]
        project_ids = [project["id"] for project in projects]
        if len(set(project_ids)) != len(project_ids):
            raise DataError("DUPLICATE_PROJECT", "同一价值目标不能重复选择（名称与别名也视为同一个目标）。")
        multiple = len(projects) > 1
        if multiple and not self._dimension_map:
            raise DataError("DIMENSION_MAPPING_REQUIRED", "三个上位维度与18个价值目标的归属尚待明确，暂不能校验多目标选择。",
                            details=[{"required": "confirmed dimensions.json with all 18 project assignments"}])
        dimension_counts = Counter(project["dimension_id"] for project in projects if project["dimension_id"])
        excessive = [key for key, value in dimension_counts.items() if value > 3]
        if excessive:
            raise DataError("TOO_MANY_PROJECTS_IN_DIMENSION", "同一个维度最多选择3个价值目标。",
                            details=[{"dimension_id": key, "count": dimension_counts[key]} for key in excessive])
        # Project order follows the explicit request, item order follows the
        # audited source. P0 and release flags are retained, never filtered out.
        pools = {project_id: [row for row in self._candidate_index.values()
                              if row["project_slug"] == project_id and (not multiple or row["bank"] == CORE_BANK)]
                 for project_id in project_ids}
        available_count = sum(len(pool) for pool in pools.values())
        minimum_count = len(projects) if multiple else 1
        if type(seed) is not int:
            raise DataError("INVALID_SAMPLING_SEED", "抽题种子必须是整数。")
        if question_count is None and seed != 0:
            raise DataError("INVALID_SAMPLING_SEED", "指定抽题种子时必须同时指定选题总数。")
        if question_count is not None and (type(question_count) is not int or
                                          not minimum_count <= question_count <= available_count):
            raise DataError("INVALID_QUESTION_COUNT", "选题总数须为可用范围内的整数，且每个目标至少保留一道题。",
                            details=[{"question_count": question_count if type(question_count) in (int, str, bool) else None,
                                      "provided_type": type(question_count).__name__,
                                      "minimum": minimum_count, "maximum": available_count,
                                      "project_count": len(projects)}])
        sampling = question_count is not None and question_count < available_count
        allocations = {project_id: len(pool) for project_id, pool in pools.items()}
        if sampling:
            # Round-robin quotas balance projects before sampling. Full pools
            # stop receiving quota, and remaining places go to other projects
            # in request order. Banks never receive separate weights.
            allocations = dict.fromkeys(project_ids, 0)
            remaining = question_count
            while remaining:
                for project_id in project_ids:
                    if allocations[project_id] < len(pools[project_id]):
                        allocations[project_id] += 1
                        remaining -= 1
                        if not remaining:
                            break
            rng = random.Random(seed)
            candidates = []
            for project_id, pool in pools.items():
                sampled_ids = {row["candidate_id"] for row in rng.sample(pool, allocations[project_id])}
                candidates.extend(deepcopy(row) for row in pool if row["candidate_id"] in sampled_ids)
        else:
            candidates = [deepcopy(row) for pool in pools.values() for row in pool]
        mode = ("multiple_core_sample" if multiple else "single_sample") if sampling else (
            "multiple_core" if multiple else "single_all")
        selection = {"mode": mode, "project_ids": project_ids,
                     "project_count": len(projects), "bank_policy": "core_only" if multiple else "core_and_backup",
                     "dimension_counts": dict(dimension_counts), "dimension_counting": "primary_dimension_only",
                     "question_count_requested": question_count, "available_candidate_count": available_count,
                     "sampling_method": ("balanced_projects_uniform_within_project" if multiple else
                                         "uniform_without_bank_priority") if sampling else "all",
                     "sampling_seed": seed if sampling else None,
                     "allocation_method": "round_robin_in_request_order_with_capacity_limits" if sampling and multiple else None,
                     "project_question_counts": allocations,
                     "candidate_count": len(candidates),
                     "candidate_ids": [row["candidate_id"] for row in candidates]}
        return {"projects": projects, "candidates": candidates, "selection": selection,
                "review": self.review_status(candidates)}

    def source_records_for(self, candidate_id):
        candidate = self._candidate(candidate_id)
        return [deepcopy(self._source_index[key]) for key in candidate["source_record_ids"].split("|")]

    def decision_records_for(self, candidate_id):
        candidate = self._candidate(candidate_id)
        return [deepcopy(self._decision_index[key]) for key in filter(None, candidate["teacher_decision_ids"].split("|"))]

    def _candidate(self, candidate_id):
        if not isinstance(candidate_id, str) or candidate_id not in self._candidate_index:
            raise DataError("CANDIDATE_NOT_FOUND", "未找到该候选题。")
        return self._candidate_index[candidate_id]

    @staticmethod
    def review_status(candidates):
        risks = Counter(row["risk_level"] or "unclassified" for row in candidates)
        return {"purpose": "review", "release_eligible": False, "risk_counts": dict(risks),
                "blocked_candidate_ids": [row["candidate_id"] for row in candidates if
                                          row["release_eligible"] != "是" or row["risk_level"] == "P0" or
                                          not row["risk_level"] or "暂缓" in row["activation_status"]],
                "english_missing_count": sum(not row["item_text_en"] for row in candidates),
                "note": "候选审查稿；选入不改变五类确认、风险或正式施测许可，不进行自动计分。"}

    def assert_survey_eligible(self, candidates):
        status = self.review_status(candidates)
        if status["blocked_candidate_ids"]:
            raise DataError("SURVEY_RELEASE_BLOCKED", "所选候选题尚未全部获准正式施测；只能生成候选审查稿。",
                            details=[{"blocked_candidate_ids": status["blocked_candidate_ids"],
                                      "risk_counts": status["risk_counts"]}])


def main(argv=None):
    parser = StructuredParser(description="18个价值目标候选数据查询与选择；不施测、不计分。")
    commands = parser.add_subparsers(dest="operation", required=True, parser_class=StructuredParser)
    commands.add_parser("list")
    commands.add_parser("validate")
    select = commands.add_parser("select")
    select.add_argument("--project", action="append", required=True)
    select.add_argument("--question-count", type=int, help="整份问卷选题总数；省略时使用全部可用题")
    select.add_argument("--seed", type=int, help="指定题数时的可复现抽题种子；默认0")
    args = None
    try:
        args = parser.parse_args(argv)
        if args.operation == "select" and args.seed is not None and args.question_count is None:
            raise DataError("INVALID_REQUEST", "指定抽题种子时必须同时指定选题总数。")
        store = CandidateStore()
        result = store.list_projects() if args.operation == "list" else store.validate() if args.operation == "validate" else store.select_projects(args.project, args.question_count, 0 if args.seed is None else args.seed)
        envelope, code = make_result_envelope(args.operation, result, title="18项目候选题库"), 0
    except DataError as exc:
        envelope, code = make_result_envelope(getattr(args, "operation", None), error=exc), 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
