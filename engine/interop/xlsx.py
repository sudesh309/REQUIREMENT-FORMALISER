"""Minimal, standard-library-only spreadsheet containers.

- ``write_xlsx(sheets)`` / ``read_xlsx(data)``: Office Open XML workbooks
  (SpreadsheetML). The writer emits inline strings, numbers and booleans with a
  bold, frozen header row; the reader understands shared strings, inline
  strings, numbers, booleans and formula results, which covers files saved by
  Excel, LibreOffice and Google Sheets.
- ``write_csv_zip(sheets)`` / ``read_csv_zip(data)``: one UTF-8 CSV per sheet.
- ``safe_xml(data)``: parses XML after rejecting DTDs and entity declarations
  (no billion-laughs / external entity expansion).

Archives are written with fixed timestamps so the same tables always give the
same bytes, and read with size limits (zip-bomb protection).

``sheets`` is an ordered ``{name: [[cell, ...], ...]}`` whose first row is the
header.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
import zlib
import xml.etree.ElementTree as ET
from typing import Any, Iterable
from xml.sax.saxutils import escape, quoteattr

from .common import InteropError, cell_text

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024     # total uncompressed size accepted
MAX_ARCHIVE_ENTRIES = 2000
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)

Sheets = dict[str, list[list[Any]]]


# --- safe XML ----------------------------------------------------------------

_FORBIDDEN = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def _decode_xml_bytes(data: bytes) -> bytes:
    """Return UTF-8 bytes for the DTD check (handles UTF-16 documents)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16").encode("utf-8")
    return data


def safe_xml(data: bytes | str) -> ET.Element:
    """Parse XML, refusing documents with a DTD or entity declarations."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if _FORBIDDEN.search(_decode_xml_bytes(raw)):
        raise InteropError("XML with a DOCTYPE or ENTITY declaration is not accepted")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as ex:
        raise InteropError(f"malformed XML: {ex}") from None


def local(tag: str) -> str:
    """Tag or attribute name without its {namespace}."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


# --- zip helpers -------------------------------------------------------------

def _zip_bytes(files: Iterable[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            info = zipfile.ZipInfo(name, date_time=_FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    return buf.getvalue()


def open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise InteropError("not a ZIP archive (expected .xlsx or a .zip of CSV files)") from None
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise InteropError(f"archive has too many entries ({len(infos)})")
    if sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
        raise InteropError("archive is too large when uncompressed")
    return zf


def _read_member(zf: zipfile.ZipFile, name: str) -> bytes:
    info = zf.getinfo(name)
    if info.file_size > MAX_ARCHIVE_BYTES:
        raise InteropError(f"{name} is too large")
    try:
        return zf.read(info)
    except (zipfile.BadZipFile, zlib.error, EOFError) as ex:
        raise InteropError(f"corrupt archive member {name}: {ex}") from None


# --- XLSX writer ---------------------------------------------------------------

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_SHEET_NAME_BAD = re.compile(r"[\[\]:*?/\\]")


def col_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        s = chr(65 + rem) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _sheet_name(name: str, used: set[str]) -> str:
    base = _SHEET_NAME_BAD.sub("_", name or "Sheet")[:31] or "Sheet"
    out, i = base, 1
    while out.lower() in used:
        suffix = f"_{i}"
        out = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(out.lower())
    return out


def _cell_xml(ref: str, value: Any, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"{s}><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value \
            and value not in (float("inf"), float("-inf")):
        return f'<c r="{ref}"{s}><v>{repr(value) if isinstance(value, float) else value}</v></c>'
    text = _ILLEGAL_XML.sub("", cell_text(value))[:32767]
    space = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
    return f'<c r="{ref}" t="inlineStr"{s}><is><t{space}>{escape(text)}</t></is></c>'


def _sheet_xml(rows: list[list[Any]]) -> str:
    ncols = max((len(r) for r in rows), default=0)
    widths = []
    for c in range(ncols):
        longest = max((len(cell_text(r[c])) for r in rows if c < len(r)), default=8)
        widths.append(min(max(longest + 2, 8), 60))
    parts = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
             f'<worksheet xmlns="{_NS_MAIN}" xmlns:r="{_NS_REL}">']
    if rows:
        parts.append('<sheetViews><sheetView workbookViewId="0">'
                     '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                     '</sheetView></sheetViews>')
    if widths:
        parts.append("<cols>" + "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths)) + "</cols>")
    parts.append("<sheetData>")
    for r, row in enumerate(rows):
        cells = "".join(_cell_xml(f"{col_letter(c)}{r + 1}", v, 1 if r == 0 else 0)
                        for c, v in enumerate(row))
        parts.append(f'<row r="{r + 1}">{cells}</row>')
    parts.append("</sheetData>")
    if rows and ncols:
        parts.append(f'<autoFilter ref="A1:{col_letter(ncols - 1)}{max(len(rows), 1)}"/>')
    parts.append("</worksheet>")
    return "".join(parts)


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<styleSheet xmlns="{_NS_MAIN}">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFDCE6F1"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


def write_xlsx(sheets: Sheets) -> bytes:
    """Write ``{sheet name: rows}`` as an .xlsx workbook (deterministic bytes)."""
    used: set[str] = set()
    names = [_sheet_name(n, used) for n in sheets]
    n = len(names)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                  'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                  for i in range(n))
        + '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>')
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{_NS_PKG_REL}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>')
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<workbook xmlns="{_NS_MAIN}" xmlns:r="{_NS_REL}"><sheets>'
        + "".join(f'<sheet name={quoteattr(name)} sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                  for i, name in enumerate(names))
        + "</sheets></workbook>")
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{_NS_PKG_REL}">'
        + "".join(f'<Relationship Id="rId{i + 1}" '
                  'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                  f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(n))
        + f'<Relationship Id="rId{n + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>')
    files = [
        ("[Content_Types].xml", content_types.encode("utf-8")),
        ("_rels/.rels", root_rels.encode("utf-8")),
        ("xl/workbook.xml", workbook.encode("utf-8")),
        ("xl/_rels/workbook.xml.rels", wb_rels.encode("utf-8")),
        ("xl/styles.xml", _STYLES.encode("utf-8")),
    ]
    for i, rows in enumerate(sheets.values()):
        files.append((f"xl/worksheets/sheet{i + 1}.xml", _sheet_xml(rows).encode("utf-8")))
    return _zip_bytes(files)


# --- XLSX reader -----------------------------------------------------------------

_REF = re.compile(r"^([A-Za-z]+)(\d+)$")


def _text_of(node: ET.Element) -> str:
    """Concatenated <t> text of a shared/inline string, skipping phonetic runs."""
    out = []
    for child in node:
        name = local(child.tag)
        if name == "t":
            out.append(child.text or "")
        elif name == "r":
            out.extend(t.text or "" for t in child if local(t.tag) == "t")
    return "".join(out)


def _number(text: str) -> Any:
    try:
        if re.fullmatch(r"[-+]?\d+", text.strip()):
            return int(text)
        return float(text)
    except ValueError:
        return text


def read_xlsx(data: bytes) -> Sheets:
    """Read every worksheet of an .xlsx workbook into ``{name: rows}``."""
    zf = open_zip(data)
    names = set(zf.namelist())
    if "xl/workbook.xml" not in names:
        raise InteropError("not an .xlsx workbook (xl/workbook.xml missing)")
    wb = safe_xml(_read_member(zf, "xl/workbook.xml"))
    targets: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        rels = safe_xml(_read_member(zf, "xl/_rels/workbook.xml.rels"))
        for rel in rels:
            if local(rel.tag) == "Relationship":
                target = rel.get("Target", "")
                target = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
                targets[rel.get("Id", "")] = target
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        sst = safe_xml(_read_member(zf, "xl/sharedStrings.xml"))
        shared = [_text_of(si) for si in sst if local(si.tag) == "si"]
    sheets: Sheets = {}
    sheet_nodes = [s for s in wb.iter() if local(s.tag) == "sheet"]
    for idx, sh in enumerate(sheet_nodes):
        rid = next((v for k, v in sh.attrib.items() if local(k) == "id"), None)
        path = targets.get(rid or "", f"xl/worksheets/sheet{idx + 1}.xml")
        if path not in names:
            continue
        sheets[sh.get("name") or f"Sheet{idx + 1}"] = _read_sheet(_read_member(zf, path), shared)
    return sheets


def _read_sheet(data: bytes, shared: list[str]) -> list[list[Any]]:
    root = safe_xml(data)
    grid: dict[int, dict[int, Any]] = {}
    next_row = 0
    for row in root.iter():
        if local(row.tag) != "row":
            continue
        r_attr = row.get("r")
        r = int(r_attr) - 1 if r_attr and r_attr.isdigit() else next_row
        next_row = r + 1
        cells = grid.setdefault(r, {})
        next_col = 0
        for c in row:
            if local(c.tag) != "c":
                continue
            ref = c.get("r")
            m = _REF.match(ref or "")
            col = col_index(m.group(1)) if m else next_col
            next_col = col + 1
            t = c.get("t", "n")
            v_node = next((x for x in c if local(x.tag) == "v"), None)
            v = v_node.text if v_node is not None else None
            if t == "inlineStr":
                is_node = next((x for x in c if local(x.tag) == "is"), None)
                value: Any = _text_of(is_node) if is_node is not None else ""
            elif t == "s":
                try:
                    value = shared[int(v or "0")]
                except (ValueError, IndexError):
                    raise InteropError(f"cell {ref}: bad shared string index {v!r}") from None
            elif t == "b":
                value = (v or "0").strip() in ("1", "true")
            elif t in ("str", "e"):
                value = v or ""
            else:
                value = _number(v) if v not in (None, "") else None
            cells[col] = value
    if not grid:
        return []
    nrows = max(grid) + 1
    ncols = max((max(c) + 1 for c in grid.values() if c), default=0)
    rows = []
    for r in range(nrows):
        cells = grid.get(r, {})
        rows.append([cells.get(c) for c in range(ncols)])
    # Drop trailing empty rows.
    while rows and all(v in (None, "") for v in rows[-1]):
        rows.pop()
    return rows


# --- CSV in a ZIP -------------------------------------------------------------------

def write_csv(rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    for row in rows:
        w.writerow([cell_text(v) for v in row])
    return buf.getvalue()


def read_csv(text: str) -> list[list[Any]]:
    if text.startswith("﻿"):
        text = text[1:]
    rows = [list(r) for r in csv.reader(io.StringIO(text))]
    while rows and all(v == "" for v in rows[-1]):
        rows.pop()
    return rows


def write_csv_zip(sheets: Sheets) -> bytes:
    """One ``<name>.csv`` (UTF-8 with BOM so Excel detects the encoding) per sheet."""
    used: set[str] = set()
    files = []
    for name, rows in sheets.items():
        fname = _sheet_name(name, used)
        files.append((f"{fname}.csv", ("﻿" + write_csv(rows)).encode("utf-8")))
    return _zip_bytes(files)


def read_csv_zip(data: bytes) -> Sheets:
    zf = open_zip(data)
    sheets: Sheets = {}
    for info in zf.infolist():
        if info.is_dir() or not info.filename.lower().endswith(".csv"):
            continue
        name = info.filename.rsplit("/", 1)[-1][:-4]
        if name.startswith("._"):     # macOS resource forks
            continue
        raw = _read_member(zf, info.filename)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        sheets[name] = read_csv(text)
    if not sheets:
        raise InteropError("the ZIP archive contains no .csv files")
    return sheets


def read_any(data: bytes, filename: str = "") -> Sheets:
    """Read .xlsx or a ZIP of CSV files (detected from content, then from the name)."""
    zf = open_zip(data)
    names = zf.namelist()
    if "xl/workbook.xml" in names:
        return read_xlsx(data)
    if any(n.lower().endswith(".csv") for n in names):
        return read_csv_zip(data)
    raise InteropError(f"{filename or 'file'}: expected an .xlsx workbook or a ZIP of CSV files")
