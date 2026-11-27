"""
Lightweight Excel (.xlsx) read/write utilities.
Uses `openpyxl` when available and falls back to pure-Python OOXML (`zipfile` + XML)
so headless scripts run cleanly even in minimal environments without `openpyxl`.
"""

import html
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple


def _col_index_from_ref(ref: str) -> int:
    col = "".join(ch for ch in ref if ch.isalpha())
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return max(0, idx - 1)


def _col_letter_from_idx(idx_1based: int) -> str:
    letters = []
    n = idx_1based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def read_xlsx_sheet(
    path: str, sheet_name: Optional[str] = None, header_row: int = 1
) -> List[Dict[str, Any]]:
    """Read an .xlsx worksheet into a list of dicts keyed by header_row (1-based)."""
    try:
        import openpyxl  # type: ignore

        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb[sheet_name] if (sheet_name and sheet_name in wb.sheetnames) else wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if len(rows) < header_row:
            return []
        headers = [str(h or "").strip() for h in rows[header_row - 1]]
        out: List[Dict[str, Any]] = []
        for r in rows[header_row:]:
            rec = {
                headers[i]: ("" if r[i] is None else r[i])
                for i in range(min(len(headers), len(r)))
                if headers[i]
            }
            if any(str(v).strip() for v in rec.values()):
                out.append(rec)
        return out
    except ImportError:
        pass

    with zipfile.ZipFile(path) as z:
        wb_xml = ET.fromstring(z.read("xl/workbook.xml"))
        rels_xml = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels_xml
            if rel.tag.endswith("}Relationship")
        }

        target_path = "xl/worksheets/sheet1.xml"
        for el in wb_xml.iter():
            if el.tag.endswith("}sheet"):
                name = el.attrib.get("name", "")
                rid = next(
                    (v for k, v in el.attrib.items() if k.endswith("}id")), None
                )
                if rid and rid in rid_to_target:
                    raw_target = rid_to_target[rid].lstrip("/")
                    cand = raw_target if raw_target.startswith("xl/") else f"xl/{raw_target}"
                    if sheet_name is None:
                        target_path = cand
                        break
                    if name == sheet_name:
                        target_path = cand
                        break

        strings: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
            strings = [
                "".join(t.text or "" for t in si.iter() if t.tag.endswith("}t"))
                for si in ss.iter()
                if si.tag.endswith("}si")
            ]

        root = ET.fromstring(z.read(target_path))
        rows_dict: Dict[int, Dict[int, Any]] = {}
        max_col = 0
        for row in root.iter():
            if row.tag.endswith("}row"):
                rnum = int(row.attrib.get("r", 0))
                rvals: Dict[int, Any] = {}
                for c in row:
                    ref = c.attrib.get("r", "")
                    ci = _col_index_from_ref(ref) if ref else len(rvals)
                    max_col = max(max_col, ci + 1)
                    t = c.attrib.get("t", "")
                    v_el = next((x for x in c if x.tag.endswith("}v")), None)
                    is_el = next((x for x in c if x.tag.endswith("}is")), None)
                    val: Any = ""
                    if t == "s" and v_el is not None:
                        val = strings[int(v_el.text or 0)]
                    elif t == "inlineStr" and is_el is not None:
                        val = "".join(
                            x.text or "" for x in is_el.iter() if x.tag.endswith("}t")
                        )
                    elif v_el is not None:
                        val = v_el.text
                    rvals[ci] = val
                rows_dict[rnum] = rvals

        if header_row not in rows_dict:
            return []
        headers = [str(rows_dict[header_row].get(i, "")).strip() for i in range(max_col)]
        out = []
        for rnum in sorted(rows_dict):
            if rnum <= header_row:
                continue
            rvals = rows_dict[rnum]
            rec = {
                headers[i]: rvals.get(i, "")
                for i in range(len(headers))
                if headers[i]
            }
            if any(str(v).strip() for v in rec.values()):
                out.append(rec)
        return out


def write_xlsx_sheets(
    path: str, sheets: List[Tuple[str, List[List[Any]]]]
) -> None:
    """Write multiple sheets (list of (sheet_name, rows_2d)) to an .xlsx workbook."""
    try:
        import openpyxl  # type: ignore
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # type: ignore

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        data_font = Font(name="Segoe UI", size=10)
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )

        for s_name, rows in sheets:
            ws = wb.create_sheet(title=s_name[:31])
            for r_idx, row in enumerate(rows, start=1):
                for c_idx, val in enumerate(row, start=1):
                    cell = ws.cell(row=r_idx, column=c_idx, value=val)
                    if r_idx == 1:
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                    else:
                        cell.font = data_font
                        cell.border = thin_border
                        cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
            for col in ws.columns:
                max_len = max(len(str(c.value or "")) for c in col[:20])
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)
        wb.save(path)
        return
    except ImportError:
        pass

    # Pure-Python OOXML fallback (valid standard .xlsx without external dependencies)
    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    wb_sheets_xml = []
    wb_rels_xml = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
    ]

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for idx, (s_name, rows) in enumerate(sheets, start=1):
            safe_name = html.escape(s_name[:31], quote=True)
            content_types.append(
                f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            wb_sheets_xml.append(
                f'<sheet name="{safe_name}" sheetId="{idx}" r:id="rId{idx}"/>'
            )
            wb_rels_xml.append(
                f'<Relationship Id="rId{idx}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{idx}.xml"/>'
            )

            sheet_lines = [
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>',
            ]
            for r_idx, row in enumerate(rows, start=1):
                cells_xml = []
                for c_idx, val in enumerate(row, start=1):
                    ref = f"{_col_letter_from_idx(c_idx)}{r_idx}"
                    if val is None or val == "":
                        continue
                    if isinstance(val, bool):
                        cells_xml.append(f'<c r="{ref}" t="b"><v>{1 if val else 0}</v></c>')
                    elif isinstance(val, (int, float)) and not isinstance(val, bool):
                        cells_xml.append(f'<c r="{ref}"><v>{val}</v></c>')
                    else:
                        txt = html.escape(str(val), quote=False)
                        cells_xml.append(
                            f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{txt}</t></is></c>'
                        )
                sheet_lines.append(f'<row r="{r_idx}">{"".join(cells_xml)}</row>')
            sheet_lines.append("</sheetData></worksheet>")
            z.writestr(f"xl/worksheets/sheet{idx}.xml", "".join(sheet_lines))

        content_types.append("</Types>")
        wb_rels_xml.append("</Relationships>")

        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(wb_sheets_xml)}</sheets>'
            "</workbook>"
        )
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        )
        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            "</styleSheet>"
        )

        z.writestr("[Content_Types].xml", "".join(content_types))
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", "".join(wb_rels_xml))
        z.writestr("xl/styles.xml", styles_xml)
