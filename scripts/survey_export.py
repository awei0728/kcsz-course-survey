"""Local WJX manual-text candidates, with explicit evidence and format limits.

No API/AIKit syntax, remote calls, scores, or host integration. The official
image examples could not be inspected in this run: matrix/type-tag templates
are deliberately provisional, and every artifact is pending import review.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
import uuid

from survey_data import (DataError, SKILL_ROOT, StructuredParser, SurveyStore,
                         make_result_envelope)
from survey_presentation import RULES_PATH, prepare_questionnaire


FORMAT_PROFILE = {
    "id": "wjx-manual-text-candidate-v1",
    "channel": "从文本创建问卷（手工导入）",
    "checked_on": "2026-10-04",
    "official_sources": [
        "https://www.wjx.cn/help/help.aspx?helpid=138",
        "https://www.wjx.cn/help/help.aspx?helpid=870",
        "https://www.wjx.cn/help/help.aspx?helpid=674",
    ],
    "syntax_evidence": "official_images_pending_review",
    "official_image_examples_verified": False,
    "actual_import_verified": False,
    "template_status": "provisional",
    "template": {
        "question_header": "连续数字. 原题文字[题型]，空行分题",
        "matrix": "[矩阵题]；首行按原顺序空格分隔列标签，随后每行一个原题项",
        "choice": "[单选题]；每行一个原选项",
        "open": "[填空题]；原开放槽位展开为单独题，逐槽映射",
        "paragraph": "[段落说明]；指导语独立段落，不算作答题",
    },
    "note": "138正文可读取，但图片403且浏览器绑定超时。上述模板是待核对候选，不声称图片语法核实或问卷星导入通过。没有采用AIKit/API的行:、列:、1~10或JSONL语法。",
}

_TYPE_TAG = re.compile(r"[\[【（(〖].{0,24}(?:题|段落说明)[\]】）)〗]")


def _parameter(name, value, *, required=False):
    if value is None and not required:
        return None
    if (not isinstance(value, str) or not value.strip() or
            any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in value) or
            _TYPE_TAG.search(value)):
        raise DataError("INVALID_REQUEST", "参数须为非空单行文字，不能包含控制符或导入题型标记。",
                        details=[{"parameter": name}])
    return value.strip()


def _line(value, field):
    """Source text is never silently escaped, rewritten, or split into questions."""
    if (not isinstance(value, str) or not value.strip() or
            any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in value)):
        raise DataError("INVALID_DATA", "学生呈现文字缺失或包含未处理的排版控制符。",
                        details=[{"field": field}])
    return value


def _format_limits(prepared):
    limits = []
    for item in prepared["basic_information"] + prepared["items"]:
        kind = item["kind"]
        if kind == "select_rank":
            limits.append({
                "code": "SELECTED_ONLY_RANKING_AND_CONDITIONAL_OTHER",
                "source_item_id": item["source_item_id"], "presentation_item_id": item["id"],
                "rule_ids": ["P2-E-2", "P2-E-3", "P2-E-8"], "source": item["source"],
                "required": deepcopy(item["response"]),
                "reason": "未证实手工文本可保留只排选中项、所有选中项都排序、不并列、其他选中必填且参与排序。普通多选或全排均不等价。",
                "platform_support": "partial_ranking_documented; conditional_other_not_verified",
                "free_plan": "single_question_partial_ranking_not_verified; option_reference_unavailable",
                "manual_text_import": "not_confirmed",
                "alternatives": [
                    "导入后人工设置单题部分排序、其他填写与条件必填，并逐项验证；不算纯文本完整导入。",
                    "后台建立多选＋付费选项引用排序，人工设置其他填写；不追加选择数量限制，不算纯文本完整导入。",
                ],
                "official_sources": FORMAT_PROFILE["official_sources"],
            })
        elif kind == "ranking":
            limits.append({
                "code": "FULL_RANKING_SETTINGS_NOT_CONFIRMED", "source_item_id": item["source_item_id"],
                "presentation_item_id": item["id"], "rule_ids": ["P2-E-4", "P2-E-8"],
                "source": item["source"], "required": deepcopy(item["response"]["ranking"]),
                "reason": "未核实文本能保留全部五项排序、重要性从高到低及不并列设置；仅写题干要求不能证明平台强制实现。",
                "manual_text_import": "not_confirmed",
                "alternatives": ["后台人工确认所有五项必须排序且不允许并列，再检查答题页面；不算纯文本完整导入。"],
            })
        elif kind not in {"rating", "choice", "open"}:
            limits.append({"code": "UNSUPPORTED_RESPONSE_KIND", "kind": kind,
                           "source_item_id": item["source_item_id"], "source": item["source"]})
    return limits


def _option_label(option):
    label, value = option["label"], option["value"]
    if value is None:
        return _line(label, "response.options.label")
    value_text = str(value)
    # A visible response code is not a WJX score-assignment directive.
    return value_text if label is None else value_text + "（" + _line(label, "response.options.label") + "）"


def _group_title(item, prepared):
    groups = {g["id"]: g for g in prepared["groups"]}
    current = item["group_id"]
    names, seen = [], set()
    while current:
        if current in seen or current not in groups:
            raise DataError("INVALID_DATA", "呈现分组引用无效。", details=[{"group_id": current}])
        seen.add(current)
        group = groups[current]
        names.insert(0, group["raw_name"])
        current = group["parent_id"]
    return " / ".join(names) if names else prepared["project_name"]


def _render_records(prepared, source_item_ids):
    """Select a clearly labelled import-test subset without changing source data."""
    records = prepared["basic_information"] + prepared["items"]
    if source_item_ids is None:
        return records, {"full_questionnaire": True, "source_item_ids": None}, deepcopy(prepared["counts"])
    if not isinstance(source_item_ids, (list, tuple)) or not source_item_ids:
        raise DataError("INVALID_REQUEST", "导入测试必须指定非空来源题项ID列表。")
    ids = [_parameter("source_item_id", value, required=True) for value in source_item_ids]
    if len(set(ids)) != len(ids):
        raise DataError("INVALID_REQUEST", "导入测试来源题项ID不能重复。")
    known = {item["source_item_id"] for item in records}
    unknown = [value for value in ids if value not in known]
    if unknown:
        raise DataError("INVALID_REQUEST", "导入测试包含不存在的来源题项ID。",
                        details=[{"unknown_source_item_ids": unknown}])
    selected = [item for item in records if item["source_item_id"] in ids]
    basic_ids = {item["id"] for item in prepared["basic_information"]}
    fields = lambda item: (item["response"]["slots"] or 1) if item["kind"] == "open" else 1
    basic = [item for item in selected if item["id"] in basic_ids]
    background = [item for item in selected if item["role"] == "background"]
    measurement = [item for item in selected if item not in basic and item not in background]
    counts = {**deepcopy(prepared["counts"]),
              "basic_information": len(basic), "background_items": len(background),
              "presentation_item_records": len(selected), "presentation_measurement_records": len(measurement),
              "independent_answer_items": sum(map(fields, selected)),
              "independent_measurement_answer_items": sum(map(fields, measurement)),
              "independent_background_answer_items": sum(map(fields, background)),
              "independent_basic_information_answer_items": sum(map(fields, basic)),
              "conditional_auxiliary_fields": 0,
              "open_answer_slots": sum(fields(item) for item in selected if item["kind"] == "open"),
              "counting_note": "导入测试子集仅统计所选题项的呈现记录和输入字段；source_counts及source_question_blocks/source_item_records仍是整份来源的历史统计。"}
    return selected, {"full_questionnaire": False, "source_item_ids": ids,
                      "purpose": "import_test_subset", "order": "source_order"}, counts


def render_questionnaire(prepared, course=None, scenario=None, source_item_ids=None):
    """Render a complete ordinary candidate or fail before producing any text.

    The return value is local serialization evidence, never WJX acceptance.
    Unadapted ranking and unsupported response rules remain format-blocked.
    """
    course = _parameter("course", course)
    scenario = _parameter("scenario", scenario)
    try:
        canonical = prepare_questionnaire(prepared["source_questionnaire"])
        if prepared != canonical:
            raise DataError("INVALID_DATA", "派生数据与正式来源及已批准规则不一致；请重新准备后渲染。",
                            details=[{"changed_fields": [key for key in sorted(set(prepared) | set(canonical))
                                                         if prepared.get(key) != canonical.get(key)]}])
        if (prepared["presentation_review"]["eligible_for_export_assessment"] is not True or
                prepared["presentation_review"]["unresolved_source_blocking_issue_ids"]):
            raise DataError("PRESENTATION_BLOCKED", "仍有未解决的呈现规则阻断。")
        limits = _format_limits(prepared)
        if limits:
            raise DataError("TARGET_FORMAT_LIMIT", "目标手工文本格式未证实能完整表达该版本的批准作答规则。",
                            details=[{"questionnaire_id": prepared["id"], "counts": prepared["counts"],
                                      "limits": limits, "format_profile": FORMAT_PROFILE}])
        records, selection, presentation_counts = _render_records(prepared, source_item_ids)
        source_title = prepared["title"]["student_text"]
        if prepared["source"]["volume"] == 1:
            title = prepared["project_name"] + "问卷"
            if prepared["version_id"] in {"A", "B"}:
                title += "（" + prepared["version_id"] + "卷）"
        else:
            title = source_title
        title = _line(title, "title")
        context = [v for v in (course, scenario) if v]
        if context:
            title += " — " + " · ".join(context)
        if not selection["full_questionnaire"]:
            title += " — 题目导入测试"
        paragraphs, mapping, number = [], [], 0
        response_instructions = []
        # A subset contains only the selected questions and their own references.
        for instruction in prepared["instructions"] if selection["full_questionnaire"] else []:
            student = instruction["student_text"]
            if student:
                paragraph = _line(student, "instructions.student_text") + "[段落说明]"
                if instruction["role"] == "response":
                    response_instructions.append(paragraph)
                else:
                    paragraphs.append(paragraph)

        def add_mapping(item, qn, row=None, sub=None, reference_paragraph_number=None):
            entry = {"source_item_id": item["source_item_id"], "presentation_item_id": item["id"],
                            "source_option_id": item["source_option_id"], "export_question_number": qn,
                            "matrix_row_number": row, "subquestion_number": sub, "kind": item["kind"],
                            "role": item["role"], "group_id": item["group_id"], "source": deepcopy(item["source"])}
            adaptation = item.get("text_answer_adaptation")
            if adaptation:
                entry.update(text_answer_adaptation=deepcopy(adaptation), combined_into_single_text_answer=True,
                             information_components=deepcopy(adaptation["information_components"]))
                if reference_paragraph_number is not None:
                    entry["reference_paragraph_number"] = reference_paragraph_number
            mapping.append(entry)

        index = 0
        while index < len(records):
            item = records[index]
            text = _line(item["student_text"], item["id"])
            kind, response = item["kind"], item["response"]
            if kind == "rating":
                # Source rating instructions follow preliminary open/yes-no
                # questions and demographic blanks; they do not govern them.
                if response_instructions:
                    paragraphs.extend(response_instructions)
                    response_instructions.clear()
                signature = [(o["label"], o["value"]) for o in response["options"]]
                if not signature:
                    raise DataError("INVALID_DATA", "评分题缺少完整响应等级。", details=[{"item_id": item["id"]}])
                rows = [item]
                while index + len(rows) < len(records):
                    next_item = records[index + len(rows)]
                    if (next_item["kind"] != "rating" or next_item["group_id"] != item["group_id"] or
                            next_item.get("source_parent_text") != item.get("source_parent_text") or
                            [(o["label"], o["value"]) for o in next_item["response"]["options"]] != signature):
                        break
                    rows.append(next_item)
                number += 1
                heading = _group_title(item, prepared)
                if item.get("source_parent_text"):
                    heading += "：" + _line(item["source_parent_text"], "source_parent_text")
                columns = [_option_label(o) for o in response["options"]]
                if any(" " in column for column in columns):
                    raise DataError("TARGET_FORMAT_LIMIT", "矩阵列标签含空格，候选模板不能无损分隔。",
                                    details=[{"source_item_id": item["source_item_id"]}])
                paragraph = [f"{number}. {heading}[矩阵题]", " ".join(columns)]
                for row_number, row in enumerate(rows, 1):
                    paragraph.append(_line(row["student_text"], row["id"]))
                    add_mapping(row, number, row=row_number)
                paragraphs.append("\n".join(paragraph))
                index += len(rows)
                continue
            if kind == "open":
                references = item.get("reference_options", [])
                reference_paragraph_number = None
                if references:
                    # References are one complete non-answer paragraph. The fill-in
                    # header below contains only the original short question stem.
                    reference_text = "；".join("【" + _line(o["id"], "reference_options.id") + "】" +
                                              _line(o["label"], "reference_options.label") for o in references)
                    reference_paragraph = _group_title(item, prepared) + "。参考项目：" + reference_text + "。"
                    if item.get("student_response_instruction"):
                        reference_paragraph += " 作答说明：" + _line(item["student_response_instruction"], "student_response_instruction")
                    reference_paragraph_number = len(paragraphs) - number + 1
                    paragraphs.append(reference_paragraph + "[段落说明]")
                elif item.get("student_response_instruction"):
                    text += " 作答说明：" + _line(item["student_response_instruction"], "student_response_instruction")
                slots = response["slots"] or 1
                for slot in range(1, slots + 1):
                    number += 1
                    suffix = "" if slots == 1 else f"（{slot}）____"
                    paragraphs.append(f"{number}. {text}{suffix}[填空题]")
                    add_mapping(item, number, sub=slot if slots > 1 else None,
                                reference_paragraph_number=reference_paragraph_number)
            elif kind == "choice":
                if response["cardinality"] != "single" or len(response["options"]) < 2:
                    raise DataError("INVALID_DATA", "该选择题未确认单选或缺少原选项。", details=[{"item_id": item["id"]}])
                number += 1
                # For choice options preserve original labels; no invented score codes.
                paragraphs.append("\n".join([f"{number}. {text}[单选题]",
                                            *[_line(o["label"], "choice.option") for o in response["options"]]]))
                add_mapping(item, number)
            index += 1
        if len(mapping) != presentation_counts["independent_answer_items"]:
            raise DataError("INVALID_DATA", "导出映射数量与独立作答项不一致。")
        counts = {**presentation_counts, "export_question_count": number,
                  "export_paragraph_count": len(paragraphs) - number,
                  "source_mapping_count": len(mapping)}
        text = title + "\n\n" + "\n\n".join(paragraphs) + "\n"
        if "反向检测题" in text or "盲目爱国主义" in text:
            raise DataError("INVALID_DATA", "学生文本泄露了教师标记。")
        verification = {"presentation_rules": "applied", "text_generation": "rendered",
                                 "syntax_evidence": FORMAT_PROFILE["syntax_evidence"],
                                 "wjx_import": "pending_user_validation", "workbuddy": "not_verified",
                                 "teach_claw": "not_verified", "reverse_scoring_applied": False,
                                 "platform_enforcement_verified": False}
        if prepared.get("response_adaptations"):
            verification.update(manual_review_required=True, automatic_text_answer_validation=False,
                                basic_question_type_adaptation="applied", free_account_import="not_verified")
        return {"text": text, "title": title, "mapping": mapping, "counts": counts, "selection": selection,
                "format_profile": deepcopy(FORMAT_PROFILE), "verification": verification}
    except DataError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise DataError("INVALID_DATA", "派生呈现数据缺字段或结构不完整。",
                        details=[{"reason": str(exc)}]) from exc


def _teacher_document(prepared, rendered):
    source = prepared["source_questionnaire"]
    parts = ["# 教师说明与来源（不导入学生问卷）", "",
             "文本文件是待用户导入核对的候选。官方图片语法尚待核查；未进行问卷星实际导入、平台设置强制性、WorkBuddy或teach_claw运行验证。",
             "本程序没有计分、反向赋值、NPS分析；显示的数字只是原响应等级。不要以平台默认分值替代原教师元数据。", "",
             "## 来源", "", json.dumps(prepared["source"], ensure_ascii=False, indent=2), "",
             "原始标题：" + str(source["title"]["raw_text"]), "呈现标题：" + rendered["title"], "",
             "## 数量与验证边界", "", json.dumps(rendered["counts"], ensure_ascii=False, indent=2), "",
             "渲染范围：" + json.dumps(rendered["selection"], ensure_ascii=False), "",
             "## 本次有效题型适配", ""]
    if prepared.get("response_adaptations"):
        parts += ["工程伦理q003、q004属于基础题型适配，各仅一个普通文本框。原A–G/A–E全文是题面参考文字，不是可点击选项。",
                  "选择、重要性顺序及G说明由同一文本回答表达；不依赖排序控件、选项引用、条件显示、条件必填、计算公式或付费校验。",
                  "重复、漏项、未知代码及G说明缺失，需要教师人工核对。不宣称与原排序控件具有相同校验能力；平台不会由本程序自动强制检查排序合法性。",
                  "不执行评分，不新增答卷分析。基础题型适配完成不等于免费账号实际导入通过。",
                  "本次呈现修正：参考项目代码展示为【A】等形式，原维度和参考全文放在填空前的完整说明段落；短题干独占填空题行。",
                  "当前排序回答使用中文逗号分隔；‘其他’具体说明在同一文本回答末尾补充。旧大于号分隔说明仅保留为历史，不再生效。",
                  "用户已反馈旧第3、4题实际被误识别为单选、参考及说明被拆成选项；本次候选仍待实际导入复核。单行矩阵不兼容尚未证实，本轮不据此改变其他题型。",
                  json.dumps(prepared["response_adaptations"], ensure_ascii=False, indent=2), "",
                  "## 已被本次适配替代的历史规则（不作为有效控件依赖）", "",
                  json.dumps(prepared.get("rule_history", []), ensure_ascii=False, indent=2), ""]
    else:
        parts += ["该来源版本本轮没有新增题型适配。", ""]
    parts += ["## 原文说明、疑点与批准有效规则", ""]
    for note in prepared["teacher_notes"]:
        parts += [f"- 类型：{note['kind']}；规则：{note.get('rule_id') or '来源原文'}", note["text"],
                  "定位：" + json.dumps(note["source"], ensure_ascii=False)]
        if note.get("issue"):
            parts.append("来源历史疑点保留；本次处理规则：" +
                         ("、".join(note.get("resolved_by_rule_ids", [])) or "无补全规则；保留原文提示/元数据未知。"))
            parts.append(json.dumps(note["issue"], ensure_ascii=False, indent=2))
    parts += ["", "## 原文明示计分元数据（本阶段不执行）", "",
              json.dumps(source["scoring"], ensure_ascii=False, indent=2), "",
              "## 导入后逐题核对", "",
              "核对矩阵识别、每个原分组、题序和完整列数；第二辑只能是1–10，中间档无补造文字；基本字段为开放填空。",
              "学习自我效能感的两个开放题各保留三个槽，候选文本逐槽展开；核对原指导语被识别为段落而非题目/选项。",
              "未确认必填、选项随机、强制排序等平台设置时，不得把默认设置称为原卷规则或程序已强制实现。", "",
              "## 手工导入格式证据", "", json.dumps(rendered["format_profile"], ensure_ascii=False, indent=2)]
    return "\n".join(parts) + "\n"


def _safe_name(value):
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).replace("..", "-").strip(" .-")
    return clean[:48].rstrip(" .-") or "survey"


def resolve_output_directory(output_dir):
    """Shared output-path checks for a single export or a whole delivery."""
    if not isinstance(output_dir, (str, Path)) or not str(output_dir).strip():
        raise DataError("INVALID_REQUEST", "必须提供输出目录。", details=[{"parameter": "output_dir"}])
    _parameter("output_dir", str(output_dir), required=True)
    try:
        root = Path(output_dir).expanduser().resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        raise DataError("INVALID_REQUEST", "输出目录不能解析。",
                        details=[{"parameter": "output_dir", "reason": str(exc)}]) from exc
    for protected in (SKILL_ROOT / "data", SKILL_ROOT / "docs", SKILL_ROOT / "scripts", SKILL_ROOT / "tests"):
        if root == protected.resolve() or root.is_relative_to(protected.resolve()):
            raise DataError("INVALID_REQUEST", "输出目录不能位于本Skill的来源、正式数据、代码或报告目录。",
                            details=[{"parameter": "output_dir"}])
    return root


def export_questionnaire(project, version=None, course=None, scenario=None,
                         output_dir=None, request_id=None, store=None, source_item_ids=None):
    """Prepare/assess completely before committing a unique three-file bundle."""
    project = _parameter("project", project, required=True)
    version = _parameter("version", version)
    course, scenario = _parameter("course", course), _parameter("scenario", scenario)
    request_id = _parameter("request_id", request_id) or str(uuid.uuid4())
    root = resolve_output_directory(SKILL_ROOT / "output" if output_dir is None else output_dir)
    store = store or SurveyStore()
    original = store.read_version(project, version)
    prepared = prepare_questionnaire(original)
    rendered = render_questionnaire(prepared, course, scenario, source_item_ids=source_item_ids)
    token = uuid.uuid4().hex
    final = root / (prepared["id"] + "-" + _safe_name(rendered["title"]) + "-" + token[:12])
    staging = root / (".partial-" + token)
    filenames = ("survey.pending-import.txt", "teacher-notes.md", "manifest.json")
    manifest = {"schema_version": 1, "request_id": request_id, "questionnaire_id": prepared["id"],
                "project_id": prepared["project_id"], "version_id": prepared["version_id"],
                "title": rendered["title"], "source": prepared["source"],
                "source_title": original["title"], "source_review": original["review"],
                "presentation_review": prepared["presentation_review"], "rule_applications": prepared["rule_applications"],
                "rule_history": prepared.get("rule_history", []), "response_adaptations": prepared.get("response_adaptations", []),
                "presentation_rules_sha256": hashlib.sha256(RULES_PATH.read_bytes()).hexdigest(),
                "format_profile": rendered["format_profile"], "counts": rendered["counts"],
                "selection": rendered["selection"],
                "mapping": rendered["mapping"], "source_groups": original["groups"], "source_blocks": original["blocks"],
                "source_mappings": prepared["source_mappings"], "verification": rendered["verification"],
                "files": [
                    {"name": filenames[0], "role": "primary", "validation": "pending_user_import",
                     "sha256": hashlib.sha256(rendered["text"].encode("utf-8")).hexdigest()},
                    {"name": filenames[1], "role": "teacher"}, {"name": filenames[2], "role": "mapping"},
                ]}
    staging_created = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        staging.mkdir()  # Exclusive, so no existing user bundle is ever touched.
        staging_created = True
        (staging / filenames[0]).write_text(rendered["text"], encoding="utf-8", newline="\n")
        (staging / filenames[1]).write_text(_teacher_document(prepared, rendered), encoding="utf-8", newline="\n")
        (staging / filenames[2]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                          encoding="utf-8", newline="\n")
        if final.exists():
            raise FileExistsError("The destination bundle already exists; refusing to replace it.")
        staging.rename(final)  # Commit only a whole bundle; no individual final TXT before this point.
    except (OSError, ValueError) as exc:
        cleanup_error = None
        if staging_created and staging.is_dir():
            try:
                for name in filenames:
                    (staging / name).unlink(missing_ok=True)
                staging.rmdir()
            except OSError as cleanup:
                cleanup_error = str(cleanup)
        raise DataError("OUTPUT_WRITE_FAILED", "输出文件事务失败；没有交付完整正式导出包。",
                        details=[{"reason": str(exc), "incomplete_directory": str(staging) if cleanup_error else None,
                                  "cleanup_error": cleanup_error}]) from exc
    artifacts = [{"name": name, "path": str(final / name), "content_type": mime, "role": role,
                  "validation": "pending_user_import" if role == "primary" else "local_metadata"}
                 for name, mime, role in zip(filenames, ("text/plain; charset=utf-8", "text/markdown; charset=utf-8", "application/json"),
                                             ("primary", "teacher", "mapping"))]
    return {"questionnaire_id": prepared["id"], "project_id": prepared["project_id"], "version_id": prepared["version_id"],
            "title": rendered["title"], "request_id": request_id, "counts": rendered["counts"],
            "selection": rendered["selection"],
            "verification": {**rendered["verification"], "text_generation": "generated"},
            "response_adaptations": prepared.get("response_adaptations", []),
            "format_profile": rendered["format_profile"], "artifacts": artifacts, "output_directory": str(final)}


def parser():
    result = StructuredParser(description="生成问卷星手工文本候选；实际导入待用户验证。")
    result.add_argument("--project", required=True, help="项目ID、名称或已确认别名")
    result.add_argument("--version", help="A/B项目必选；单一来源版为original")
    result.add_argument("--course", help="仅加入标题的课程名称")
    result.add_argument("--scenario", help="仅加入标题的前测/后测等场景")
    result.add_argument("--output-dir", help="保存独立候选、教师说明与映射的目录；缺省为实际Skill根目录/output")
    result.add_argument("--request-id", help="可选调用方请求标识")
    result.add_argument("--source-item-id", action="append", help="仅用于导入测试子集，可重复指定来源题项ID；不指定时整卷导出")
    return result


def main(argv=None):
    started, request_id = datetime.now(timezone.utc).isoformat(), str(uuid.uuid4())
    result, error, exit_code = None, None, 0
    try:
        args = parser().parse_args(argv)
        request_id = _parameter("request_id", args.request_id) or request_id
        result = export_questionnaire(args.project, args.version, args.course, args.scenario,
                                      args.output_dir, request_id, source_item_ids=args.source_item_id)
    except DataError as exc:
        error = exc
        exit_code = (5 if exc.code == "OUTPUT_WRITE_FAILED" else 4 if exc.code in {
            "INVALID_DATA", "PRESENTATION_BLOCKED", "TARGET_FORMAT_LIMIT"} else 2)
    envelope = make_result_envelope("export", result, error, request_id=request_id, started_at=started,
                                    title="课程思政问卷文本候选",
                                    message="候选文本、教师说明与映射已生成；官方图片语法及问卷星实际导入待核对。")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
