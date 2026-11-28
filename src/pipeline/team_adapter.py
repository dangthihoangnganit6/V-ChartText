"""Nối demo app.py với bước 2–3 dùng trong thực nghiệm (verify.py luật R1–R9 + describe.py).

app.py giữ nguyên bước 1 (Qwen3-VL), bước 4 (TTS Hoài My), giao diện và ViChartFact; chỉ thay chỗ gọi bước 2–3:

    val_status, val_notes, flagged_matrix, desc_dict = run_step23(step1_dict)

Đầu vào step1_dict: định dạng phẳng của app.py / Benchmark.xlsx (chart_title, chart_type, unit, x_axis_label,
categories ' | ', series_name ' || ', values: ' | ' trong một chuỗi, ' || ' giữa các chuỗi).
Đầu ra: đúng các cấu trúc app.py đang dùng
  flagged_matrix: chart_title, chart_type, unit, categories, series_names, series_data (ô bị cờ = '[chưa chắc chắn]'),
                  has_uncertainty, validation_notes
  desc_dict     : desc_5s, desc_30s, desc_study   (= nghe_5s, nghe_30s, dien_giai của describe.py)
Mô tả giống hệt src/pipeline/run.py, chỉ bỏ dấu chấm nghìn ('1.063,7' -> '1063,7') vì bộ tách số của
vichartfact_metrics đọc '1.063,7' thành hai số '1' và '063,7' (ViChartFact trên demo sẽ báo sai oan).
"""
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (HERE, ROOT / "eval", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from describe import describe  # noqa: E402
from verify import verify  # noqa: E402

UNCERTAIN = "[chưa chắc chắn]"
THOUSANDS = re.compile(r"(?<![\d.,])(\d{1,3})((?:\.\d{3})+)(?![\d.])")
TYPE_FOR_APP = {"bar": "column", "line": "line", "pie": "pie", "area": "area", "combo": "combo"}


def _nfc(s):
    return unicodedata.normalize("NFC", str(s if s is not None else "")).strip()


def _split(s):
    s = _nfc(s)
    if not s:
        return []
    sep = "||" if "||" in s else ("|" if "|" in s else ";")
    return [p.strip() for p in s.split(sep) if p.strip()]


def chart_type_en(t):
    """'cột ghép' / 'column' / 'đường' / 'kết hợp' ... -> loại của verify.py (bar, line, pie, area, combo)."""
    s = _nfc(t).lower()
    for keys, v in ((("kết hợp", "combo"), "combo"), (("miền", "area"), "area"), (("tròn", "pie"), "pie"),
                    (("đường", "line"), "line"), (("cột", "column", "bar"), "bar")):
        if any(k in s for k in keys):
            return v
    return s


def no_thousands(text):
    return THOUSANDS.sub(lambda m: m.group(1) + m.group(2).replace(".", ""), text or "")


def to_raw(step1):
    """Định dạng phẳng -> bảng thô của verify.py (giữ nguyên chuỗi số để luật R1 tự xử lý '1.200' / '1,2')."""
    cats = _split(step1.get("categories"))
    series = _split(step1.get("series_name")) or [None]
    values = _nfc(step1.get("values"))
    points = []
    if "{" in values:   # mô hình trả dict/JSON trong 'values': để vichartfact_metrics bóc số, rồi dùng lại
        import vichartfact_metrics as vm
        _, _, parsed = vm.validate_chart_data(step1)
        for s, vals in parsed["series_data"].items():
            for x, v in zip(parsed["categories"], vals):
                if v is not None:
                    points.append({"series": s, "x": x, "raw": v, "axis": None})
    else:
        chunks = [c for c in values.split("||")] if "||" in values else [values]
        for i, chunk in enumerate(chunks):
            s = series[i] if i < len(series) else f"Chuỗi {i + 1}"
            for x, raw in zip(cats, re.split(r"[|;]", chunk)):
                raw = raw.strip()
                if re.search(r"\d", raw):          # bỏ ô trống, '-', 'nan', 'null', '[chưa chắc chắn]'
                    points.append({"series": s, "x": x, "raw": raw, "axis": None})
    units = [u.strip() for u in re.split(r"[|;]", _nfc(step1.get("unit"))) if u.strip()]
    return {"chart_type": chart_type_en(step1.get("chart_type")), "title": step1.get("chart_title"),
            "x_label": step1.get("x_axis_label"), "unit": units[0] if units else None, "unit_label": None,
            "unit2": units[1] if len(units) > 1 else None, "points": points}


def run_step23(step1):
    t = verify(to_raw(step1))
    lv = describe(t, "omit")
    cell = {(p["series"], p["x"]): p for p in t["points"]}
    series_data = {}
    for s in t["series"]:
        row = []
        for x in t["xs"]:
            p = cell.get((s, x))
            row.append(UNCERTAIN if p is None or p["flags"] else p["y"])
        series_data[s] = row
    point_flags = sorted({f for p in t["points"] for f in p["flags"]})
    notes = t["flags"] + ([f"{t['n_uncertain']} ô gắn cờ chưa chắc chắn ({'; '.join(point_flags)})"]
                          if t["n_uncertain"] else [])
    status = "Hợp lệ" if not notes else "Cần kiểm tra"
    flagged = {"chart_title": t["title"] or _nfc(step1.get("chart_title")),
               "chart_type": TYPE_FOR_APP.get(t["chart_type"], "column"),
               "unit": " | ".join(u for u in (t["unit"], t["unit2"]) if u),
               "categories": list(t["xs"]), "series_names": list(t["series"]), "series_data": series_data,
               "has_uncertainty": bool(notes),
               "validation_notes": "; ".join(notes) if notes else "Đạt các luật kiểm chứng R1–R9"}
    desc = {"desc_5s": no_thousands(lv["nghe_5s"]), "desc_30s": no_thousands(lv["nghe_30s"]),
            "desc_study": no_thousands(lv["dien_giai"])}
    return status, flagged["validation_notes"], flagged, desc
