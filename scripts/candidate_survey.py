"""Compose the reviewed 18-goal candidate banks into local import files.

Selection, teacher approval and platform import are separate states. Review
exports contain the requested whole banks or their explicitly sized subset; a survey export fails as a whole
when any selected item is not cleared. No responses are scored here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
import uuid

from candidate_data import CandidateStore
from survey_data import DataError, SKILL_ROOT, StructuredParser, make_result_envelope
from survey_export import _parameter, _safe_name, resolve_output_directory


OPTIONS = ("完全不同意", "比较不同意", "不确定", "比较同意", "完全同意")
FORMAT_PROFILES = {
    "wjx": {
        "id": "wjx-candidate-single-choice-v1",
        "extension": ".txt",
        "content_type": "text/plain; charset=utf-8",
        "channel": "从文本创建问卷",
        "official_sources": ["https://www.wjx.cn/help/help.aspx?helpid=138"],
        "syntax_evidence": "existing_local_single_choice_template",
        "actual_import_verified": False,
    },
    "chaoxing": {
        "id": "chaoxing-assessment-xls-v1",
        "extension": ".xls",
        "content_type": "application/vnd.ms-excel",
        "channel": "学习通课程题库Excel导入",
        "question_type": "测评题",
        "correct_answers": None,
        "actual_import_verified": False,
    },
}
_TYPE_TAG = re.compile(r"[\[【（(〖].{0,24}(?:题|段落说明)[\]】）)〗]")


def _student_line(value, field):
    if (not isinstance(value, str) or not value.strip()
            or any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in value)
            or _TYPE_TAG.search(value) or re.search(r"<[^>]+>", value)):
        raise DataError("INVALID_DATA", "题文不能缺失或包含控制符、导入标记及HTML。",
                        details=[{"field": field}])
    return value


def render_wjx(items, title):
    """One answerable item per candidate, in source order, with no score key."""
    title = _student_line(title, "title")
    blocks = []
    for number, item in enumerate(items, 1):
        text = _student_line(item["item_text_zh"], "item_text_zh")
        options = [_student_line(option, "option") for option in item["options"]]
        if len(options) != 5 or tuple(options) != OPTIONS:
            raise DataError("INVALID_DATA", "候选题必须保留统一五级同意选项。")
        blocks.append("\n".join([f"{number}. {text}[单选题]", *options]))
    if not blocks:
        raise DataError("INVALID_DATA", "选中的候选题库为空。")
    return (title + "\n\n" + "\n\n".join(blocks) + "\n").encode("utf-8")


def _release_blockers(candidates):
    blockers = []
    for candidate in candidates:
        reasons = []
        if candidate.get("release_eligible") != "是":
            reasons.append("release_not_approved")
        risk = candidate.get("risk_level")
        if risk == "P0":
            reasons.append("P0")
        elif risk not in {"P1", "P2"}:
            reasons.append("risk_not_classified")
        if any(word in candidate.get("activation_status", "") for word in ("暂缓", "暂停")):
            reasons.append("activation_blocked")
        if reasons:
            blockers.append({"candidate_id": candidate["candidate_id"], "reasons": reasons})
    return blockers


def _teacher_notes(selection, candidates, blockers, output_format, purpose):
    names = "、".join(project["name"] for project in selection["projects"])
    multiple = len(selection["projects"]) > 1
    policy = selection["selection"]
    requested_count = policy.get("question_count_requested")
    if requested_count is None:
        rule = ("多目标默认使用各目标全部核心候选。" if multiple
                else "单目标默认使用核心及备份全部候选。")
    else:
        rule = (f"多目标从核心候选池抽取总计{requested_count}题，按目标尽量均衡分配，每个目标至少1题。"
                if multiple else f"单目标从核心及备份合并候选池抽取{requested_count}题，不区分两库优先级。")
    lines = ["# 课程思政评价问卷导出说明", "", f"价值目标：{names}",
             "选题规则：" + rule,
             "目标上限：最多6个目标，同一主归属维度最多3个。",
             f"导出用途：{'候选审查' if purpose == 'review' else '施测文件'}。",
             f"题数：{len(candidates)}。格式：{'问卷星文本' if output_format == 'wjx' else '学习通Excel测评题'}。",
             "本文件未执行反向赋值、正确答案判定、合分、阈值或等级解释。",
             "统一五级同意选项是候选工作方案；不表示与原题量尺等值。",
             "文件已在本地生成，尚未在目标平台实际导入验证。", ""]
    if requested_count is not None:
        method = {"all": "全量选取", "uniform_without_bank_priority": "核心及备份同池等概率抽题",
                  "balanced_projects_uniform_within_project": "按目标均衡分配，各目标内等概率抽题"}[policy["sampling_method"]]
        lines += [f"可用候选数：{policy['available_candidate_count']}；指定总题数：{requested_count}。",
                  f"抽题方法：{method}；种子：{policy.get('sampling_seed')}。",
                  "各目标题数：" + "、".join(
                      f"{project['name']}{policy['project_question_counts'][project['id']]}题"
                      for project in selection["projects"]), ""]
    if purpose == "review":
        lines += [f"当前有{len(blockers)}题未满足正式施测条件。审查稿保留本次选题的审查状态，不能直接视作施测批准。",
                  "科研诚信RI-L001—RI-L016仍按交接候选文字展示；历史F1/F2双量尺确认与本候选方案的冲突保留于来源映射，不在此自动解决。", ""]
    lines += ["## 逐题审查状态", "", "|序号|候选ID|价值目标|候选库|风险|启用状态|",
              "|---:|---|---|---|---|---|"]
    for n, candidate in enumerate(candidates, 1):
        values = [candidate["candidate_id"], candidate["project_name"], candidate["bank"],
                  candidate["risk_level"] or "未按P分级", candidate["activation_status"]]
        lines.append("|" + str(n) + "|" + "|".join(v.replace("|", "／").replace("\n", " ")
                                                  for v in values) + "|")
    return "\n".join(lines) + "\n"


def export_candidate_survey(goals=None, output_format="wjx", output_dir=None, request_id=None,
                            purpose="review", dimensions_path=None, store=None, *,
                            question_count=None, seed=0):
    """Export selected banks or an explicitly sized subset as one output bundle."""
    request_id = _parameter("request_id", request_id) or str(uuid.uuid4())
    if not isinstance(output_format, str) or output_format not in FORMAT_PROFILES:
        raise DataError("INVALID_REQUEST", "请选择问卷星文本（wjx）或学习通Excel（chaoxing）。")
    if not isinstance(purpose, str) or purpose not in {"review", "survey"}:
        raise DataError("INVALID_REQUEST", "导出用途须为review或survey。")
    if store is not None and dimensions_path is not None:
        raise DataError("INVALID_REQUEST", "不能同时传入数据存储和维度配置路径。")
    if dimensions_path is not None:
        if not isinstance(dimensions_path, (str, Path)):
            raise DataError("INVALID_REQUEST", "维度配置路径须为非空路径。")
        _parameter("dimensions_path", str(dimensions_path), required=True)
    store = store or CandidateStore(dimensions_path=dimensions_path)
    selected = store.select_projects(goals, question_count=question_count, seed=seed)
    projects, candidates = selected["projects"], selected["candidates"]
    blockers = _release_blockers(candidates)
    if purpose == "survey" and blockers:
        raise DataError("SURVEY_RELEASE_BLOCKED", "所选题库仍有未批准或暂缓题，未生成正式施测文件。",
                        details=[{"candidate_count": len(candidates), "blockers": blockers}])
    if purpose == "review":
        suffix = "（候选审查稿）"
    else:
        suffix = ""
    title = "课程思政评价问卷" + suffix
    items = [{"candidate_id": candidate["candidate_id"], "item_text_zh": candidate["item_text_zh"],
              "options": list(OPTIONS)} for candidate in candidates]
    # Validate source text before either format is serialized.
    for item in items:
        _student_line(item["item_text_zh"], "item_text_zh")
    if output_format == "wjx":
        payload = render_wjx(items, title)
        profile = dict(FORMAT_PROFILES["wjx"])
    else:
        from chaoxing_export import render_chaoxing
        payload = render_chaoxing(items, title=title)
        profile = dict(FORMAT_PROFILES["chaoxing"])
        template = SKILL_ROOT / "assets" / "importQuestionTemplateNew.xls"
        if template.is_file():
            profile["template_sha256"] = hashlib.sha256(template.read_bytes()).hexdigest()
    if not payload:
        raise DataError("INVALID_DATA", "导出文件为空。")
    root = resolve_output_directory(SKILL_ROOT / "output" / "candidates" if output_dir is None else output_dir)
    for name in ("assets", "references"):
        protected = (SKILL_ROOT / name).resolve()
        if root == protected or root.is_relative_to(protected):
            raise DataError("INVALID_REQUEST", "输出目录不能覆盖模板或运行资料。")
    token = uuid.uuid4().hex
    destination = root / (_safe_name(title) + "-" + token[:12])
    staging = root / (".partial-" + token)
    primary_name = "questionnaire" + profile["extension"]
    filenames = (primary_name, "teacher-notes.md", "manifest.json")
    counts = {"project_count": len(projects), "candidate_count": len(candidates),
              "core_count": sum(c["bank"] == "核心候选题库" for c in candidates),
              "backup_count": sum(c["bank"] == "备份候选题库" for c in candidates),
              "export_question_count": len(candidates)}
    mapping = []
    sources, decisions = {}, {}
    for n, candidate in enumerate(candidates, 1):
        candidate_sources = store.source_records_for(candidate["candidate_id"])
        candidate_decisions = store.decision_records_for(candidate["candidate_id"])
        sources.update((r["source_record_id"], r) for r in candidate_sources)
        decisions.update((r["decision_event_id"], r) for r in candidate_decisions)
        mapping.append({"export_question_number": n, "candidate_id": candidate["candidate_id"],
                        "project_id": candidate["project_id"], "project_slug": candidate["project_slug"],
                        "source_record_ids": [r["source_record_id"] for r in candidate_sources],
                        "decision_event_ids": [r["decision_event_id"] for r in candidate_decisions]})
    manifest = {"schema_version": "kcsz-candidate-survey-v1", "request_id": request_id,
                "title": title, "purpose": purpose, "projects": projects,
                "data_version": store.index["data_version"], "input_files": store.index["files"],
                "dimension_config": store.dimension_config,
                "selection": selected["selection"], "counts": counts,
                "format_profile": profile, "review": selected.get("review", {}),
                "release_eligible": not blockers, "release_blockers": blockers,
                "automatic_scoring": False, "actual_import_verified": False,
                "response_options": list(OPTIONS), "mapping": mapping,
                "candidates": candidates, "source_records": list(sources.values()),
                "teacher_decisions": list(decisions.values()),
                "files": [{"name": primary_name, "role": "primary",
                           "sha256": hashlib.sha256(payload).hexdigest()},
                          {"name": filenames[1], "role": "teacher"},
                          {"name": filenames[2], "role": "mapping"}]}
    notes = _teacher_notes(selected, candidates, blockers, output_format, purpose)
    created = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        created = True
        (staging / primary_name).write_bytes(payload)
        (staging / filenames[1]).write_text(notes, encoding="utf-8", newline="\n")
        (staging / filenames[2]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2,
                                                    allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        if destination.exists():
            raise FileExistsError("Refusing to replace an existing questionnaire export.")
        staging.rename(destination)
    except (OSError, ValueError) as exc:
        cleanup_failed = False
        if created and staging.is_dir():
            try:
                for name in filenames:
                    (staging / name).unlink(missing_ok=True)
                staging.rmdir()
            except OSError:
                cleanup_failed = True
        raise DataError("OUTPUT_WRITE_FAILED", "问卷导出未完成，未交付完整文件包。",
                        details=[{"cleanup_failed": cleanup_failed}]) from exc
    artifacts = [{"name": name, "path": str(destination / name), "role": role,
                  "content_type": mime, "validation": "pending_user_import" if role == "primary" else "local_metadata"}
                 for name, role, mime in zip(filenames, ("primary", "teacher", "mapping"),
                                            (profile["content_type"], "text/markdown; charset=utf-8", "application/json"))]
    return {"request_id": request_id, "title": title, "projects": projects,
            "selection": selected["selection"], "counts": counts, "purpose": purpose,
            "format_profile": profile, "release_eligible": not blockers,
            "attachment_filename": _safe_name("、".join(p["name"] for p in projects) + "评价问卷" + suffix)
                                   + profile["extension"],
            "artifacts": artifacts, "output_directory": str(destination),
            "verification": {"actual_import_verified": False, "automatic_scoring": False}}


def run_request(goals=None, output_format="wjx", output_dir=None, request_id=None,
                purpose="review", dimensions_path=None, store=None, *, question_count=None, seed=0):
    started = datetime.now(timezone.utc).isoformat()
    identity, result, error, code = str(uuid.uuid4()), None, None, 0
    try:
        identity = _parameter("request_id", request_id) or identity
        result = export_candidate_survey(goals, output_format, output_dir, identity, purpose,
                                        dimensions_path, store, question_count=question_count, seed=seed)
    except DataError as caught:
        error = caught
        code = 5 if caught.code == "OUTPUT_WRITE_FAILED" else 4 if caught.code in {
            "INVALID_DATA", "SURVEY_RELEASE_BLOCKED", "TARGET_FORMAT_LIMIT"} else 2
    label = "问卷星TXT" if output_format == "wjx" else "学习通Excel"
    message = f"已生成{label}及来源映射，待目标平台导入核对。"
    if purpose == "review":
        message += "当前文件为候选审查稿。"
    return make_result_envelope("export_candidates", result, error, request_id=identity,
                                started_at=started, title="课程思政评价问卷", message=message), code


def parser():
    result = StructuredParser(description="按价值目标选取候选题，导出问卷星TXT或学习通Excel。")
    result.add_argument("--goal", action="append", help="价值目标名称、稳定标识或编号；重复指定多个目标")
    result.add_argument("--format", choices=tuple(FORMAT_PROFILES), default="wjx", dest="output_format")
    result.add_argument("--purpose", choices=("review", "survey"), default="review")
    result.add_argument("--dimensions-file", help="经确认的3维度及18目标归属JSON", dest="dimensions_path")
    result.add_argument("--output-dir")
    result.add_argument("--request-id")
    result.add_argument("--question-count", type=int, help="整份问卷总题数；省略时按单目标全候选/多目标全核心导出")
    result.add_argument("--seed", type=int, help="指定题数时的抽题种子，默认0；相同请求和种子可复现")
    result.add_argument("--list", action="store_true", help="列出18个价值目标及当前上位维度归属")
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if args.seed is not None and args.question_count is None:
            raise DataError("INVALID_REQUEST", "指定抽题种子时须同时指定选题数。")
        if args.list:
            if args.goal or args.question_count is not None or args.seed is not None:
                raise DataError("INVALID_REQUEST", "列目录与导出目标不能同时指定。")
            store = CandidateStore(dimensions_path=args.dimensions_path)
            envelope = make_result_envelope("list_candidates", {"projects": store.list_projects(),
                                             "validation": store.validate()}, request_id=args.request_id)
            code = 0
        else:
            envelope, code = run_request(args.goal, args.output_format, args.output_dir, args.request_id,
                                         args.purpose, args.dimensions_path,
                                         question_count=args.question_count, seed=0 if args.seed is None else args.seed)
    except DataError as caught:
        envelope = make_result_envelope("export_candidates", error=caught)
        code = 4 if caught.code == "INVALID_DATA" else 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
