"""Deterministic TeachClaw parameter adapter; no chat routing or model calls.

The host parses the Chinese command and passes argv as separate strings. This
module validates the real catalog and reuses the existing public exporter.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

from survey_data import (DataError, StructuredParser, SurveyStore,
                         make_result_envelope)
from survey_export import _parameter, export_questionnaire


# Explicitly authorized by the user for this command, not a new source alias.
COMMAND_ALIASES = {"爱国主义": "patriotism"}
USER_FEEDBACK_PASSED = {
    "creativity--original",
    "engineering-ethics--original",
}


def _candidates(projects):
    return [{"id": project["id"], "name": project["name"],
             "versions": [version["id"] for version in project["versions"]]}
            for project in projects]


def _unknown_project_message(projects):
    lines = ["未找到该评价项目，请从以下12个项目中选择："]
    lines.extend(f"{number}. {project['name']}"
                 for number, project in enumerate(projects, 1))
    lines += ["正确写法：生成课程思政调查问卷 --创造力",
              "爱国主义也可写为：生成课程思政调查问卷 --爱国主义"]
    return "\n".join(lines)


def _resolve_project(query, projects):
    if query is None or (isinstance(query, str) and not query.strip()):
        key = ""
    else:
        key = _parameter("project", query, required=True)
    key = COMMAND_ALIASES.get(key, key).casefold()
    matches = [project for project in projects
               if key and key in {project["id"].casefold(), project["name"].casefold()}]
    if not matches:
        raise DataError("PROJECT_NOT_FOUND", _unknown_project_message(projects),
                        candidates=_candidates(projects))
    if len(matches) != 1:
        raise DataError("AMBIGUOUS_PROJECT", "项目名称不明确，请选择准确项目名称或标识。",
                        candidates=_candidates(matches))
    return matches[0]


def _exit_code(error):
    if error.code == "OUTPUT_WRITE_FAILED":
        return 5
    if error.code in {"INVALID_DATA", "PRESENTATION_BLOCKED", "TARGET_FORMAT_LIMIT"}:
        return 4
    return 2


def _feedback(questionnaire_id):
    passed = questionnaire_id in USER_FEEDBACK_PASSED
    return {"status": "user_feedback_passed" if passed else "pending_user_feedback",
            "evidence_kind": "user_report" if passed else None,
            "scope": "source_version_and_current_presentation",
            "current_artifact_import_verified": False,
            "note": "该版本此前获用户反馈导入通过；不表示本次文件已经导入。"
                    if passed else "该版本待用户逐版导入验证。"}


def run_request(project=None, version=None, request_id=None, output_dir=None, store=None, *,
                goals=None, output_format=None, purpose=None, dimensions_path=None,
                question_count=None, seed=None):
    """Return (the existing JSON result envelope, exit code), without printing.

    Invalid/unknown/ambiguous requests only read catalog/source data. The public
    exporter alone creates a new output bundle after all validation succeeds.
    """
    started = datetime.now(timezone.utc).isoformat()
    identity = str(uuid.uuid4())
    result, error, code = None, None, 0
    message = None
    try:
        identity = _parameter("request_id", request_id) or identity
        candidate_mode = any(value is not None for value in
                             (goals, output_format, purpose, dimensions_path, question_count, seed))
        if candidate_mode:
            if version is not None:
                raise DataError("INVALID_REQUEST", "候选组卷不能指定A/B等旧来源版本。")
            if goals is not None and project is not None:
                raise DataError("INVALID_REQUEST", "请选择goals或单个project，不要混用两种目标参数。")
            if seed is not None and question_count is None:
                raise DataError("INVALID_REQUEST", "抽题种子须与指定总选题数一起使用。")
            from candidate_survey import run_request as run_candidate_request
            selected_goals = goals if goals is not None else ([project] if project is not None else None)
            return run_candidate_request(
                goals=selected_goals, output_format="wjx" if output_format is None else output_format,
                output_dir=output_dir, request_id=identity, purpose="review" if purpose is None else purpose,
                dimensions_path=dimensions_path, store=store, question_count=question_count,
                seed=0 if seed is None else seed)
        version = _parameter("version", version)
        store = store or SurveyStore()
        projects = store.list_projects()
        selected = _resolve_project(project, projects)
        versions = [record["id"] for record in selected["versions"]]
        if version is None and len(versions) != 1:
            choices = "、".join(value + "卷" if value in {"A", "B"} else value
                               for value in versions)
            raise DataError("VERSION_REQUIRED", f"{selected['name']}有{choices}，请回复选择A卷或B卷。",
                            details=[{"project_id": selected["id"], "project_name": selected["name"],
                                      "versions": versions}],
                            candidates=[{"project_id": selected["id"], "version_id": value}
                                        for value in versions])
        selected_version = version if version is not None else versions[0]
        source = store.read_version(selected["id"], selected_version)
        result = export_questionnaire(selected["id"], selected_version, output_dir=output_dir,
                                      request_id=identity, store=store)
        result["project_name"] = selected["name"]
        display_name = "爱国主义" if selected["id"] == "patriotism" else selected["name"]
        version_suffix = f"_{selected_version}卷" if selected_version in {"A", "B"} else ""
        result["attachment_filename"] = f"{display_name}问卷{version_suffix}.txt"
        result["source"] = source["source"]
        result["user_import_feedback"] = _feedback(result["questionnaire_id"])
        primary = [artifact for artifact in result["artifacts"] if artifact["role"] == "primary"]
        if len(primary) != 1 or any(not Path(artifact["path"]).is_file()
                                    for artifact in result["artifacts"]):
            raise DataError("OUTPUT_WRITE_FAILED", "生成产物未全部找到，不能交付问卷文件。")
        label = selected_version + "卷" if selected_version in {"A", "B"} else "原版"
        message = (f"已生成{selected['name']}{label}，请查收TXT，自行导入问卷星。"
                   + result["user_import_feedback"]["note"])
        if selected["id"] == "engineering-ethics":
            message += "工程伦理采用作答规则补全及基础题型适配；排序代码及‘其他’说明需人工核对。"
        if selected["id"] == "core-literacy":
            message += "本原卷评价指标合理性，不应解释为学生个人素养水平测量。"
    except DataError as caught:
        error, code, result = caught, _exit_code(caught), None
        if caught.code in {"VERSION_REQUIRED", "VERSION_NOT_FOUND"}:
            result = {"project_id": selected["id"], "project_name": selected["name"],
                      "versions": [record["id"] for record in selected["versions"]]}
    return make_result_envelope("export", result, error, request_id=identity,
                                started_at=started, title="课程思政调查问卷", message=message), code


def parser():
    result = StructuredParser(description="TeachClaw课程思政问卷参数入口；不解析整句聊天消息。")
    result.add_argument("--project", help="正式项目名称、稳定ID，或明确授权名称‘爱国主义’")
    result.add_argument("--goal", action="append", help="18项目候选价值目标，可重复；多目标最多6个且每维度最多3个")
    result.add_argument("--format", dest="output_format", choices=("wjx", "chaoxing"),
                        help="候选问卷输出：问卷星文本或学习通Excel；显式指定后使用18项目候选题库")
    result.add_argument("--purpose", choices=("review", "survey"),
                        help="候选组卷用途：review审查稿（默认）或survey正式施测资格检查")
    result.add_argument("--dimensions-file", help="三个上位维度与18个价值目标的显式归属配置")
    result.add_argument("--question-count", type=int, help="整份候选问卷总题数；单目标从全部候选选，多目标仅核心")
    result.add_argument("--seed", type=int, help="抽题种子，默认0；须与--question-count一起使用")
    result.add_argument("--version", help="A/B项目须明确选择；单一来源版可省略")
    result.add_argument("--request-id", help="可选调用方请求标识")
    result.add_argument("--output-dir", help="缺省为实际Skill根目录/output")
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        envelope, code = run_request(args.project, args.version, args.request_id, args.output_dir,
                                     goals=args.goal, output_format=args.output_format,
                                     purpose=args.purpose, dimensions_path=args.dimensions_file,
                                     question_count=args.question_count, seed=args.seed)
    except DataError as error:
        envelope = make_result_envelope("export", error=error, title="课程思政调查问卷")
        code = _exit_code(error)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
