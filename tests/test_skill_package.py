"""Standard-library structural checks; not a host or language-understanding test."""
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillPackageTests(unittest.TestCase):
    def test_portable_frontmatter_has_only_name_and_description(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        header = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(header)
        values = {}
        for line in header.group(1).splitlines():
            key, value = line.split(":", 1)
            self.assertNotIn(key, values)
            values[key] = value.strip()
        self.assertEqual(set(values), {"name", "description"})
        self.assertEqual(values["name"], ROOT.name)
        self.assertRegex(values["name"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        self.assertLessEqual(len(values["name"]), 64)
        # Description is a JSON-compatible quoted YAML scalar, so this exact
        # two-scalar format can be checked without a runtime YAML dependency.
        description = json.loads(values["description"])
        self.assertIsInstance(description, str)
        self.assertTrue(description.strip())
        self.assertLessEqual(len(description), 1024)

    def test_entrypoint_references_resolve_inside_skill_package(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        targets = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
        self.assertTrue(targets)
        for target in targets:
            with self.subTest(target=target):
                path = (ROOT / target).resolve()
                self.assertTrue(path.is_relative_to(ROOT.resolve()))
                self.assertTrue(path.is_file())
                path.read_text(encoding="utf-8")
        self.assertEqual((ROOT / "data/catalog.json").is_file(), True)
        self.assertEqual(len(list((ROOT / "data/questionnaires").glob("*.json"))), 16)


if __name__ == "__main__":
    unittest.main()
