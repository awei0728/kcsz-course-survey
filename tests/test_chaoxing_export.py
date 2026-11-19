"""Read XLS output independently and verify the supplied import contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from chaoxing_export import PROFILE_PATH, TEMPLATE_PATH, render_chaoxing
from survey_data import DataError


def read_xls(blob):
    """Small independent test reader for CFB/BIFF8 LABELSST and NUMBER cells."""
    assert blob[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    sector_size = 2 ** struct.unpack_from("<H", blob, 30)[0]
    def sector(index):
        return blob[(index + 1) * sector_size:(index + 2) * sector_size]
    fat = []
    for index in struct.unpack_from("<109I", blob, 76):
        if index < 0xFFFFFFFA:
            fat += list(struct.unpack("<" + str(sector_size // 4) + "I", sector(index)))
    def chain(start):
        result = b""
        while start < 0xFFFFFFFA:
            result += sector(start)
            start = fat[start]
        return result
    directory = chain(struct.unpack_from("<I", blob, 48)[0])
    names = []
    for offset in range(0, len(directory), 128):
        entry = directory[offset:offset + 128]
        length = struct.unpack_from("<H", entry, 64)[0]
        if not length:
            continue
        name = entry[:length - 2].decode("utf-16le")
        names.append(name)
        if name == "Workbook":
            data = chain(struct.unpack_from("<I", entry, 116)[0])[:struct.unpack_from("<Q", entry, 120)[0]]
    records, offset = [], 0
    while offset + 4 <= len(data):
        kind, size = struct.unpack_from("<HH", data, offset)
        records.append((kind, data[offset + 4:offset + 4 + size]))
        offset += 4 + size

    strings = []
    for index, (kind, payload) in enumerate(records):
        if kind != 0xFC:
            continue
        chunks = [payload]
        following = index + 1
        while following < len(records) and records[following][0] == 0x3C:
            chunks.append(records[following][1])
            following += 1
        chunk, position = 0, 0
        def take(size):
            nonlocal chunk, position
            result = b""
            while size:
                if position == len(chunks[chunk]):
                    chunk, position = chunk + 1, 0
                count = min(size, len(chunks[chunk]) - position)
                result += chunks[chunk][position:position + count]
                position += count
                size -= count
            return result
        _, count = struct.unpack("<II", take(8))
        for _ in range(count):
            length, flags = struct.unpack("<HB", take(3))
            runs = struct.unpack("<H", take(2))[0] if flags & 8 else 0
            extension = struct.unpack("<I", take(4))[0] if flags & 4 else 0
            wide, pieces = flags & 1, []
            while length:
                if position == len(chunks[chunk]):
                    chunk, position = chunk + 1, 0
                    wide = take(1)[0] & 1
                width = 2 if wide else 1
                available = min(length, (len(chunks[chunk]) - position) // width)
                pieces.append(take(available * width).decode("utf-16le" if wide else "latin1"))
                length -= available
            strings.append("".join(pieces))
            take(runs * 4 + extension)
    cells, sheet_names = {}, []
    for kind, payload in records:
        if kind == 0xFD:
            row, col, _, string_id = struct.unpack("<HHHI", payload)
            cells[row, col] = strings[string_id]
        elif kind == 0x203:
            row, col, _, number = struct.unpack("<HHHd", payload)
            cells[row, col] = number
        elif kind == 0x85:
            _, _, _, length, wide = struct.unpack_from("<IBBBB", payload)
            sheet_names.append(payload[8:8 + length * (2 if wide else 1)].decode("utf-16le" if wide else "latin1"))
    return {"cells": cells, "records": records, "streams": names, "sheets": sheet_names}


def item(identity="T001", text="我不会忽略不同观点。", **extra):
    return {"candidate_id": identity, "item_text_zh": text,
            "options": ["非常不同意", "不同意", "既不同意也不反对", "同意", "非常同意"], **extra}


class ChaoxingExportTests(unittest.TestCase):
    def test_supplied_template_contract_and_source_evidence(self):
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        raw = TEMPLATE_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), profile["source_template"]["sha256"])
        source = read_xls(raw)["cells"]
        self.assertEqual([source[0, col] for col in range(20)], profile["headers"])
        self.assertIn(profile["evidence"]["assessment_rule"], source[1, 0])
        self.assertEqual(source[36, 1], "测评题")
        self.assertNotIn((36, 6), source)

    def test_exact_headers_assessment_type_five_options_and_blank_answers(self):
        doc = read_xls(render_chaoxing([item(project_name="批判性思维", dimension_name="认知")], title="课程后测"))
        cells = doc["cells"]
        headers = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))["headers"]
        self.assertEqual([cells[0, col] for col in range(20)], headers)
        self.assertEqual(doc["sheets"], ["课程题库"])
        self.assertEqual(doc["streams"], ["Root Entry", "Workbook"])
        self.assertEqual(cells[1, 0], "/认知/批判性思维")
        self.assertEqual(cells[1, 1], "测评题")
        self.assertEqual(cells[1, 3], "我不会忽略不同观点。")
        self.assertEqual(cells[1, 11], 5)
        self.assertEqual([cells[1, col] for col in range(12, 17)], item()["options"])
        for col in [2, 4, 5, 6, 7, 8, 9, 10, 17, 18, 19]:
            self.assertNotIn((1, col), cells)
        self.assertEqual(max(row for row, _ in cells), 1)

    def test_no_formula_or_external_content_and_no_example_rows(self):
        dangerous = item(text='=HYPERLINK("https://example.invalid","x")', options=["=1+1", "+2", "-3", "@SUM(A1)", "5"])
        doc = read_xls(render_chaoxing([dangerous]))
        self.assertEqual(doc["cells"][1, 3], dangerous["item_text_zh"])
        self.assertEqual([doc["cells"][1, col] for col in range(12, 17)], dangerous["options"])
        kinds = [kind for kind, _ in doc["records"]]
        for forbidden in [0x0006, 0x0018, 0x0017, 0x01AE, 0x005D, 0x00EB, 0x00EC]:
            self.assertNotIn(forbidden, kinds)
        self.assertNotIn("关于《花间集》说法错误的是", doc["cells"].values())

    def test_many_questions_and_long_unicode_continue_records_round_trip(self):
        text = "文😀" * 3500 + "\n负向题文不修改。"
        items = [item(str(number), text if number == 1 else "陈述" + str(number)) for number in range(1, 101)]
        doc = read_xls(render_chaoxing(items))
        self.assertEqual(doc["cells"][1, 3], text)
        self.assertEqual(max(row for row, _ in doc["cells"]), 100)
        self.assertIn(0x3C, [kind for kind, _ in doc["records"]])
        self.assertEqual(render_chaoxing(items), render_chaoxing(items))

    def test_reject_invalid_inputs_instead_of_inventing_answer_options(self):
        cases = [[], [item(), item()], [item(options=["是", "否"])],
                 [item(options=["相同"] * 5)], [item(text="坏\x00文字")],
                 [item(text="文" * 32768)], [item(project_name="a/b")], None]
        for records in cases:
            with self.subTest(records_type=type(records).__name__), self.assertRaises(DataError):
                render_chaoxing(records)


if __name__ == "__main__":
    unittest.main()
