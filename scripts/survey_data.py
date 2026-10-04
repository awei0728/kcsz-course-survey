"""Read and validate the local questionnaire collection; standard library only.

This module does not generate surveys, score answers, or invoke a model/service.
Resource paths are relative to this file, independent of the process cwd.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any
import uuid


SKILL_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = SKILL_ROOT / "data"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
KINDS = {"rating", "choice", "open", "ranking", "unknown"}


class DataError(Exception):
    def __init__(self, code: str, message: str, *, details=None, candidates=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []
        self.candidates = candidates or []


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite JSON number: {value}")
    return number


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"),
                           object_pairs_hook=_unique_object, parse_constant=_reject_constant,
                           parse_float=_finite_float)
    except (OSError, UnicodeError, ValueError) as exc:
        raise DataError("INVALID_DATA", "数据文件无法读取或不是合法的 UTF-8 JSON。",
                        details=[{"file": path.name, "reason": str(exc)}]) from exc
    if not isinstance(value, dict):
        raise DataError("INVALID_DATA", "数据文件根节点必须是对象。", details=[{"file": path.name}])
    return value


def _validate_questionnaire(doc: Any, source_page_counts: dict | None = None) -> list[dict]:
    """Validate structure and evidence/status consistency, never certify transcription."""
    errors: list[dict] = []

    def error(path, code, message):
        errors.append({"path": path, "code": code, "message": message})

    def required(obj, names, path):
        if not isinstance(obj, dict):
            error(path, "OBJECT_REQUIRED", "必须是对象")
            return False
        for name in names:
            if name not in obj:
                error(f"{path}.{name}", "MISSING_FIELD", "缺少必要字段")
        return True

    def text(value, path, nullable=False):
        if nullable and value is None:
            return
        if not isinstance(value, str) or not value.strip():
            error(path, "TEXT_REQUIRED", "必须是非空文字")

    def array(value, path):
        if not isinstance(value, list):
            error(path, "ARRAY_REQUIRED", "必须是数组")
            return []
        return value

    def location(value, path):
        if not required(value, ["pdf_pages", "printed_pages"], path):
            return
        pdf = array(value.get("pdf_pages"), path + ".pdf_pages")
        printed = array(value.get("printed_pages"), path + ".printed_pages")
        if not pdf or len(pdf) != len(printed):
            error(path, "SOURCE_PAGES", "PDF 页序与印刷页码必须非空且逐页对应")
        for key, pages in (("pdf_pages", pdf), ("printed_pages", printed)):
            if any(type(p) is not int or p < 1 for p in pages):
                error(path + "." + key, "SOURCE_PAGES", "正文来源页码必须是从1起的整数")
            elif pages != sorted(set(pages)):
                error(path + "." + key, "SOURCE_PAGES", "页码必须唯一且按原顺序排列")
        if all(type(p) is int for p in pdf + printed):
            # Both supplied editions have three front-matter pages; this is a
            # validated source convention, not a general PDF page assumption.
            if any(p - q != 3 for p, q in zip(pdf, printed)):
                error(path, "SOURCE_PAGE_MAPPING", "这两辑正文 PDF 页与印刷页必须相差3")
            limit = (source_page_counts or {}).get(doc.get("source", {}).get("filename"))
            if limit and any(p > limit for p in pdf):
                error(path, "SOURCE_PAGE_RANGE", "来源 PDF 页序超过文件总页数")

    if not required(doc, ["schema_version", "id", "project_id", "version_id", "project_name",
                          "original_name", "original_name_reason", "title", "source", "instructions",
                          "basic_information", "items", "groups", "blocks", "scoring", "counts",
                          "issues", "review"], "$" ):
        return errors
    if doc.get("schema_version") != 1:
        error("$.schema_version", "SCHEMA_VERSION", "仅支持数据版本1")
    for name in ("id", "project_id", "version_id", "project_name"):
        text(doc.get(name), "$." + name)
    if isinstance(doc.get("project_id"), str) and not ID_PATTERN.fullmatch(doc["project_id"]):
        error("$.project_id", "INVALID_ID", "项目标识应为小写英文数字和短横线")
    if doc.get("id") != f"{doc.get('project_id')}--{doc.get('version_id')}":
        error("$.id", "IDENTITY_MISMATCH", "问卷标识必须对应项目与版本")
    text(doc.get("original_name"), "$.original_name", nullable=True)
    if doc.get("original_name") is None:
        text(doc.get("original_name_reason"), "$.original_name_reason")
    source = doc.get("source")
    if required(source, ["filename", "volume", "chapter", "pdf_pages", "printed_pages", "sha256"], "$.source"):
        for key in ("filename", "chapter", "sha256"):
            text(source.get(key), "$.source." + key)
        filename = source.get("filename")
        if isinstance(filename, str) and (Path(filename).name != filename or "/" in filename or "\\" in filename):
            error("$.source.filename", "SOURCE_FILENAME", "来源应为原始文件名，不是路径")
        if source.get("volume") not in (1, 2):
            error("$.source.volume", "SOURCE_VOLUME", "来源辑别必须是1或2")
        if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", ""))):
            error("$.source.sha256", "SOURCE_HASH", "必须记录来源 SHA-256")
        location(source, "$.source")
    title = doc.get("title")
    if required(title, ["raw_text", "student_text", "source"], "$.title"):
        text(title.get("raw_text"), "$.title.raw_text")
        text(title.get("student_text"), "$.title.student_text", nullable=True)
        location(title.get("source"), "$.title.source")

    groups = array(doc.get("groups"), "$.groups")
    group_ids = set()
    for i, group in enumerate(groups):
        path = f"$.groups[{i}]"
        if not required(group, ["id", "raw_name", "source", "parent_id", "note"], path):
            continue
        text(group.get("id"), path + ".id")
        gid = group.get("id")
        if isinstance(gid, str):
            if gid in group_ids:
                error(path + ".id", "DUPLICATE_GROUP_ID", "分组标识重复")
            group_ids.add(gid)
        text(group.get("raw_name"), path + ".raw_name")
        location(group.get("source"), path + ".source")
    for i, group in enumerate(groups):
        if isinstance(group, dict) and group.get("parent_id") is not None and group.get("parent_id") not in group_ids:
            error(f"$.groups[{i}].parent_id", "UNKNOWN_GROUP", "父分组不存在")

    issues = array(doc.get("issues"), "$.issues")
    issue_ids = set()
    unresolved = []
    for i, issue in enumerate(issues):
        path = f"$.issues[{i}]"
        if not required(issue, ["id", "category", "blocking", "source", "original_text",
                                "missing_information", "possible_resolutions", "recommendation",
                                "affected_item_ids", "resolution"], path):
            continue
        for key in ("id", "original_text", "missing_information", "recommendation"):
            text(issue.get(key), path + "." + key)
        iid = issue.get("id")
        if isinstance(iid, str):
            if iid in issue_ids:
                error(path + ".id", "DUPLICATE_ISSUE_ID", "疑点标识重复")
            issue_ids.add(iid)
        if issue.get("category") not in {"textual", "blocking", "metadata"}:
            error(path + ".category", "ISSUE_CATEGORY", "疑点必须区分文字/阻断/元数据")
        if type(issue.get("blocking")) is not bool:
            error(path + ".blocking", "BOOLEAN_REQUIRED", "必须明确是否阻断")
        if issue.get("category") == "blocking" and issue.get("blocking") is not True:
            error(path, "ISSUE_CATEGORY", "阻断类别必须标为阻断")
        if issue.get("resolution") is not None:
            text(issue.get("resolution"), path + ".resolution")
        if issue.get("blocking") and issue.get("resolution") is None:
            unresolved.append(issue)
        location(issue.get("source"), path + ".source")
        resolutions = array(issue.get("possible_resolutions"), path + ".possible_resolutions")
        if not resolutions:
            error(path, "ISSUE_RESOLUTIONS", "必须保留可选处理方式")
        for j, resolution in enumerate(resolutions):
            text(resolution, f"{path}.possible_resolutions[{j}]")
        array(issue.get("affected_item_ids"), path + ".affected_item_ids")

    all_ids = set()
    item_ids = set()
    response_unknown_items = set()
    collections = (("basic_information", array(doc.get("basic_information"), "$.basic_information")),
                   ("items", array(doc.get("items"), "$.items")))
    item_required = ["id", "order", "original_number", "role", "measurement_class", "kind", "raw_text",
                     "student_text", "source", "group_id", "subdimension", "subdimension_reason",
                     "teacher_annotations", "reverse", "response"]
    response_required = ["options", "minimum", "maximum", "cardinality", "slots", "raw_instruction",
                         "unknowns", "ranking"]
    for name, records in collections:
        for i, item in enumerate(records):
            path = f"$.{name}[{i}]"
            if not required(item, item_required, path):
                continue
            text(item.get("id"), path + ".id")
            item_id = item.get("id")
            if isinstance(item_id, str):
                if item_id in all_ids:
                    error(path + ".id", "DUPLICATE_ITEM_ID", "题项标识重复")
                all_ids.add(item_id)
                if name == "items":
                    item_ids.add(item_id)
            if item.get("order") != i + 1 or type(item.get("order")) is not int:
                error(path + ".order", "ITEM_ORDER", "所属数组的原顺序必须从1连续")
            expected_roles = {"basic_information"} if name == "basic_information" else {"measurement", "background"}
            if item.get("role") not in expected_roles:
                error(path + ".role", "ITEM_ROLE", "基本信息与测量/背景题必须分开")
            if item.get("original_number") is not None:
                text(item.get("original_number"), path + ".original_number")
            if item.get("measurement_class") not in {None, "scale", "preliminary", "mixed"}:
                error(path + ".measurement_class", "ITEM_CLASS", "测量类别不合法")
            if item.get("kind") not in KINDS:
                error(path + ".kind", "ITEM_KIND", "题型不合法")
            text(item.get("raw_text"), path + ".raw_text")
            text(item.get("student_text"), path + ".student_text")
            location(item.get("source"), path + ".source")
            if item.get("group_id") is not None and item.get("group_id") not in group_ids:
                error(path + ".group_id", "UNKNOWN_GROUP", "题项引用了不存在的分组")
            if item.get("subdimension") is None:
                text(item.get("subdimension_reason"), path + ".subdimension_reason")
            annotations = array(item.get("teacher_annotations"), path + ".teacher_annotations")
            for j, annotation in enumerate(annotations):
                apath = f"{path}.teacher_annotations[{j}]"
                if required(annotation, ["text", "kind", "visibility", "source"], apath):
                    text(annotation.get("text"), apath + ".text")
                    location(annotation.get("source"), apath + ".source")
                    if annotation.get("kind") not in {"reverse", "concept", "note"}:
                        error(apath + ".kind", "ANNOTATION_KIND", "教师标记类型不合法")
                    if annotation.get("visibility") not in {"teacher", "undecided"}:
                        error(apath + ".visibility", "ANNOTATION_VISIBILITY", "展示属性必须明确或待决")
            reverse = item.get("reverse")
            if required(reverse, ["marked", "raw_marker", "source", "reason"], path + ".reverse"):
                if reverse.get("marked") is not None and type(reverse.get("marked")) is not bool:
                    error(path + ".reverse.marked", "REVERSE_FLAG", "反向状态必须为true/false/null")
                if reverse.get("marked") is True:
                    text(reverse.get("raw_marker"), path + ".reverse.raw_marker")
                    location(reverse.get("source"), path + ".reverse.source")
                    if "反向检测题" in str(item.get("student_text", "")):
                        error(path + ".student_text", "TEACHER_MARKER_LEAK", "学生题干不能含反向检测提示")
                    if not any(isinstance(a, dict) and a.get("kind") == "reverse" for a in annotations):
                        error(path + ".teacher_annotations", "REVERSE_EVIDENCE", "反向标记必须单独保存")
                elif reverse.get("marked") is None:
                    text(reverse.get("reason"), path + ".reverse.reason")

            response = item.get("response")
            if not required(response, response_required, path + ".response"):
                continue
            rpath = path + ".response"
            options = array(response.get("options"), rpath + ".options")
            unknowns = array(response.get("unknowns"), rpath + ".unknowns")
            for j, unknown in enumerate(unknowns):
                if required(unknown, ["field", "reason"], f"{rpath}.unknowns[{j}]"):
                    text(unknown.get("field"), f"{rpath}.unknowns[{j}].field")
                    text(unknown.get("reason"), f"{rpath}.unknowns[{j}].reason")
            option_ids = set()
            for j, option in enumerate(options):
                opath = f"{rpath}.options[{j}]"
                if not required(option, ["id", "label", "value", "source"], opath):
                    continue
                text(option.get("id"), opath + ".id")
                oid = option.get("id")
                if isinstance(oid, str):
                    if oid in option_ids:
                        error(opath + ".id", "DUPLICATE_OPTION_ID", "同一响应内选项标识重复")
                    option_ids.add(oid)
                text(option.get("label"), opath + ".label", nullable=True)
                if option.get("label") is None and not unknowns:
                    error(opath + ".label", "UNKNOWN_REASON", "未命名等级必须保留未知原因")
                number = option.get("value")
                if number is not None and (type(number) not in (int, float) or
                                           (type(number) is float and not math.isfinite(number))):
                    error(opath + ".value", "OPTION_VALUE", "原分值必须为有限数值或null")
                location(option.get("source"), opath + ".source")
            kind = item.get("kind")
            if kind == "rating":
                low, high = response.get("minimum"), response.get("maximum")
                if type(low) is not int or type(high) is not int or low >= high:
                    error(rpath, "RATING_RANGE", "评分题必须明确有效的整数等级范围")
                else:
                    values = [o.get("value") if isinstance(o, dict) else None for o in options]
                    if (not all(type(v) is int for v in values) or
                            sorted(values) != list(range(low, high + 1))):
                        error(rpath + ".options", "RATING_OPTIONS", "评分题必须保留范围内全部档位及原分值")
                if response.get("cardinality") != "single":
                    error(rpath + ".cardinality", "RATING_CARDINALITY", "每评分行应只有一个作答等级")
            elif kind == "choice":
                if len(options) < 2 or any(not isinstance(o, dict) or not o.get("label") for o in options):
                    error(rpath + ".options", "CHOICE_OPTIONS", "选择题必须保存实际选项文字")
                if response.get("cardinality") not in {"single", "multiple", None}:
                    error(rpath + ".cardinality", "CHOICE_CARDINALITY", "选择基数不合法")
                if response.get("cardinality") is None:
                    response_unknown_items.add(item_id)
            elif kind == "open":
                if options:
                    error(rpath + ".options", "OPEN_OPTIONS", "开放题不应添加选择项")
                if response.get("slots") is not None and (type(response.get("slots")) is not int or response["slots"] < 1):
                    error(rpath + ".slots", "OPEN_SLOTS", "填写位置数须为正整数或有原因的null")
                if response.get("slots") is None and not unknowns:
                    error(rpath + ".slots", "UNKNOWN_REASON", "未知填写位置须给原因")
            elif kind == "ranking":
                if len(options) < 2:
                    error(rpath + ".options", "RANKING_OPTIONS", "排序题必须保存排序对象")
                ranking = response.get("ranking")
                if required(ranking, ["direction", "complete", "ties_allowed", "other_text"], rpath + ".ranking"):
                    if any(ranking.get(k) is None for k in ("direction", "complete", "ties_allowed")):
                        response_unknown_items.add(item_id)
            elif kind == "unknown":
                response_unknown_items.add(item_id)
                if not unknowns:
                    error(rpath, "UNKNOWN_REASON", "未知题型必须保留原因")

    blocked_items = {iid for issue in unresolved for iid in issue.get("affected_item_ids", []) if isinstance(iid, str)}
    for iid in response_unknown_items:
        if iid not in blocked_items:
            error("$.issues", "UNRECORDED_RESPONSE_BLOCKER", f"题项 {iid} 的响应未知必须关联未解阻断")
    for i, issue in enumerate(issues):
        if isinstance(issue, dict):
            for iid in issue.get("affected_item_ids", []):
                if iid not in all_ids:
                    error(f"$.issues[{i}].affected_item_ids", "UNKNOWN_ITEM", "疑点引用了不存在的题项")

    for i, instruction in enumerate(array(doc.get("instructions"), "$.instructions")):
        path = f"$.instructions[{i}]"
        if required(instruction, ["id", "role", "raw_text", "student_text", "source"], path):
            text(instruction.get("id"), path + ".id")
            text(instruction.get("raw_text"), path + ".raw_text")
            text(instruction.get("student_text"), path + ".student_text", nullable=True)
            location(instruction.get("source"), path + ".source")
            if instruction.get("role") not in {"guidance", "response", "teacher"}:
                error(path + ".role", "INSTRUCTION_ROLE", "说明角色不合法")
            if instruction.get("role") == "teacher" and instruction.get("student_text") is not None:
                error(path + ".student_text", "TEACHER_TEXT_LEAK", "教师说明不能直接作为学生说明")

    block_ids = set()
    for i, block in enumerate(array(doc.get("blocks"), "$.blocks")):
        path = f"$.blocks[{i}]"
        if required(block, ["id", "kind", "raw_title", "item_ids", "source", "note"], path):
            text(block.get("id"), path + ".id")
            bid = block.get("id")
            if isinstance(bid, str):
                if bid in block_ids:
                    error(path + ".id", "DUPLICATE_BLOCK_ID", "结构块标识重复")
                block_ids.add(bid)
            if block.get("kind") not in {"matrix", "section"}:
                error(path + ".kind", "BLOCK_KIND", "原结构块类型不合法")
            rows = array(block.get("item_ids"), path + ".item_ids")
            if len(rows) != len(set(str(x) for x in rows)):
                error(path + ".item_ids", "DUPLICATE_BLOCK_ROW", "原块引用行重复")
            if any(iid not in item_ids for iid in rows):
                error(path + ".item_ids", "UNKNOWN_ITEM", "结构块引用了不存在的测量/背景题")
            if block.get("kind") == "matrix" and not rows:
                error(path, "EMPTY_MATRIX", "原矩阵必须保存全部行引用")
            location(block.get("source"), path + ".source")

    scoring = doc.get("scoring")
    if required(scoring, ["raw_rules", "reverse_mapping", "unknowns"], "$.scoring"):
        for i, rule in enumerate(array(scoring.get("raw_rules"), "$.scoring.raw_rules")):
            if required(rule, ["raw_text", "source"], f"$.scoring.raw_rules[{i}]"):
                text(rule.get("raw_text"), f"$.scoring.raw_rules[{i}].raw_text")
                location(rule.get("source"), f"$.scoring.raw_rules[{i}].source")
        for i, unknown in enumerate(array(scoring.get("unknowns"), "$.scoring.unknowns")):
            if required(unknown, ["field", "reason", "source"], f"$.scoring.unknowns[{i}]"):
                text(unknown.get("reason"), f"$.scoring.unknowns[{i}].reason")
                location(unknown.get("source"), f"$.scoring.unknowns[{i}].source")
        mapping = scoring.get("reverse_mapping")
        if mapping is not None:
            for i, pair in enumerate(array(mapping, "$.scoring.reverse_mapping")):
                if required(pair, ["from", "to"], f"$.scoring.reverse_mapping[{i}]"):
                    if any(type(pair.get(k)) not in (int, float) or
                           (type(pair.get(k)) is float and not math.isfinite(pair[k]))
                           for k in ("from", "to")):
                        error("$.scoring.reverse_mapping", "SCORING_MAPPING", "原文明示计分映射必须是有限数值")

    counts = doc.get("counts")
    basic = collections[0][1]
    items = collections[1][1]
    if required(counts, ["basic_information", "measurement_items", "scale_items", "preliminary_items",
                         "background_items", "item_records", "original_question_blocks", "reason"], "$.counts"):
        actual = {"basic_information": len(basic), "item_records": len(items),
                  "preliminary_items": sum(isinstance(i, dict) and i.get("measurement_class") == "preliminary" for i in items),
                  "background_items": sum(isinstance(i, dict) and i.get("role") == "background" for i in items),
                  "measurement_items": sum(isinstance(i, dict) and i.get("role") == "measurement" for i in items),
                  "scale_items": sum(isinstance(i, dict) and i.get("kind") == "rating" for i in items)}
        for key, value in actual.items():
            reported = counts.get(key)
            nullable = key in {"measurement_items", "scale_items"}
            if nullable and reported is None:
                text(counts.get("reason"), "$.counts.reason")
            elif type(reported) is not int or reported != value:
                error("$.counts." + key, "COUNT_MISMATCH", "题数必须与记录和统计口径一致")
        blocks_count = counts.get("original_question_blocks")
        if blocks_count is not None and (type(blocks_count) is not int or blocks_count < 1):
            error("$.counts.original_question_blocks", "BLOCK_COUNT", "原题干块数应为正整数或null")

    review = doc.get("review")
    if required(review, ["status", "transcription_verified", "checked_pdf_pages", "method", "reviewed_on",
                         "eligible_for_generation", "note"], "$.review"):
        if review.get("status") not in {"verified", "needs_confirmation"}:
            error("$.review.status", "REVIEW_STATUS", "审核状态必须明确")
        for key in ("transcription_verified", "eligible_for_generation"):
            if type(review.get(key)) is not bool:
                error("$.review." + key, "BOOLEAN_REQUIRED", "审核标记必须是布尔值")
        for key in ("method", "reviewed_on", "note"):
            text(review.get(key), "$.review." + key)
        checked = array(review.get("checked_pdf_pages"), "$.review.checked_pdf_pages")
        if any(type(p) is not int or p < 1 for p in checked):
            error("$.review.checked_pdf_pages", "REVIEW_PAGES", "核对页序必须从1起")
        if review.get("transcription_verified") and not checked:
            error("$.review", "REVIEW_EVIDENCE", "原文核对标记须有人工核对记录")
        if unresolved and (review.get("status") != "needs_confirmation" or review.get("eligible_for_generation") is not False):
            error("$.review", "BLOCKER_STATUS_MISMATCH", "存在未解阻断，不能标已核对或可直接生成")
        if review.get("status") == "verified" and review.get("transcription_verified") is not True:
            error("$.review", "REVIEW_EVIDENCE", "结构合法不能替代原文核对")
        if review.get("eligible_for_generation") and review.get("status") != "verified":
            error("$.review", "GENERATION_STATUS", "需要人工确认的版本不具备直接生成数据资格")
    return errors


def validate_questionnaire(doc: Any, source_page_counts: dict | None = None) -> list[dict]:
    """Malformed JSON shapes are validation errors, never an unhandled traceback."""
    try:
        return _validate_questionnaire(doc, source_page_counts)
    except (TypeError, AttributeError, ValueError) as exc:
        return [{"path": "$", "code": "MALFORMED_STRUCTURE",
                 "message": "字段类型或引用结构不合法", "reason": str(exc)}]


class SurveyStore:
    def __init__(self, data_root: Path | str = DATA_ROOT):
        self.data_root = Path(data_root).resolve()
        self.catalog = read_json(self.data_root / "catalog.json")

    def _path(self, relative: Any) -> Path:
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise DataError("INVALID_DATA", "索引数据路径必须是可移植的相对路径。")
        path = (self.data_root / relative).resolve()
        if not path.is_relative_to(self.data_root) or Path(relative).is_absolute():
            raise DataError("INVALID_DATA", "索引数据路径超出数据目录。")
        return path

    def _documents(self):
        projects = self.catalog.get("projects")
        if not isinstance(projects, list):
            raise DataError("INVALID_DATA", "索引缺少项目列表。")
        for project in projects:
            if not isinstance(project, dict) or not isinstance(project.get("versions"), list):
                raise DataError("INVALID_DATA", "索引项目或版本列表不合法。")
            for version in project["versions"]:
                if not isinstance(version, dict):
                    raise DataError("INVALID_DATA", "索引版本必须是对象。")
                yield project, version, read_json(self._path(version.get("file")))

    def validate_all(self) -> dict:
        try:
            return self._validate_all()
        except DataError:
            raise
        except (TypeError, AttributeError, ValueError) as exc:
            raise DataError("INVALID_DATA", "索引字段类型或引用结构不合法。",
                            details=[{"reason": str(exc)}]) from exc

    def _validate_all(self) -> dict:
        errors = []
        catalog = self.catalog
        for field in ("schema_version", "name", "coverage", "sources", "projects"):
            if field not in catalog:
                errors.append({"path": "catalog." + field, "code": "MISSING_FIELD"})
        if catalog.get("schema_version") != 1:
            errors.append({"path": "catalog.schema_version", "code": "SCHEMA_VERSION"})
        sources = catalog.get("sources", [])
        if not isinstance(sources, list):
            raise DataError("INVALID_DATA", "索引来源必须是数组。")
        source_records = {}
        source_page_counts = {}
        for i, source in enumerate(sources):
            if not isinstance(source, dict):
                errors.append({"path": f"catalog.sources[{i}]", "code": "OBJECT_REQUIRED"})
                continue
            filename = source.get("filename")
            if not isinstance(filename, str) or Path(filename).name != filename or "/" in filename or "\\" in filename:
                errors.append({"path": f"catalog.sources[{i}]", "code": "SOURCE_FILENAME"})
                continue
            if filename in source_records:
                errors.append({"path": f"catalog.sources[{i}]", "code": "DUPLICATE_SOURCE"})
            source_records[filename] = source
            count = source.get("pdf_page_count")
            if type(count) is not int or count < 1 or source.get("volume") not in (1, 2):
                errors.append({"path": f"catalog.sources[{i}]", "code": "SOURCE_METADATA"})
            else:
                source_page_counts[filename] = count
            original = self.data_root.parent / "docs" / filename
            try:
                digest = hashlib.sha256(original.read_bytes()).hexdigest()
            except OSError:
                errors.append({"path": f"catalog.sources[{i}]", "code": "SOURCE_MISSING"})
            else:
                if digest != source.get("sha256"):
                    errors.append({"path": f"catalog.sources[{i}]", "code": "SOURCE_HASH_MISMATCH"})
        projects = catalog.get("projects", [])
        if not isinstance(projects, list):
            raise DataError("INVALID_DATA", "索引项目必须是数组。")
        project_ids = set()
        for i, project in enumerate(projects):
            if not isinstance(project, dict):
                continue  # _documents reports the malformed project.
            pid = project.get("id")
            if not isinstance(pid, str) or not ID_PATTERN.fullmatch(pid) or pid in project_ids:
                errors.append({"path": f"catalog.projects[{i}].id", "code": "PROJECT_ID"})
            if isinstance(pid, str):
                project_ids.add(pid)
            if not isinstance(project.get("name"), str) or not project.get("name"):
                errors.append({"path": f"catalog.projects[{i}].name", "code": "PROJECT_NAME"})
            aliases = project.get("aliases")
            if not isinstance(aliases, list) or any(not isinstance(a, str) or not a.strip() for a in aliases):
                errors.append({"path": f"catalog.projects[{i}].aliases", "code": "ALIASES"})
            if project.get("source_volume") not in (1, 2):
                errors.append({"path": f"catalog.projects[{i}].source_volume", "code": "SOURCE_VOLUME"})
            if "default_version" in project:
                errors.append({"path": f"catalog.projects[{i}]", "code": "DEFAULT_VERSION_NOT_ALLOWED"})
            if not project.get("versions"):
                errors.append({"path": f"catalog.projects[{i}].versions", "code": "EMPTY_VERSIONS"})
        seen_documents = set()
        seen_files = set()
        seen_item_ids = set()
        seen_versions = set()
        summaries = []
        for project, version, doc in self._documents():
            filename = version.get("file")
            prefix = str(filename)
            for issue in validate_questionnaire(doc, source_page_counts):
                errors.append({"file": prefix, **issue})
            identity = doc.get("id")
            vkey = (project.get("id"), version.get("id"))
            if identity in seen_documents or filename in seen_files or vkey in seen_versions:
                errors.append({"file": prefix, "code": "DUPLICATE_VERSION"})
            if isinstance(identity, str):
                seen_documents.add(identity)
            seen_files.add(filename)
            seen_versions.add(vkey)
            if (doc.get("project_id") != project.get("id") or doc.get("version_id") != version.get("id") or
                    doc.get("id") != version.get("questionnaire_id") or doc.get("project_name") != project.get("name")):
                errors.append({"file": prefix, "code": "INDEX_IDENTITY_MISMATCH"})
            review = doc.get("review", {})
            if not isinstance(review, dict):
                review = {}
            if (version.get("review_status") != review.get("status") or
                    version.get("eligible_for_generation") != review.get("eligible_for_generation")):
                errors.append({"file": prefix, "code": "INDEX_REVIEW_MISMATCH"})
            source = doc.get("source", {})
            if not isinstance(source, dict):
                source = {}
            registered_source = source_records.get(source.get("filename"), {})
            if (not registered_source or source.get("sha256") != registered_source.get("sha256") or
                    source.get("volume") != registered_source.get("volume") or
                    source.get("volume") != project.get("source_volume")):
                errors.append({"file": prefix, "code": "INDEX_SOURCE_MISMATCH"})
            for collection in ("items", "basic_information"):
                for item in doc.get(collection, []) if isinstance(doc.get(collection), list) else []:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        if item["id"] in seen_item_ids:
                            errors.append({"file": prefix, "code": "GLOBAL_DUPLICATE_ITEM_ID", "id": item["id"]})
                        seen_item_ids.add(item["id"])
            summaries.append(self._summary(doc))
        actual_files = {p.relative_to(self.data_root).as_posix() for p in (self.data_root / "questionnaires").glob("*.json")}
        if actual_files != seen_files:
            errors.append({"path": "catalog.projects", "code": "INDEX_FILE_SET_MISMATCH",
                           "unindexed": sorted(actual_files - seen_files), "missing": sorted(seen_files - actual_files)})
        coverage = catalog.get("coverage")
        if not isinstance(coverage, dict) or coverage != {"projects": len(projects), "versions": len(summaries)}:
            errors.append({"path": "catalog.coverage", "code": "COVERAGE_MISMATCH"})
        if errors:
            raise DataError("INVALID_DATA", "数据结构、来源或审核状态校验未通过。", details=errors)
        return {"structure_valid": True, "projects": len(projects), "versions": len(summaries),
                "review_counts": dict(Counter(s["review_status"] for s in summaries)),
                "questionnaires": summaries,
                "note": "结构校验不证明转录正确，也不表示问卷导出或宿主运行验证通过。"}

    @staticmethod
    def _summary(doc):
        review = doc.get("review", {})
        issues = doc.get("issues", [])
        return {"project_id": doc.get("project_id"), "version_id": doc.get("version_id"), "id": doc.get("id"),
                "counts": doc.get("counts"), "kinds": sorted({i.get("kind") for i in doc.get("items", []) if isinstance(i, dict) and isinstance(i.get("kind"), str)}),
                "review_status": review.get("status"), "transcription_verified": review.get("transcription_verified"),
                "eligible_for_generation": review.get("eligible_for_generation"),
                "blocking_issues": [i["id"] for i in issues if isinstance(i, dict) and i.get("blocking") and i.get("resolution") is None]}

    def list_projects(self):
        validation = self.validate_all()
        summaries = {s["id"]: s for s in validation["questionnaires"]}
        return [{**p, "versions": [{**v, "data_summary": summaries[v["questionnaire_id"]]} for v in p["versions"]]}
                for p in self.catalog["projects"]]

    def find_project(self, query: str):
        projects = self.list_projects()
        key = query.strip().casefold()
        exact_ids = [p for p in projects if p["id"].casefold() == key]
        matches = exact_ids or [p for p in projects if key in {p["name"].strip().casefold(), *(a.strip().casefold() for a in p["aliases"])}]
        candidates = [{"id": p["id"], "name": p["name"], "versions": [v["id"] for v in p["versions"]]} for p in matches]
        if not matches:
            available = [{"id": p["id"], "name": p["name"]} for p in projects]
            raise DataError("PROJECT_NOT_FOUND", "未收录该项目；请使用项目标识或已确认名称。", candidates=available)
        if len(matches) > 1:
            raise DataError("AMBIGUOUS_PROJECT", "名称对应多个项目，请选择明确标识。", candidates=candidates)
        return matches[0]

    def read_version(self, query: str, version_id: str | None = None):
        project = self.find_project(query)
        versions = project["versions"]
        if version_id is None:
            if len(versions) != 1:
                raise DataError("VERSION_REQUIRED", "该项目有多个原版，必须明确选择版本。",
                                candidates=[{"project_id": project["id"], "version_id": v["id"]} for v in versions])
            selected = versions[0]  # Sole original, never a default for an A/B project.
        else:
            selected = next((v for v in versions if v["id"] == version_id), None)
            if selected is None:
                raise DataError("VERSION_NOT_FOUND", "项目不存在指定版本。",
                                candidates=[{"project_id": project["id"], "version_id": v["id"]} for v in versions])
        return read_json(self._path(selected["file"]))


class StructuredParser(argparse.ArgumentParser):
    def error(self, message):
        raise DataError("INVALID_REQUEST", "命令参数不正确。", details=[{"reason": message}])


def parser():
    result = StructuredParser(description="课程思政问卷正式数据查询与校验（不导出、不分析）。")
    result.add_argument("--request-id", help="可选的调用方请求标识；未提供时生成本地标识")
    commands = result.add_subparsers(dest="operation", required=True, parser_class=StructuredParser)
    commands.add_parser("list", help="列出全部项目、版本与数据审核状态")
    find = commands.add_parser("find", help="按稳定标识或准确别名查找项目")
    find.add_argument("project")
    read = commands.add_parser("read", help="读取完整原版JSON，包含未解问题；不代表可生成")
    read.add_argument("project")
    read.add_argument("--version")
    commands.add_parser("validate", help="校验全部索引、数据、来源哈希及状态")
    return result


def make_result_envelope(operation, result=None, error=None, *, request_id=None,
                         started_at=None, title="课程思政问卷数据", message=None):
    """Shared local-workflow envelope; completion is specific to the operation."""
    now = datetime.now(timezone.utc).isoformat()
    if isinstance(error, DataError):
        error = {"code": error.code, "message": error.message, "retryable": False,
                 "details": error.details, "candidates": error.candidates}
    ok = error is None
    return {"schema_version": "1.0", "request_id": request_id or str(uuid.uuid4()),
            "skill_id": "kcsz-course-survey", "workflow": "teaching",
            "status": "completed" if ok else "failed", "ok": ok,
            "message": (message or "本地数据层操作完成。") if ok else error["message"],
            "summary": {"title": title, "content": {"operation": operation, "data": result}},
            "artifacts": result.get("artifacts", []) if isinstance(result, dict) else [],
            "model_trace": [], "error": error, "started_at": started_at or now, "finished_at": now}


def main(argv=None):
    started = datetime.now(timezone.utc).isoformat()
    request_id = str(uuid.uuid4())
    operation = None
    result = None
    error = None
    code = 0
    try:
        args = parser().parse_args(argv)
        request_id = args.request_id or request_id
        operation = args.operation
        store = SurveyStore()
        if operation == "list":
            result = store.list_projects()
        elif operation == "find":
            result = store.find_project(args.project)
        elif operation == "read":
            result = store.read_version(args.project, args.version)
        else:
            result = store.validate_all()
    except DataError as exc:
        code = 4 if exc.code == "INVALID_DATA" else 2
        error = {"code": exc.code, "message": exc.message, "retryable": False,
                 "details": exc.details, "candidates": exc.candidates}
    envelope = make_result_envelope(operation, result, error, request_id=request_id, started_at=started)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
