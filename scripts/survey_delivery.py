"""Deliver all source versions together, using the shared single-export core.

UTF-8 candidates and metadata only; no survey service, answers, or models.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

from survey_data import DataError, SKILL_ROOT, StructuredParser, SurveyStore, make_result_envelope, read_json
from survey_export import _parameter, export_questionnaire, resolve_output_directory
from survey_presentation import RULES_PATH


def _text_name(project, version):
    if project["id"] == "engineering-ethics":
        return "工程伦理_作答规则补全_基础题型适配_待导入核对.txt"
    version_label = version + "卷" if version in {"A", "B"} else "原版"
    return project["name"] + "_" + version_label + "_待导入核对.txt"


def _copy_file_exact(source, target):
    data = source.read_bytes()
    data.decode("utf-8")
    with target.open("xb") as handle:  # A file in the new delivery is never replaced.
        handle.write(data)
    if target.read_bytes() != data:
        raise OSError("The delivery copy does not match its current export.")


def _remove_owned_directory(path, parent):
    # A recursive operation is allowed only for the exclusively created stage
    # inside this resolved, explicitly named output root.
    resolved, boundary = path.resolve(), parent.resolve()
    if resolved.parent != boundary or not resolved.name.startswith(".partial-phase-2-1-"):
        raise OSError("Refusing cleanup outside the owned delivery staging directory.")
    shutil.rmtree(resolved)


def _manifest_for_delivery(manifest, artifacts, run_id):
    result = deepcopy(manifest)
    result["files"] = [{"name": a["name"], "path": a["path"], "role": a["role"],
                        "sha256": a["sha256"], "validation": a["validation"]}
                       for a in artifacts if a["role"] != "mapping"]
    # Self hashes are not embedded in the manifest; the delivery index records
    # that hash after serialization, avoiding a circular checksum.
    result["files"].append({"name": artifacts[2]["name"], "path": artifacts[2]["path"],
                            "role": "mapping", "validation": "local_metadata"})
    result["delivery"] = {"run_id": run_id, "copied_from_current_export": True,
                          "identity_and_primary_sha256_checked": True,
                          "primary_path": artifacts[0]["path"], "teacher_path": artifacts[1]["path"],
                          "mapping_path": artifacts[2]["path"],
                          "producer_manifest_sha256": artifacts[2]["producer_manifest_sha256"]}
    return result


def export_all_candidates(output_dir=None, request_id=None):
    """Commit one new, central delivery directory after all 16 exports verify."""
    request_id = _parameter("request_id", request_id) or str(uuid.uuid4())
    output = resolve_output_directory(output_dir if output_dir is not None else SKILL_ROOT / "output")
    store = SurveyStore()
    projects = store.list_projects()
    rules_sha256 = hashlib.sha256(RULES_PATH.read_bytes()).hexdigest()
    if len(projects) != 12 or sum(len(p["versions"]) for p in projects) != 16:
        raise DataError("INVALID_DATA", "集中交付须完整覆盖12项目/16来源版本。")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    final = output / ("phase-2-1-" + run_id)
    stage = output / (".partial-phase-2-1-" + run_id)
    owned = False
    entries, artifacts, names, produced_bundles = [], [], set(), []
    try:
        output.mkdir(parents=True, exist_ok=True)
        stage.mkdir()
        owned = True
        (stage / "教师说明").mkdir()
        (stage / "来源映射").mkdir()
        for project in projects:
            for version in project["versions"]:
                current = export_questionnaire(project["id"], version["id"], output_dir=stage / "_current_exports",
                                               request_id=request_id + ":" + version["questionnaire_id"], store=store)
                expected_id = version["questionnaire_id"]
                if (current["questionnaire_id"] != expected_id or current["project_id"] != project["id"] or
                        current["version_id"] != version["id"]):
                    raise DataError("INVALID_DATA", "本轮生产结果与交付索引的项目/版本不一致。")
                by_role = {a["role"]: a for a in current["artifacts"]}
                if set(by_role) != {"primary", "teacher", "mapping"} or len(current["artifacts"]) != 3:
                    raise DataError("INVALID_DATA", "本轮导出产物集合不完整。")
                source_txt, source_teacher = Path(by_role["primary"]["path"]), Path(by_role["teacher"]["path"])
                source_manifest = Path(by_role["mapping"]["path"])
                bundle = Path(current["output_directory"]).resolve()
                if not bundle.is_relative_to((stage / "_current_exports").resolve()):
                    raise DataError("INVALID_DATA", "交付只能复制本轮专用目录中的导出产物。")
                for artifact in (source_txt, source_teacher, source_manifest):
                    if artifact.resolve().parent != bundle:
                        raise DataError("INVALID_DATA", "生产文件未归属于本轮项目版本导出包。")
                manifest = read_json(source_manifest)
                if (manifest["questionnaire_id"] != expected_id or manifest["project_id"] != project["id"] or
                        manifest["version_id"] != version["id"] or manifest["request_id"] != current["request_id"] or
                        manifest["counts"] != current["counts"] or manifest["presentation_rules_sha256"] != rules_sha256):
                    raise DataError("INVALID_DATA", "本轮manifest来源身份不一致。")
                primary_hash = hashlib.sha256(source_txt.read_bytes()).hexdigest()
                primary_record = next(f for f in manifest["files"] if f["role"] == "primary")
                if primary_record["sha256"] != primary_hash or manifest["verification"]["wjx_import"] != "pending_user_validation":
                    raise DataError("INVALID_DATA", "候选文本与本轮manifest校验和或验收状态不一致。")
                text_name = _text_name(project, version["id"])
                if text_name in names or Path(text_name).name != text_name:
                    raise DataError("INVALID_DATA", "集中交付中文文件名重复或含路径组件。")
                names.add(text_name)
                stem = text_name[:-4]
                destinations = [Path(text_name), Path("教师说明") / (stem + "_教师说明.md"),
                                Path("来源映射") / (stem + "_manifest.json")]
                delivery_artifacts = [{"name": path.name, "path": str(final / path), "role": role,
                                       "content_type": mime, "validation": "pending_user_import" if role == "primary" else "local_metadata"}
                                      for path, role, mime in zip(destinations, ("primary", "teacher", "mapping"),
                                          ("text/plain; charset=utf-8", "text/markdown; charset=utf-8", "application/json"))]
                _copy_file_exact(source_txt, stage / destinations[0])
                _copy_file_exact(source_teacher, stage / destinations[1])
                delivery_artifacts[0]["sha256"] = primary_hash
                delivery_artifacts[1]["sha256"] = hashlib.sha256(source_teacher.read_bytes()).hexdigest()
                delivery_artifacts[2]["producer_manifest_sha256"] = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
                delivered_manifest = _manifest_for_delivery(manifest, delivery_artifacts, run_id)
                (stage / destinations[2]).write_text(json.dumps(delivered_manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                                   encoding="utf-8", newline="\n")
                delivery_artifacts[2]["sha256"] = hashlib.sha256((stage / destinations[2]).read_bytes()).hexdigest()
                entries.append({"project_id": project["id"], "project_name": project["name"], "version_id": version["id"],
                                "questionnaire_id": expected_id, "txt_path": delivery_artifacts[0]["path"],
                                "teacher_path": delivery_artifacts[1]["path"], "manifest_path": delivery_artifacts[2]["path"],
                                "artifacts": delivery_artifacts, "counts": current["counts"],
                                "verification": current["verification"], "actual_status": "已生成；待用户导入验证",
                                "source": manifest["source"], "source_review_status": manifest["source_review"]["status"],
                                "response_adaptations": current.get("response_adaptations", [])})
                artifacts.extend(delivery_artifacts)
                produced_bundles.append(bundle)
        # The intermediate single-export artifacts are local producers, never
        # returned as deliverables. Remove only their three registered files.
        for bundle in produced_bundles:
            for name in ("survey.pending-import.txt", "teacher-notes.md", "manifest.json"):
                (bundle / name).unlink()
            bundle.rmdir()
        (stage / "_current_exports").rmdir()
        index = {"schema_version": 1, "run_id": run_id, "request_id": request_id,
                 "coverage": {"projects": 12, "source_versions": 16, "generated": len(entries)},
                 "delivery_directory": str(final), "status": "candidates_generated_pending_import",
                 "actual_import": "pending_user_validation", "free_account_import": "not_verified",
                 "presentation_rules_sha256": rules_sha256,
                 "workbuddy": "not_verified", "teach_claw": "not_verified", "entries": entries}
        (stage / "交付清单.json").write_text(json.dumps(index, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                          encoding="utf-8", newline="\n")
        lines = ["# 阶段2.1集中交付清单", "", "全部12项目、16来源版本已生成。所有TXT均为待用户导入核对候选，未通过免费账号实际导入或宿主运行验证。",
                 "", "16份中文TXT直接位于本目录；教师说明与来源映射分别位于同名子目录。工程伦理q003/q004各为一个普通文本框，排序合法性须人工核对，不自动计分或分析。", "",
                 "| 项目 | 来源版本 | TXT | 教师说明 | 来源映射 | 实际状态 |", "| --- | --- | --- | --- | --- | --- |"]
        for entry in entries:
            relative = [Path(a["path"]).relative_to(final).as_posix() for a in entry["artifacts"]]
            links = [f"[{Path(p).name}](<{p}>)" for p in relative]
            lines.append(f"| {entry['project_name']} | {entry['version_id']} | {' | '.join(links)} | {entry['actual_status']} |")
        (stage / "交付清单.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        # A last physical check precedes commit. No mtime-based selection.
        for artifact in artifacts:
            path = stage / Path(artifact["path"]).relative_to(final)
            path.read_text(encoding="utf-8")
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise DataError("INVALID_DATA", "集中交付实际文件与清单哈希不一致。")
        if len(list(stage.glob("*.txt"))) != 16 or len(entries) != 16:
            raise DataError("INVALID_DATA", "集中交付未实际生成16份TXT。")
        if final.exists():
            raise FileExistsError("Refusing to overwrite an earlier delivery.")
        stage.rename(final)
    except (DataError, OSError, ValueError, KeyError, StopIteration) as exc:
        cleanup_error = None
        if owned and stage.exists():
            try:
                _remove_owned_directory(stage, output)
            except OSError as cleanup:
                cleanup_error = str(cleanup)
        if isinstance(exc, DataError) and cleanup_error is None:
            raise
        raise DataError("OUTPUT_WRITE_FAILED", "集中交付失败；没有交付完整的本轮目录。",
                        details=[{"reason": str(exc), "cleanup_error": cleanup_error,
                                  "incomplete_directory": str(stage) if cleanup_error else None}]) from exc
    for name, mime in (("交付清单.json", "application/json"), ("交付清单.md", "text/markdown; charset=utf-8")):
        artifacts.append({"name": name, "path": str(final / name), "role": "index", "content_type": mime,
                          "validation": "local_metadata", "sha256": hashlib.sha256((final / name).read_bytes()).hexdigest()})
    return {"run_id": run_id, "request_id": request_id, "output_directory": str(final),
            "coverage": index["coverage"], "entries": entries, "artifacts": artifacts,
            "verification": {"text_generation": "generated", "wjx_import": "pending_user_validation",
                             "free_account_import": "not_verified", "workbuddy": "not_verified", "teach_claw": "not_verified"}}


def parser():
    result = StructuredParser(description="将全部16来源版本候选集中交付为中文TXT。")
    result.add_argument("--output-dir", default=str(SKILL_ROOT / "output"), help="新交付目录的父目录")
    result.add_argument("--request-id")
    return result


def main(argv=None):
    started, request_id = datetime.now(timezone.utc).isoformat(), str(uuid.uuid4())
    result, error, exit_code = None, None, 0
    try:
        args = parser().parse_args(argv)
        request_id = _parameter("request_id", args.request_id) or request_id
        result = export_all_candidates(args.output_dir, request_id)
    except DataError as exc:
        error = exc
        exit_code = 5 if exc.code == "OUTPUT_WRITE_FAILED" else 4 if exc.code in {"INVALID_DATA", "TARGET_FORMAT_LIMIT", "PRESENTATION_BLOCKED"} else 2
    envelope = make_result_envelope("deliver", result, error, request_id=request_id, started_at=started,
                                    title="课程思政问卷集中交付",
                                    message="全部16来源版本候选TXT已集中生成；待用户导入验证。")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
