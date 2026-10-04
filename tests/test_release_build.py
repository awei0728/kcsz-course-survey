"""Release boundaries and reproducibility, not a WorkBuddy upload test."""
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_release


class ReleaseBuildTests(unittest.TestCase):
    def setUp(self):
        temporary_parent = ROOT / "tmp"
        temporary_parent.mkdir(exist_ok=True)
        self.temporary = TemporaryDirectory(prefix="release-build-test-", dir=temporary_parent)
        self.addCleanup(self.temporary.cleanup)
        self.area = Path(self.temporary.name)
        self.clone = self.area / "中文源码" / "kcsz-course-survey"
        _, payload = build_release.collect_public_files(ROOT)
        for relative, content in payload.items():
            target = self.clone / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def test_allowlist_and_determinism_ignore_private_files_and_mtime(self):
        private = self.clone / "local-only-config.txt"
        private.write_text("This non-allowlisted file must never enter the candidate.", encoding="utf-8")
        first = build_release.build_candidate(self.clone, self.area / "构建", "first")
        for relative in build_release.PUBLIC_FILES:
            os.utime(self.clone / relative, (1700000000, 1700000000))
        second = build_release.build_candidate(self.clone, self.area / "构建", "second")
        self.assertEqual(Path(first["zip_path"]).read_bytes(), Path(second["zip_path"]).read_bytes())
        self.assertEqual(Path(first["manifest_path"]).read_bytes(), Path(second["manifest_path"]).read_bytes())
        self.assertEqual(Path(first["checksum_path"]).read_bytes(), Path(second["checksum_path"]).read_bytes())
        self.assertEqual(Path(first["release_notes_path"]).read_bytes(), Path(second["release_notes_path"]).read_bytes())
        source = Path(first["source_directory"])
        actual = {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}
        self.assertEqual(actual, set(build_release.PUBLIC_FILES))
        self.assertFalse((source / private.name).exists())
        with zipfile.ZipFile(first["zip_path"]) as archive:
            self.assertIsNone(archive.testzip())
            for name in archive.namelist():
                self.assertTrue(name.startswith("kcsz-course-survey/"))
                relative = name.removeprefix("kcsz-course-survey/")
                self.assertEqual(archive.read(name), (source / relative).read_bytes())
        manifest = json.loads(Path(first["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["pdf_files"]), 2)
        self.assertTrue(manifest["public_release_ready"])
        self.assertEqual(manifest["remote_release_status"], "not_published_by_builder")
        self.assertEqual(manifest["github_repository"], "awei0728/kcsz-course-survey")
        checksum_lines = Path(first["checksum_path"]).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(checksum_lines), len(build_release.PUBLIC_FILES) + 3)
        for line in checksum_lines:
            digest, relative = line.split("  ", 1)
            self.assertFalse(Path(relative).is_absolute())
            self.assertEqual(digest, hashlib.sha256((source.parents[1] / relative).read_bytes()).hexdigest())

    def test_license_scope_and_release_notes_are_explicit_and_consistent(self):
        result = build_release.build_candidate(self.clone, self.area / "builds", "licensed")
        source = Path(result["source_directory"])
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        license_text = (source / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2026 awei0728", license_text)
        self.assertIn("Permission is hereby granted, free of charge", license_text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', license_text)
        authorization = manifest["publication_authorization"]
        self.assertEqual(authorization["basis"], "user_instruction")
        self.assertEqual(authorization["code_license"]["spdx"], "MIT")
        self.assertEqual(set(authorization["code_license"]["excluded_materials"]), {
            "third_party_source_pdfs", "original_scale_content", "verbatim_transcribed_items",
            "corresponding_source_content_in_derived_materials",
        })
        self.assertFalse(authorization["source_pdfs"]["included_in_project_mit_license"])
        self.assertFalse(authorization["source_pdfs"]["third_party_open_license_asserted"])
        self.assertFalse(authorization["source_pdfs"]["authorization_document_or_school_endorsement_asserted"])
        self.assertFalse(authorization["transcribed_and_source_derived_content"]["included_in_project_mit_license"])
        self.assertEqual(manifest["verification"]["this_candidate_workbuddy"], "not_reloaded")
        self.assertEqual(manifest["verification"]["other_source_versions_wjx"], "pending_user_feedback")
        notes = manifest["release_notes"]
        attachment = Path(result["release_notes_path"])
        self.assertEqual(attachment.name, notes["path"])
        self.assertEqual(attachment.read_bytes(), (source / notes["source_path"]).read_bytes())
        self.assertEqual(attachment.stat().st_size, notes["bytes"])
        self.assertEqual(hashlib.sha256(attachment.read_bytes()).hexdigest(), notes["sha256"])
        self.assertIn(f'{notes["sha256"]}  {notes["path"]}',
                      Path(result["checksum_path"]).read_text(encoding="utf-8"))

    def test_existing_candidate_is_not_overwritten(self):
        first = build_release.build_candidate(self.clone, self.area / "builds", "one")
        artifact_keys = ("zip_path", "manifest_path", "checksum_path", "release_notes_path")
        original = {key: Path(first[key]).read_bytes() for key in artifact_keys}
        with self.assertRaises(FileExistsError):
            build_release.build_candidate(self.clone, self.area / "builds", "one")
        self.assertEqual({key: Path(first[key]).read_bytes() for key in artifact_keys}, original)

    def test_missing_runtime_pdf_fails_before_candidate_creation(self):
        (self.clone / build_release.PDF_FILES[0]).unlink()
        destination = self.area / "builds"
        with self.assertRaises(ValueError):
            build_release.build_candidate(self.clone, destination, "missing-source")
        self.assertFalse(destination.exists())

    def test_local_reference_to_excluded_file_is_rejected(self):
        with (self.clone / "README.md").open("a", encoding="utf-8") as handle:
            handle.write("\n[excluded](tmp/development-notes.md)\n")
        with self.assertRaisesRegex(ValueError, "Unpackaged reference"):
            build_release.collect_public_files(self.clone)


if __name__ == "__main__":
    unittest.main()
