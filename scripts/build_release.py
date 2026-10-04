"""Build a local release candidate from an explicit allowlist, with no Git/network use."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import uuid
import zipfile

from survey_data import SurveyStore
from survey_presentation import load_presentation_rules


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "kcsz-course-survey"
PDF_FILES = (
    "docs/武汉大学课程思政教学评价指南（第一辑）.pdf",
    "docs/武汉大学课程思政教学评价指南（第二辑）.pdf",
)
QUESTIONNAIRE_FILES = (
    "data/questionnaires/critical-thinking--A.json",
    "data/questionnaires/critical-thinking--B.json",
    "data/questionnaires/learning-self-efficacy--A.json",
    "data/questionnaires/learning-self-efficacy--B.json",
    "data/questionnaires/professional-identity--A.json",
    "data/questionnaires/professional-identity--B.json",
    "data/questionnaires/patriotism--original.json",
    "data/questionnaires/core-literacy--original.json",
    "data/questionnaires/scientific-spirit--A.json",
    "data/questionnaires/scientific-spirit--B.json",
    "data/questionnaires/creativity--original.json",
    "data/questionnaires/learning-style-engagement--original.json",
    "data/questionnaires/cooperation-social--original.json",
    "data/questionnaires/thinking-problem-solving--original.json",
    "data/questionnaires/cultural-identity--original.json",
    "data/questionnaires/engineering-ethics--original.json",
)
PUBLIC_FILES = tuple(sorted((
    ".gitignore", "SKILL.md", "README.md", "BUILDING.md", "SOURCES.md", "VERSION",
    "LICENSE", "RELEASE_NOTES.md",
    "references/public-call.md", "references/runtime.md", "references/import-feedback.md",
    "references/workbuddy.md", "references/teach-claw.md",
    "scripts/survey_data.py", "scripts/survey_presentation.py", "scripts/survey_export.py",
    "scripts/survey_delivery.py", "scripts/build_release.py",
    "data/catalog.json", "data/presentation-rules.json",
    "tests/test_survey_data.py", "tests/test_survey_export.py", "tests/test_survey_delivery.py",
    "tests/test_skill_package.py", "tests/test_release_build.py",
    *QUESTIONNAIRE_FILES, *PDF_FILES,
)))
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _category(relative: str) -> str:
    if relative in PDF_FILES:
        return "third_party_source_pdf"
    if relative in QUESTIONNAIRE_FILES:
        return "transcribed_source_questionnaire"
    if relative == "data/presentation-rules.json":
        return "approved_derived_presentation_rules"
    if relative.startswith("scripts/"):
        return "code"
    if relative.startswith("tests/"):
        return "test"
    return "documentation_or_index"


def collect_public_files(root: Path) -> tuple[str, dict[str, bytes]]:
    root = root.resolve()
    if len(PUBLIC_FILES) != len(set(PUBLIC_FILES)):
        raise ValueError("The public allowlist has duplicate paths.")
    payload: dict[str, bytes] = {}
    for relative in PUBLIC_FILES:
        parts = PurePosixPath(relative)
        if parts.is_absolute() or ".." in parts.parts:
            raise ValueError("The public allowlist contains an unsafe path.")
        source = root / relative
        if source.is_symlink() or not source.resolve().is_relative_to(root) or not source.is_file():
            raise ValueError(f"Missing or unsafe allowlisted file: {relative}")
        content = source.read_bytes()
        if relative not in PDF_FILES:
            content.decode("utf-8")
        payload[relative] = content
    version = payload["VERSION"].decode("utf-8").strip()
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[a-z0-9.]+)?", version):
        raise ValueError("VERSION must contain a release version identifier.")
    store = SurveyStore(root / "data")
    validation = store.validate_all()
    if validation["projects"] != 12 or validation["versions"] != 16:
        raise ValueError("Expected 12 projects and 16 source versions.")
    actual = {"data/" + v["file"] for p in store.catalog["projects"] for v in p["versions"]}
    sources = {"docs/" + s["filename"] for s in store.catalog["sources"]}
    if actual != set(QUESTIONNAIRE_FILES) or sources != set(PDF_FILES):
        raise ValueError("The catalog and release allowlist do not match.")
    load_presentation_rules(root / "data/presentation-rules.json")
    for relative, content in payload.items():
        if not relative.endswith(".md"):
            continue
        for target in re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", content.decode("utf-8")):
            if target.startswith(("https://", "http://", "#")):
                continue
            local = target.split("#", 1)[0]
            resolved = (root / relative).parent.joinpath(local).resolve()
            if not resolved.is_relative_to(root) or resolved.relative_to(root).as_posix() not in payload:
                raise ValueError(f"Unpackaged reference in {relative}")
    return version, payload


def build_candidate(root: Path = ROOT, output_dir: Path | None = None,
                    candidate_id: str | None = None) -> dict:
    """Make a new directory; neither old candidates nor source files are overwritten."""
    root = Path(root).resolve()
    version, payload = collect_public_files(root)
    if candidate_id is None:
        candidate_id = version + "-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}", candidate_id):
        raise ValueError("candidate_id must be a single safe directory name.")
    parent = Path(output_dir).resolve() if output_dir is not None else root / "release-candidate"
    for protected in [root / n for n in ("data", "scripts", "tests", "docs", "references")]:
        if parent == protected or parent.is_relative_to(protected):
            raise ValueError("The output directory cannot be a source resource directory.")
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / candidate_id
    destination.mkdir(exist_ok=False)
    # A failed build stays visibly incomplete; never delete an existing candidate.
    marker = destination / "BUILD-INCOMPLETE"
    marker.write_text("This directory is not a completed release candidate.\n", encoding="utf-8")
    source_root = destination / "source" / PACKAGE_NAME
    source_root.mkdir(parents=True)
    entries = []
    for relative, content in payload.items():
        target = source_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(content)
        entries.append({"path": relative, "bytes": len(content), "sha256": sha256(content),
                        "category": _category(relative)})
    zip_name = f"{PACKAGE_NAME}-{version}-workbuddy.zip"
    zip_path = destination / zip_name
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, content in payload.items():
            info = zipfile.ZipInfo(PACKAGE_NAME + "/" + relative, FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content, compresslevel=9)
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None or archive.namelist() != [PACKAGE_NAME + "/" + p for p in payload]:
            raise ValueError("Archive member validation failed.")
        for relative, content in payload.items():
            if archive.read(PACKAGE_NAME + "/" + relative) != content:
                raise ValueError("Archive content validation failed.")
    release_notes_name = "release-notes.md"
    release_notes_content = payload["RELEASE_NOTES.md"]
    release_notes_path = destination / release_notes_name
    with release_notes_path.open("xb") as handle:
        handle.write(release_notes_content)
    manifest = {
        "schema_version": 1, "name": PACKAGE_NAME, "version": version,
        "scope": "local_release_candidate", "public_release_ready": True,
        "public_release_ready_meaning": "Local materials are complete under the user's publication instruction; this builder does not publish remotely or verify a new host installation.",
        "public_release_pending": [],
        "github_repository": "awei0728/kcsz-course-survey",
        "remote_release_status": "not_published_by_builder",
        "publication_authorization": {
            "basis": "user_instruction",
            "code_license": {
                "spdx": "MIT", "license_file": "LICENSE",
                "copyright": "Copyright (c) 2026 awei0728",
                "scope": "original_project_code_and_original_project_materials",
                "excluded_materials": ["third_party_source_pdfs", "original_scale_content",
                                       "verbatim_transcribed_items", "corresponding_source_content_in_derived_materials"],
            },
            "source_pdfs": {
                "publication_status": "user_confirmed_publication_permitted",
                "evidence": "user_instruction", "rights": "retained_by_original_authors_and_publishers",
                "included_in_project_mit_license": False, "third_party_open_license_asserted": False,
                "authorization_document_or_school_endorsement_asserted": False,
            },
            "transcribed_and_source_derived_content": {
                "publication_status": "included_by_user_publication_instruction",
                "rights": "retained_by_original_authors_and_publishers",
                "included_in_project_mit_license": False,
            },
        },
        "source_directory": "source/" + PACKAGE_NAME, "file_count": len(entries),
        "files": entries, "contains_source_pdfs": True,
        "pdf_files": [e for e in entries if e["category"] == "third_party_source_pdf"],
        "pdf_reason": "Runtime source-integrity validation reads both original PDFs and checks SHA-256.",
        "coverage": {"projects": 12, "source_versions": 16},
        "verification": {"prior_workbuddy_package": "user_feedback_passed_loading_and_creativity",
                         "this_candidate_workbuddy": "not_reloaded",
                         "wjx_user_feedback_passed": ["creativity--original", "engineering-ethics--original"],
                         "other_source_versions_wjx": "pending_user_feedback", "teach_claw": "deferred"},
        "release_notes": {"path": release_notes_name, "bytes": len(release_notes_content),
                          "sha256": sha256(release_notes_content), "source_path": "RELEASE_NOTES.md"},
        "zip": {"path": zip_name, "bytes": zip_path.stat().st_size,
                "sha256": sha256(zip_path.read_bytes()), "root_directory": PACKAGE_NAME,
                "fixed_timestamp": list(FIXED_ZIP_TIME), "compression": "deflate_level_9",
                "reproducibility_scope": "same input bytes and Python/zlib build environment"},
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    checksums = [("source/" + PACKAGE_NAME + "/" + e["path"], e["sha256"]) for e in entries]
    checksums += [(zip_name, manifest["zip"]["sha256"]), ("manifest.json", sha256(manifest_path.read_bytes())),
                  (release_notes_name, manifest["release_notes"]["sha256"])]
    checksum_path = destination / "SHA256SUMS"
    checksum_path.write_text("".join(f"{digest}  {path}\n" for path, digest in sorted(checksums)),
                             encoding="utf-8", newline="\n")
    marker.unlink()
    return {"ok": True, "version": version, "source_directory": str(source_root),
            "zip_path": str(zip_path), "manifest_path": str(manifest_path),
            "checksum_path": str(checksum_path), "release_notes_path": str(release_notes_path),
            "file_count": len(entries),
            "zip_bytes": manifest["zip"]["bytes"], "zip_sha256": manifest["zip"]["sha256"],
            "public_release_ready": True, "remote_release_status": "not_published_by_builder", "model_trace": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a local candidate; no remote repository or release is created.")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--candidate-id")
    args = parser.parse_args(argv)
    try:
        result = build_candidate(output_dir=args.output_dir, candidate_id=args.candidate_id)
        code = 0
    except Exception as exc:
        # Do not print file contents, configuration, credentials or traceback locals.
        result = {"ok": False, "error": {"code": "BUILD_FAILED", "message": str(exc)}, "model_trace": []}
        code = 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
