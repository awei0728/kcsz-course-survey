"""Verify and import the reviewed handoff without running its bundled scripts.

Only data used by the candidate workflow is retained. All upstream manifest
entries are verified before any destination is created. Existing imports are
never overwritten. This importer uses the Python standard library only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile

from survey_data import DataError


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = SKILL_ROOT / "data" / "candidates" / "handoff-v1"
MANIFEST_NAME = "kcsz_18project_manifest_v1.json"
RETAINED_FILES = {
    "candidates": "kcsz_18project_candidates_v1.csv",
    "sources": "kcsz_18project_source_traceability_v1.csv",
    "decisions": "kcsz_18project_teacher_decisions_v1.csv",
    "projects": "kcsz_18project_project_summary_v1.csv",
    "exceptions": "kcsz_18project_priority_exceptions_v1.csv",
    "overlaps": "kcsz_18project_overlap_screen_v1.csv",
    "validation_log": "kcsz_18project_validation_log_v1.csv",
    "original_rows": "sources/item-mapping.csv",
    "upstream_manifest": MANIFEST_NAME,
}


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def csv_rows(content: bytes, filename: str) -> tuple[list[str], list[dict]]:
    try:
        records = list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))
    except (UnicodeError, csv.Error) as exc:
        raise DataError("INVALID_DATA", "候选数据不是合法的 UTF-8 CSV。",
                        details=[{"file": filename}]) from exc
    if not records or not records[0] or len(set(records[0])) != len(records[0]):
        raise DataError("INVALID_DATA", "CSV 表头为空或重复。", details=[{"file": filename}])
    header = records[0]
    if any(len(record) != len(header) for record in records[1:]):
        raise DataError("INVALID_DATA", "CSV 记录列数与表头不一致。", details=[{"file": filename}])
    return header, [dict(zip(header, record)) for record in records[1:]]


def raw_signature(row: dict, fields: list[str], prefix="") -> str:
    values = [row[prefix + key] for key in fields]
    return sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def read_verified_archive(archive_path: Path | str) -> tuple[dict, dict[str, bytes], str]:
    archive_path = Path(archive_path)
    try:
        archive_content = archive_path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(archive_content)) as archive:
            infos = archive.infolist()
            names = [entry.filename for entry in infos]
            if len(names) != len(set(names)) or sum(entry.file_size for entry in infos) > 32 * 1024 * 1024:
                raise ValueError("duplicate archive members or excessive uncompressed size")
            for name in names:
                member = PurePosixPath(name)
                if member.is_absolute() or ".." in member.parts or "\\" in name or ":" in name:
                    raise ValueError("unsafe archive member")
            manifest_bytes = archive.read(MANIFEST_NAME)
            manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
            if manifest.get("schema_version") != "kcsz-18project-consolidation-v1":
                raise ValueError("unsupported handoff version")
            verified = {}
            for category, prefix in (("source_inputs", "sources/"), ("outputs", "")):
                for entry in manifest[category]:
                    name = prefix + entry["file"]
                    content = archive.read(name)
                    if len(content) != entry["bytes"] or sha256(content) != entry["sha256"]:
                        raise ValueError("upstream manifest hash mismatch: " + name)
                    verified[name] = content
            retained = {name: (manifest_bytes if name == MANIFEST_NAME else verified[name])
                        for name in RETAINED_FILES.values()}
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, TypeError, UnicodeError) as exc:
        raise DataError("INVALID_HANDOFF", "交接包完整性校验失败，未导入数据。",
                        details=[{"reason": str(exc)}]) from exc
    for name, content in retained.items():
        if name.endswith(".csv"):
            csv_rows(content, name)
    raw_fields, originals = csv_rows(retained[RETAINED_FILES["original_rows"]], "item-mapping.csv")
    _, sources = csv_rows(retained[RETAINED_FILES["sources"]], RETAINED_FILES["sources"])
    try:
        original_signatures = Counter(raw_signature(row, raw_fields) for row in originals)
        retained_signatures = Counter(raw_signature(row, raw_fields, "raw_") for row in sources)
        if len(raw_fields) != 30 or len(originals) != 505 or original_signatures != retained_signatures:
            raise ValueError("original 505 rows / 30 fields are not preserved")
        if any(raw_signature(row, raw_fields, "raw_") != row["source_integrity_sha256"] for row in sources):
            raise ValueError("source raw-field integrity mismatch")
    except (ValueError, KeyError) as exc:
        raise DataError("INVALID_HANDOFF", "交接包原始字段无损校验失败。") from exc
    return manifest, retained, sha256(archive_content)


def import_handoff(archive_path: Path | str, output_dir: Path | str = DEFAULT_OUTPUT) -> dict:
    manifest, retained, archive_hash = read_verified_archive(archive_path)
    index = {
        "schema_version": 1,
        "data_version": "consolidation-v1",
        "archive_sha256": archive_hash,
        "status": manifest["status"],
        "counts": manifest["counts"],
        "files": {role: {"file": name, "sha256": sha256(retained[name]), "bytes": len(retained[name])}
                  for role, name in RETAINED_FILES.items()},
        "import_policy": "verified upstream SHA256; data only; no bundled code executed",
    }
    index_bytes = (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        try:
            matches = (output_dir / "import-manifest.json").read_bytes() == index_bytes
            matches = matches and all((output_dir / name).read_bytes() == content for name, content in retained.items())
        except OSError:
            matches = False
        if not matches:
            raise DataError("OUTPUT_EXISTS", "目标导入目录已存在且内容不同；拒绝覆盖。")
        return {"data_version": index["data_version"], "counts": index["counts"], "unchanged": True}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".candidate-import-", dir=output_dir.parent))
    try:
        for name, content in retained.items():
            destination = temporary / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        (temporary / "import-manifest.json").write_bytes(index_bytes)
        temporary.rename(output_dir)
    except OSError as exc:
        raise DataError("OUTPUT_WRITE_FAILED", "候选数据导入写入失败；未覆盖现有目录。") from exc
    finally:
        if temporary.exists():
            # This directory was exclusively created by this invocation, under
            # the resolved destination parent; no input/user directory is removed.
            shutil.rmtree(temporary)
    return {"data_version": index["data_version"], "counts": index["counts"], "unchanged": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        result = import_handoff(args.archive, args.output_dir)
    except DataError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
