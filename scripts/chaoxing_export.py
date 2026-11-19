"""Offline Chaoxing assessment-question export using the supplied XLS template.

The import template explicitly permits assessment questions without an answer.
This writes real BIFF8/XLS, never a renamed XML/CSV file. Only the template's
font/number/style records are retained; instructions, examples, formulas, OLE
objects, links and macros are not copied. The output has one Workbook stream.
"""
from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
import math
from pathlib import Path
import struct

from survey_data import DataError


ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"
TEMPLATE_PATH = ASSET_ROOT / "importQuestionTemplateNew.xls"
PROFILE_PATH = ASSET_ROOT / "chaoxing-template-profile.json"
HEADERS = ("目录", "题目类型", "自定义题型", "大题题干", "小题题型", "小题题干",
           "正确答案", "答案解析", "难易度", "知识点", "标签", "选项数",
           "选项A", "选项B", "选项C", "选项D", "选项E", "选项F", "选项G", "选项H")
SHEET_NAME = "课程题库"
FREE_SECTOR = 0xFFFFFFFF
END_OF_CHAIN = 0xFFFFFFFE
FAT_SECTOR = 0xFFFFFFFD
BIFF_RECORD_LIMIT = 8224


def _invalid(message):
    return DataError("INVALID_DATA", message)


def _record(kind, payload=b""):
    if len(payload) > BIFF_RECORD_LIMIT:
        raise _invalid("学习通 Excel 记录超过 BIFF8 限制。")
    return struct.pack("<HH", kind, len(payload)) + payload


def _template_workbook(raw):
    """Read the fixed, hash-checked template's regular Workbook stream."""
    if raw[:8] != bytes.fromhex("d0cf11e0a1b11ae1") or struct.unpack_from("<H", raw, 30)[0] != 9:
        raise _invalid("学习通原始模板不是预期的 XLS 文件。")
    sector = lambda number: raw[(number + 1) * 512:(number + 2) * 512]
    fat = []
    for number in struct.unpack_from("<109I", raw, 76):
        if number < FAT_SECTOR:
            fat.extend(struct.unpack("<128I", sector(number)))

    def stream(first):
        chunks, visited = [], set()
        while first != END_OF_CHAIN:
            if first in visited or not 0 <= first < len(fat):
                raise _invalid("学习通原始模板的扇区链无效。")
            visited.add(first)
            chunks.append(sector(first))
            first = fat[first]
        return b"".join(chunks)

    directory = stream(struct.unpack_from("<I", raw, 48)[0])
    for offset in range(0, len(directory), 128):
        entry = directory[offset:offset + 128]
        length = struct.unpack_from("<H", entry, 64)[0]
        if length and entry[:length - 2].decode("utf-16le") == "Workbook":
            size = struct.unpack_from("<Q", entry, 120)[0]
            if size < 4096:
                raise _invalid("学习通模板 Workbook 存储方式已改变。")
            return stream(struct.unpack_from("<I", entry, 116)[0])[:size]
    raise _invalid("学习通原始模板缺少 Workbook。")


def _style_records():
    try:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        raw = TEMPLATE_PATH.read_bytes()
        if (hashlib.sha256(raw).hexdigest() != profile["source_template"]["sha256"]
                or tuple(profile["headers"]) != HEADERS
                or profile["worksheet_name"] != SHEET_NAME):
            raise _invalid("学习通模板或模板契约校验值不一致。")
        workbook = _template_workbook(raw)
    except (OSError, ValueError, KeyError, struct.error, UnicodeError) as exc:
        raise _invalid("学习通模板无法读取或契约无效。") from exc
    # Required workbook globals and inert formatting only. No NAME, SUPBOOK,
    # EXTERNSHEET, OBJ, drawing, VBA or original cell/string records are copied.
    allowed = {0x0809, 0x00E1, 0x00C1, 0x00E2, 0x0042, 0x0161, 0x013D,
               0x0019, 0x0012, 0x0013, 0x003D, 0x0040, 0x008D, 0x0022,
               0x000E, 0x01B7, 0x00DA, 0x0031, 0x041E, 0x00E0, 0x0293}
    kept, offset = [], 0
    while offset + 4 <= len(workbook):
        kind, size = struct.unpack_from("<HH", workbook, offset)
        end = offset + 4 + size
        if end > len(workbook):
            raise _invalid("学习通模板的 BIFF 记录不完整。")
        if kind == 0x000A:
            break
        if kind in allowed:
            kept.append(workbook[offset:end])
        offset = end
    return b"".join(kept)


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise DataError("INVALID_PARAMETER", f"{label}必须是非空文字。")
    if any(ord(c) < 32 and c not in "\t\r\n" for c in value):
        raise DataError("INVALID_PARAMETER", f"{label}含不支持的控制字符。")
    try:
        encoded = value.encode("utf-16le")
    except UnicodeError as exc:
        raise DataError("INVALID_PARAMETER", f"{label}含无效字符。") from exc
    if len(encoded) // 2 > 32767:
        raise DataError("TARGET_FORMAT_LIMIT", f"{label}超过 Excel 单元格文字限制。")
    return value


def _rows(items):
    yield list(HEADERS)
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise DataError("INVALID_PARAMETER", "学习通题项必须是对象。")
        candidate_id = _text(item.get("candidate_id"), "候选题编号")
        if candidate_id in seen:
            raise DataError("INVALID_PARAMETER", "学习通导出包含重复候选题编号。")
        seen.add(candidate_id)
        text = _text(item.get("item_text_zh"), "题文")
        options = item.get("options")
        if not isinstance(options, list) or len(options) != 5:
            raise DataError("INVALID_PARAMETER", "学习通候选题必须明确提供五个作答选项。")
        options = [_text(option, "作答选项") for option in options]
        if len(set(options)) != len(options):
            raise DataError("INVALID_PARAMETER", "学习通作答选项不能重复。")
        directory_parts = []
        for key in ("dimension_name", "project_name"):
            if item.get(key):
                part = _text(item[key], "题库目录")
                if "/" in part or "\\" in part or part in {".", ".."}:
                    raise DataError("INVALID_PARAMETER", "题库目录名称不能包含路径分隔符。")
                directory_parts.append(part)
        directory = "/" + "/".join(directory_parts) if directory_parts else ""
        if directory:
            _text(directory, "题库目录")
        # No correct answer, scoring key, interpretation or reverse-code hints.
        yield [directory, "测评题", "", text, "", "", "", "", "", "", "", 5,
               *options, "", "", ""]


def _sst(values, total):
    """Build SST/CONTINUE records, including long UTF-16 strings."""
    chunks = []
    current = bytearray(struct.pack("<II", total, len(values)))
    for value in values:
        encoded = value.encode("utf-16le")
        if BIFF_RECORD_LIMIT - len(current) < 3:
            chunks.append(bytes(current))
            current = bytearray()
        current.extend(struct.pack("<HB", len(encoded) // 2, 1))
        offset = 0
        while offset < len(encoded):
            room = (BIFF_RECORD_LIMIT - len(current)) // 2 * 2
            if not room:
                chunks.append(bytes(current))
                current = bytearray(b"\x01")  # Continued string is UTF-16.
                continue
            size = min(room, len(encoded) - offset)
            # Keep surrogate pairs together at continuation boundaries.
            if size < len(encoded) - offset:
                last = struct.unpack_from("<H", encoded, offset + size - 2)[0]
                if 0xD800 <= last <= 0xDBFF:
                    size -= 2
                    if not size:
                        chunks.append(bytes(current))
                        current = bytearray(b"\x01")
                        continue
            current.extend(encoded[offset:offset + size])
            offset += size
    chunks.append(bytes(current))
    return b"".join(_record(0x00FC if index == 0 else 0x003C, chunk)
                    for index, chunk in enumerate(chunks))


def _directory_entry(name, kind, first, size, child=FREE_SECTOR):
    name_bytes = (name + "\0").encode("utf-16le")
    result = bytearray(128)
    result[:len(name_bytes)] = name_bytes
    struct.pack_into("<HBBIII", result, 64, len(name_bytes), kind, 1,
                     FREE_SECTOR, FREE_SECTOR, child)
    struct.pack_into("<IQ", result, 116, first, size)
    return bytes(result)


def _compound_file(workbook):
    """Single-stream CFB v3 with regular sectors, no mini stream or metadata."""
    stream_size = max(4096, len(workbook))
    data_count = (stream_size + 511) // 512
    fat_count = 1
    while (data_count + 1 + fat_count + 127) // 128 != fat_count:
        fat_count = (data_count + 1 + fat_count + 127) // 128
    if fat_count > 109:
        raise DataError("TARGET_FORMAT_LIMIT", "学习通导出超出当前 XLS 文件大小限制。")
    directory_sector = data_count
    fat_start = directory_sector + 1
    entries = [number + 1 for number in range(data_count)]
    entries[-1] = END_OF_CHAIN
    entries += [END_OF_CHAIN] + [FAT_SECTOR] * fat_count
    entries += [FREE_SECTOR] * (fat_count * 128 - len(entries))
    header = bytearray(512)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHHH", header, 24, 0x003E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, fat_count, directory_sector, 0,
                     4096, END_OF_CHAIN, 0, END_OF_CHAIN, 0)
    difat = list(range(fat_start, fat_start + fat_count)) + [FREE_SECTOR] * (109 - fat_count)
    struct.pack_into("<109I", header, 76, *difat)
    directory = (_directory_entry("Root Entry", 5, END_OF_CHAIN, 0, child=1)
                 + _directory_entry("Workbook", 2, 0, stream_size) + bytes(256))
    return (bytes(header) + workbook.ljust(data_count * 512, b"\0") + directory
            + struct.pack("<" + str(len(entries)) + "I", *entries))


def render_chaoxing(items: Iterable[dict], title=None) -> bytes:
    """Return the template's 20-column assessment workbook as genuine XLS bytes.

    ``title`` is accepted for caller parity; filenames carry titles. The fixed
    import sheet has no added title/instruction rows. Every text is an SST cell,
    including text beginning with =, +, -, or @; none becomes an Excel formula.
    Platform import remains a user validation step.
    """
    if title is not None:
        _text(title, "问卷标题")
    try:
        rows = list(_rows(items))
    except TypeError as exc:
        raise DataError("INVALID_PARAMETER", "学习通题项必须是可迭代集合。") from exc
    if len(rows) == 1:
        raise DataError("INVALID_PARAMETER", "学习通问卷至少需要一道题。")
    if len(rows) > 65536:
        raise DataError("TARGET_FORMAT_LIMIT", "学习通 XLS 超过 65536 行限制。")
    strings, indexes, total = [], {}, 0
    for row in rows:
        for value in row:
            if isinstance(value, str) and value:
                total += 1
                if value not in indexes:
                    indexes[value] = len(strings)
                    strings.append(value)
    shared_strings = _sst(strings, total)
    globals_prefix = _style_records()

    def boundsheet(offset):
        name = SHEET_NAME.encode("utf-16le")
        return _record(0x0085, struct.pack("<IBBBB", offset, 0, 0, len(name) // 2, 1) + name)

    sheet_offset = len(globals_prefix) + len(boundsheet(0)) + len(shared_strings) + 4
    globals_data = globals_prefix + boundsheet(sheet_offset) + shared_strings + _record(0x000A)
    sheet = [_record(0x0809, struct.pack("<HHHHII", 0x0600, 0x0010, 0x0DBB, 0x07CC,
                                       0x000180C1, 0x00000606)),
             _record(0x0200, struct.pack("<IIHHH", 0, len(rows), 0, len(HEADERS), 0))]
    widths = [28, 12, 14, 70, 12, 25, 12, 22, 10, 20, 15, 10] + [20] * 8
    for column, width in enumerate(widths):
        sheet.append(_record(0x007D, struct.pack("<HHHHHH", column, column, width * 256, 15, 0, 0)))
    for row_number, row in enumerate(rows):
        height = 400 if row_number == 0 else min(4000, max(500, math.ceil(len(row[3]) / 45) * 300))
        sheet.append(_record(0x0208, struct.pack("<HHHHHHI", row_number, 0, len(HEADERS),
                                               height, 0, 0, 0x00000100)))
        for column, value in enumerate(row):
            style = 64 if row_number == 0 else 67
            if isinstance(value, str) and value:
                sheet.append(_record(0x00FD, struct.pack("<HHHI", row_number, column, style, indexes[value])))
            elif isinstance(value, int):
                sheet.append(_record(0x0203, struct.pack("<HHHd", row_number, column, style, value)))
    sheet.append(_record(0x023E, struct.pack("<HHHIHHI", 0x06B6, 0, 0, 0x00000040, 0, 0, 0)))
    sheet.append(_record(0x000A))
    return _compound_file(globals_data + b"".join(sheet))
