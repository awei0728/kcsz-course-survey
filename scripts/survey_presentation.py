"""Apply explicit user-approved presentation rules to immutable source data.

Preparation does not render an import file, score responses, contact a service,
or certify that a target platform enforces the resulting response rules.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from survey_data import DATA_ROOT, DataError, read_json, validate_questionnaire


RULES_PATH = DATA_ROOT / "presentation-rules.json"
RULE_IDS = {"P2-1", "P2-2", "P2-3", "P2-4", "P2-5", "P2-E-0",
            *(f"P2-E-{i}" for i in range(1, 11)), "P2.1-E-2-3", "P2.1-E-4",
            "P2.1-R-E-2-3", "P2.1-R-E-4"}


def _invalid(message: str, **details):
    raise DataError("INVALID_DATA", message, details=[details] if details else [])


def load_presentation_rules(path: Path | str = RULES_PATH) -> dict:
    """Load the recorded decisions; malformed rules never silently use defaults."""
    document = read_json(Path(path))
    if (document.get("schema_version") != 1 or
            document.get("coverage") != {"projects": 12, "source_versions": 16}):
        _invalid("派生呈现规则版本或覆盖范围不合法。")
    authority = document.get("authority")
    if (not isinstance(authority, dict) or
            authority.get("kind") != "explicit_user_instruction" or
            authority.get("engineering_completion_adds_source_version") is not False):
        _invalid("呈现规则须保留用户授权与来源版本边界。")
    versions = document.get("source_version_ids")
    if (not isinstance(versions, list) or len(versions) != 16 or
            any(not isinstance(v, str) or not v for v in versions) or
            len(set(versions)) != len(versions)):
        _invalid("呈现规则须列出16个不重复的来源版本。")
    rules = document.get("rules")
    if not isinstance(rules, list) or len(rules) != len(RULE_IDS):
        _invalid("呈现规则条目不完整。")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict):
            _invalid("每条呈现规则必须是对象。")
        rid = rule.get("id")
        if not isinstance(rid, str) or rid not in RULE_IDS or rid in seen:
            _invalid("呈现规则标识未知或重复。", rule_id=rid)
        seen.add(rid)
        for key in ("origin", "approved_text"):
            if not isinstance(rule.get(key), str) or not rule[key].strip():
                _invalid("呈现规则须保留批准原文和补充来源类别。", rule_id=rid, field=key)
        scope = rule.get("scope")
        if not isinstance(scope, dict) or not scope or any(
                key not in {"volumes", "project_ids", "all_source_versions"} for key in scope):
            _invalid("呈现规则适用范围不合法。", rule_id=rid)
        for key in ("volumes", "project_ids"):
            if key in scope and (not isinstance(scope[key], list) or not scope[key]):
                _invalid("呈现规则适用范围应为非空数组。", rule_id=rid)
        suffixes = rule.get("resolves_issue_suffixes")
        if (not isinstance(suffixes, list) or
                any(not isinstance(s, str) or not s for s in suffixes)):
            _invalid("呈现规则关联疑点应为标识数组。", rule_id=rid)
        if not isinstance(rule.get("settings"), dict):
            _invalid("呈现规则缺少实施参数。", rule_id=rid)
        if rule.get("status", "active") not in {"active", "superseded"}:
            _invalid("呈现规则状态必须区分有效与被替代历史。", rule_id=rid)
    if seen != RULE_IDS:
        _invalid("呈现规则条目不完整。")
    by_id = {r["id"]: r for r in rules}
    replacements = {"P2-E-2": "P2.1-E-2-3", "P2-E-3": "P2.1-E-2-3", "P2-E-4": "P2.1-E-4",
                    "P2.1-E-2-3": "P2.1-R-E-2-3", "P2.1-E-4": "P2.1-R-E-4"}
    for old_id, new_id in replacements.items():
        old, new = by_id[old_id], by_id[new_id]
        if (old.get("status") != "superseded" or old.get("superseded_by") != new_id or
                new.get("status") not in {"active", "superseded"} or old_id not in new.get("supersedes", [])):
            _invalid("工程伦理开放适配与历史控件规则的替代关系不完整。", rule_id=old_id)
    for rid in ("P2.1-E-2-3", "P2.1-E-4", "P2.1-R-E-2-3", "P2.1-R-E-4"):
        rule = by_id[rid]
        settings, authority = rule["settings"], rule.get("authority")
        if (not isinstance(authority, dict) or authority.get("kind") != "explicit_user_instruction" or
                settings.get("kind") != "open" or settings.get("slots") != 1 or
                settings.get("automatic_validation") is not False or
                settings.get("manual_review_required") is not True or
                settings.get("paid_feature_dependency") is not False or
                settings.get("score_responses") is not False or settings.get("analyze_responses") is not False or
                settings.get("student_instruction") != rule["approved_text"]):
            _invalid("普通文本适配须保留逐字批准说明、单字段及人工核对边界。", rule_id=rid)
    for rid in ("P2.1-R-E-2-3", "P2.1-R-E-4"):
        rule = by_id[rid]
        settings = rule["settings"]
        if (rule.get("status") != "active" or settings.get("answer_separator") != "，" or
                settings.get("reference_layout") != "paragraph_before_question" or
                settings.get("reference_code_style") != "bracketed" or
                settings.get("reference_code_template") != "【{code}】" or
                settings.get("question_stem") != "source_student_text" or
                settings.get("question_type_marker") != "[填空题]" or
                ">" in settings["student_instruction"]):
            _invalid("导入反馈修正须使用题前参考说明、括号代码及中文逗号回答，保留原短题干。", rule_id=rid)
    # Explicitly refuse unapproved scoring and selection-count additions.
    reverse = by_id["P2-2"]["settings"]
    if (reverse.get("apply_reverse_scoring") is not False or
            reverse.get("assign_reverse_values") is not False or
            reverse.get("option_order") != "source_order"):
        _invalid("本阶段必须维持原选项顺序且不实施反向计分。")
    selection = by_id["P2-E-2"]["settings"]
    if selection.get("minimum_selections") is not None or selection.get("maximum_selections") is not None:
        _invalid("用户未批准工程伦理选择数量限制。")
    for rid in ("P2-E-5", "P2-E-6", "P2-E-7"):
        settings = by_id[rid]["settings"]
        if (settings.get("assign_score_values") is not False or
                settings.get("expand_source_options") != ["A", "B", "C"] or
                not isinstance(settings.get("labels"), list) or len(settings["labels"]) != 5 or
                any(not isinstance(v, str) or not v for v in settings["labels"])):
            _invalid("工程伦理补全五级只保留已批准等级文字，不添加计分。", rule_id=rid)
    return document


def _applies(rule: dict, document: dict) -> bool:
    scope = rule["scope"]
    return bool(scope.get("all_source_versions") or
                document["source"]["volume"] in scope.get("volumes", []) or
                document["project_id"] in scope.get("project_ids", []))


def _origin(item: dict, rule_id: str):
    if rule_id not in item["provenance"]["rule_ids"]:
        item["provenance"]["rule_ids"].append(rule_id)
    item["provenance"]["origin"] = "user_approved_derivation"


def _source_item(item: dict, hidden_kinds: set[str]) -> dict:
    result = deepcopy(item)
    result.update(source_item_id=item["id"], source_option_id=None,
                  source_parent_text=None, student_response_instruction=None,
                  provenance={"origin": "source", "rule_ids": []})
    # Use only individually recorded annotations, never delete every bracket.
    for annotation in item["teacher_annotations"]:
        if annotation["kind"] in hidden_kinds:
            result["student_text"] = result["student_text"].replace(annotation["text"], "")
            _origin(result, "P2-2" if annotation["kind"] == "reverse" else "P2-3")
    return result


def _note(kind: str, text: str, source: Any, rule_id: str | None = None) -> dict:
    return {"kind": kind, "text": text, "source": deepcopy(source), "rule_id": rule_id}


def _remove_unknown(response: dict, fields: set[str]):
    response["unknowns"] = [u for u in response["unknowns"] if u["field"] not in fields]


def _expand_rating(item: dict, rule: dict) -> list[dict]:
    settings = rule["settings"]
    original_options = item["response"]["options"]
    if [option["id"] for option in original_options] != settings["expand_source_options"]:
        _invalid("工程伦理原A/B/C列表缺项或次序改变，不能应用补全规则。", item_id=item["id"])
    rows = []
    for option in original_options:
        row = deepcopy(item)
        row["id"] = item["id"] + ".part-" + option["id"]
        row["source_option_id"] = option["id"]
        row["source_parent_text"] = item["raw_text"]
        row["raw_text"] = option["label"]
        row["student_text"] = option["label"]
        row["source"] = deepcopy(option["source"])
        row["original_number"] = option["id"]
        row["kind"] = "rating"
        row["student_response_instruction"] = settings["student_instruction"]
        row["response"] = {
            "options": [
                {"id": row["id"] + f".level-{index}", "label": label,
                 "value": None, "source": None, "level_order": index,
                 "provenance": {"origin": "user_approved_supplement", "rule_id": rule["id"]}}
                for index, label in enumerate(settings["labels"], 1)
            ],
            "minimum": None, "maximum": None, "cardinality": "single", "slots": None,
            "raw_instruction": None, "unknowns": [{"field": "score_values", "reason": "用户仅批准五级文字与作答方式，未批准数字计分。"}],
            "ranking": None, "level_count": 5, "assign_score_values": False,
        }
        _origin(row, rule["id"])
        rows.append(row)
    return rows


def _adapt_text_answer(item: dict, rule: dict) -> dict:
    """One response field stores multiple information components, without controls."""
    settings = rule["settings"]
    source_options = item["response"]["options"]
    if [option["id"] for option in source_options] != settings["reference_option_ids"]:
        _invalid("工程伦理原参考列表缺项或次序改变，不能应用文本适配。", item_id=item["id"])
    item["reference_options"] = [
        {**deepcopy(option), "order": index}
        for index, option in enumerate(source_options, 1)
    ]
    item["kind"] = "open"
    item["response"] = {
        "options": [], "minimum": None, "maximum": None, "cardinality": None,
        "slots": 1, "raw_instruction": None, "ranking": None,
        "unknowns": [{"field": "required", "reason": "用户未追加平台必填设置；文本内容要求由人工核对。"}],
    }
    item["student_response_instruction"] = settings["student_instruction"]
    item["text_answer_adaptation"] = {
        "rule_id": rule["id"], "single_text_answer": True,
        "information_components": deepcopy(settings["information_components"]),
        "answer_separator": settings["answer_separator"],
        "reference_layout": settings["reference_layout"],
        "reference_code_style": settings["reference_code_style"],
        "reference_code_template": settings["reference_code_template"],
        "question_stem": settings["question_stem"],
        "question_type_marker": settings["question_type_marker"],
        "automatic_validation": settings["automatic_validation"],
        "manual_review_required": settings["manual_review_required"],
        "manual_review_checks": deepcopy(settings["manual_review_checks"]),
        "paid_feature_dependency": settings["paid_feature_dependency"],
        "score_responses": settings["score_responses"], "analyze_responses": settings["analyze_responses"],
    }
    _origin(item, rule["id"])
    return item


def _answer_units(item: dict) -> int:
    if item["kind"] == "select_rank":
        return 2  # Selection and selected-only ranking; Other is auxiliary.
    if item["kind"] == "open":
        return item["response"]["slots"] or 1
    return 1


def _prepare(document: dict, rules_document: dict) -> dict:
    errors = validate_questionnaire(document)
    if errors:
        raise DataError("INVALID_DATA", "原量表结构不完整，不能准备导出呈现。", details=errors)
    if document["id"] not in rules_document["source_version_ids"]:
        _invalid("该来源版本没有已批准的呈现规则。", questionnaire_id=document["id"])
    if document["review"]["transcription_verified"] is not True:
        _invalid("未经原文核对的数据不能因应用规则而获得生成资格。")
    history = [r for r in rules_document["rules"] if _applies(r, document) and r.get("status") == "superseded"]
    applicable = [r for r in rules_document["rules"] if _applies(r, document) and r.get("status", "active") == "active"]
    by_id = {r["id"]: r for r in applicable}
    resolved = {}
    for issue in document["issues"]:
        matching = [r["id"] for r in applicable for suffix in r["resolves_issue_suffixes"]
                    if issue["id"] == suffix or issue["id"].endswith("." + suffix)]
        if matching:
            resolved[issue["id"]] = matching
    unresolved = [issue for issue in document["issues"] if issue["blocking"] and
                  issue["resolution"] is None and issue["id"] not in resolved]
    if unresolved:
        raise DataError("PRESENTATION_BLOCKED", "存在未获批准处理的来源呈现或作答阻断。",
                        details=deepcopy(unresolved))
    hidden = set(by_id["P2-2"]["settings"]["hide_annotation_kinds"])
    if "P2-3" in by_id:
        hidden.update(by_id["P2-3"]["settings"]["hide_annotation_kinds"])
    result = {
        "schema_version": 1, "id": document["id"], "project_id": document["project_id"],
        "version_id": document["version_id"], "project_name": document["project_name"],
        "original_name": document["original_name"], "source": deepcopy(document["source"]),
        "source_questionnaire": deepcopy(document), "title": deepcopy(document["title"]),
        "instructions": [deepcopy(i) for i in document["instructions"] if i["role"] != "teacher"],
        "teacher_notes": [],
        "basic_information": [_source_item(i, hidden) for i in document["basic_information"]],
        "items": [], "groups": deepcopy(document["groups"]), "blocks": deepcopy(document["blocks"]),
        "source_mappings": [], "rule_applications": [], "rule_history": [], "response_adaptations": [],
    }
    notes = result["teacher_notes"]
    for instruction in document["instructions"]:
        if instruction["role"] == "teacher":
            notes.append(_note("source_teacher_instruction", instruction["raw_text"], instruction["source"]))
    for rule in applicable:
        result["rule_applications"].append({
            "rule_id": rule["id"], "origin": rule["origin"], "authority": deepcopy(rule.get("authority", rules_document["authority"])),
            "approved_on": rule.get("authority", {}).get("approved_on", rules_document["approved_on"]), "approved_text": rule["approved_text"],
            "questionnaire_id": document["id"],
            "resolved_source_issue_ids": [iid for iid, ids in resolved.items() if rule["id"] in ids],
            "supersedes": deepcopy(rule.get("supersedes", [])),
        })
    for rule in history:
        entry = {"rule_id": rule["id"], "origin": rule["origin"], "status": "superseded",
                 "approved_text": rule["approved_text"], "settings": deepcopy(rule["settings"]),
                 "authority": deepcopy(rule.get("authority", rules_document["authority"])),
                 "superseded_by": rule["superseded_by"], "questionnaire_id": document["id"]}
        result["rule_history"].append(entry)
        notes.append(_note("superseded_rule_history",
                           f"历史规则{rule['id']}已被{rule['superseded_by']}替代，不作为当前控件或条件强制要求。历史批准原文：{rule['approved_text']}",
                           None, rule["id"]))
    for item in document["basic_information"] + document["items"]:
        for annotation in item["teacher_annotations"]:
            note = _note("source_annotation", annotation["text"], annotation["source"])
            note.update(source_item_id=item["id"], annotation_kind=annotation["kind"])
            notes.append(note)
    for issue in document["issues"]:
        note = _note("source_issue", issue["missing_information"], issue["source"])
        note.update(issue=deepcopy(issue), resolved_by_rule_ids=resolved.get(issue["id"], []))
        notes.append(note)
    for rule in applicable:
        notes.append(_note("approved_rule", rule["approved_text"], None, rule["id"]))
    if "P2-4" in by_id:
        notes.append(_note("interpretation_warning", by_id["P2-4"]["settings"]["teacher_warning"],
                           document["title"]["source"], "P2-4"))
    for original in document["items"]:
        item = _source_item(original, hidden)
        if document["source"]["volume"] == 1:
            _remove_unknown(item["response"], {"display_order_and_score_mapping"})
            item["response"]["presentation_policy"] = {
                "option_order": "source_order", "apply_reverse_scoring": False,
                "assign_reverse_values": False, "rule_id": "P2-2",
            }
        if document["project_id"] == "core-literacy":
            for option in item["response"]["options"]:
                option["source_label"] = option["label"]
                option["label"] = None
                option["provenance"] = {"origin": "user_approved_presentation", "rule_id": "P2-1"}
            item["response"]["unknowns"].append({"field": "student_options.label", "reason": "原学生题表仅1–5数字，文字来自教师计分段；不移入学生呈现。"})
            _origin(item, "P2-1")
        if document["project_id"] == "engineering-ethics":
            suffix = item["id"].rsplit(".", 1)[1]
            if suffix in by_id["P2-E-1"]["settings"]["item_suffixes"]:
                item["response"]["cardinality"] = "single"
                _remove_unknown(item["response"], {"cardinality"})
                _origin(item, "P2-E-1")
            for rule_id in ("P2.1-R-E-2-3", "P2.1-R-E-4"):
                rule = by_id[rule_id]
                if suffix == rule["settings"]["item_suffix"]:
                    item = _adapt_text_answer(item, rule)
                    result["response_adaptations"].append({
                        "source_item_id": item["source_item_id"], "presentation_item_id": item["id"],
                        **deepcopy(item["text_answer_adaptation"]), "target_kind": "open", "input_fields": 1,
                        "reference_option_ids": [option["id"] for option in item["reference_options"]],
                    })
                    notes.append(_note("text_answer_adaptation",
                                       "采用用户批准的导入反馈呈现修正：原列表全文和顺序不变，参考代码展示为【A】等形式，原维度标题、完整参考列表及作答要求置于题前独立说明段落；原短题干行末紧接[填空题]，每题仍为一个普通文本框。回答代码之间用中文逗号分隔，不预填或推荐排列。重复、漏项、未知代码、并列及其他具体内容说明缺失须按本题说明人工核对，不依赖排序控件、选项引用、条件显示、条件必填、计算公式或付费校验，不声称与原控件同等校验；本程序不评分、不分析。候选排版尚待实际导入验证。",
                                       item["source"], rule_id))
            expansion = next((by_id[rid] for rid in ("P2-E-5", "P2-E-6", "P2-E-7")
                              if suffix == by_id[rid]["settings"]["item_suffix"]), None)
            if expansion:
                result["items"].extend(_expand_rating(item, expansion))
                continue
            if suffix in {"q008", "q011"}:
                marker = "[量表题]"
                if marker in item["student_text"]:
                    item["student_text"] = item["student_text"].replace(marker, "")
                    note = _note("source_type_marker", marker, item["source"])
                    note["source_item_id"] = item["id"]
                    notes.append(note)
                    item["provenance"]["text_transforms"] = [{
                        "kind": "source_type_metadata_separation", "text": marker,
                        "authority": "source_explicit_question_type_marker",
                        "source": deepcopy(item["source"]),
                        "note": "将原题型元标记与学生内容分开，不改题干措辞、否定或端点；导出层独立添加目标格式语法。",
                    }]
            if suffix == "q013":
                # Three requested sentences are not three drawn text fields.
                item["response"]["presentation_text_areas"] = 1
                item["response"]["enforce_sentence_count"] = False
        result["items"].append(item)
    for index, item in enumerate(result["items"], 1):
        item["order"] = index
    all_presented = result["basic_information"] + result["items"]
    for original in document["basic_information"] + document["items"]:
        descendants = [i for i in all_presented if i["source_item_id"] == original["id"]]
        result["source_mappings"].append({
            "source_item_id": original["id"], "presentation_item_ids": [i["id"] for i in descendants],
            "source_option_mappings": [{"source_option_id": i["source_option_id"], "presentation_item_id": i["id"]}
                                       for i in descendants if i["source_option_id"] is not None],
            "text_information_mapping": [
                {"presentation_item_id": i["id"], "input_field_count": 1,
                 "information_components": deepcopy(i["text_answer_adaptation"]["information_components"]),
                 "rule_id": i["text_answer_adaptation"]["rule_id"]}
                for i in descendants if "text_answer_adaptation" in i
            ],
        })
    mapping = {m["source_item_id"]: m["presentation_item_ids"] for m in result["source_mappings"]}
    for block in result["blocks"]:
        block["source_block_id"] = block["id"]
        original_ids = block["item_ids"]
        block["item_ids"] = [pid for oid in original_ids for pid in mapping[oid]]
        expanded = [i for i in result["items"] if i["id"] in block["item_ids"] and i["source_option_id"] is not None]
        if expanded:
            block["kind"] = "matrix"
            block["note"] = "用户批准作答规则补全：原A/B/C材料分别作答；原题干及原列表保存在source_questionnaire。"
            block["provenance"] = {"origin": "user_approved_supplement", "rule_ids": expanded[0]["provenance"]["rule_ids"][:]}
    if "P2-E-0" in by_id:
        result["title"]["student_text"] = document["title"]["student_text"] + "（" + by_id["P2-E-0"]["settings"]["title_suffix"] + "）"
        result["title"]["provenance"] = {"origin": "user_approved_supplement", "rule_id": "P2-E-0"}
    measurement = [i for i in result["items"] if i["role"] == "measurement"]
    background = [i for i in result["items"] if i["role"] == "background"]
    result["counts"] = {
        "source_counts": deepcopy(document["counts"]),
        "source_question_blocks": document["counts"]["original_question_blocks"],
        "source_item_records": len(document["items"]),
        "basic_information": len(result["basic_information"]),
        "background_items": len(background), "presentation_item_records": len(result["items"]),
        "presentation_measurement_records": len(measurement),
        "independent_answer_items": sum(_answer_units(i) for i in all_presented),
        "independent_measurement_answer_items": sum(_answer_units(i) for i in measurement),
        "independent_background_answer_items": sum(_answer_units(i) for i in background),
        "independent_basic_information_answer_items": sum(_answer_units(i) for i in result["basic_information"]),
        "conditional_auxiliary_fields": sum(len(i["response"].get("auxiliary_fields", [])) for i in all_presented),
        "open_answer_slots": sum(_answer_units(i) for i in all_presented if i["kind"] == "open"),
        "export_question_count": None,
        "counting_note": "独立作答项按实际输入字段统计，含基本信息及背景；每个评分行/单选和每个原开放槽为1。工程q003一个文本框同时承载选择、重要性顺序及其他说明，q004另一文本框承载五项顺序；信息组成不是独立字段，条件辅助字段为0。工程三句话开放题为一个文本框，不追加句数强制。来源题干块、存储记录、输入字段及导出题数不能互换；导出题量由格式层给出。",
    }
    result["presentation_review"] = {
        "status": "approved_rules_applied", "source_review_status": document["review"]["status"],
        "source_transcription_verified": document["review"]["transcription_verified"],
        "resolved_source_blocking_issue_ids": [i["id"] for i in document["issues"] if i["blocking"] and i["id"] in resolved],
        "unresolved_source_blocking_issue_ids": [], "eligible_for_export_assessment": True,
        "source_rules_overridden": document["project_id"] == "engineering-ethics",
        "actual_import_validation": "not_performed", "host_runtime_validation": "not_performed",
        "note": rules_document["validation_boundary"],
    }
    return result


def prepare_questionnaire(document: dict, rules_path: Path | str | None = None) -> dict:
    """Return a fresh source-plus-presentation object, without changing input.

    The caller must separately assess its target format, enforce the approved
    response rules, and validate actual import; eligibility here is not export
    or integration success. Engineering supplements remain one source version.
    """
    try:
        return _prepare(document, load_presentation_rules(rules_path or RULES_PATH))
    except DataError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise DataError("INVALID_DATA", "呈现规则或原始量表结构不完整。",
                        details=[{"reason": str(exc)}]) from exc
