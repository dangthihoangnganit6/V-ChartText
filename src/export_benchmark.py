"""Xuất docs/Benchmark.xlsx từ nhãn chuẩn data/labels/*.json (một nguồn nhãn duy nhất cho cả repo).

  python src/export_benchmark.py

Giữ ĐÚNG bố cục Benchmark cũ để app.py, evaluate_vichartfact_completeness.py, run_phase3_benchmark_comparison.py
đọc được như trước (không phải sửa code): sheet 'Data_Labeling', dòng 1 = link Drive, dòng 3 = tên cột
STT | image_name | chart_title | chart_type | unit | x_axis_label | categories | series_name | values |
Người kiểm tra | Trạng thái kiểm tra | Vấn đề với model | Ghi chú nhãn.

Khác bản cũ (docs/archive/Benchmark_truoc_soat_22-11.xlsx):
  - giá trị lấy từ nhãn đã soát 24–25/11; bỏ 13 biểu đồ bị loại (status = excluded) -> 200 dòng
  - số thập phân ghi dấu phẩy; số có đúng 3 chữ số thập phân thêm một số 0 ('19,2570'), vì
    clean_vietnamese_number hiểu '19.257' và '19,257' là 19257 (dấu phân cách nghìn)
  - ảnh không có tiêu đề / đơn vị: để trống (bản cũ ghi chữ mẫu 'Thiếu tên biểu đồ', 'không có')
  - 'Ghi chú nhãn' có cờ 'ẢNH KHÔNG GHI SỐ' cho ảnh không in số và 'TRÙNG SỐ LIỆU VỚI <id>'
  - cột 'Người kiểm tra', 'Vấn đề với model' giữ nguyên từ bản cũ (khớp theo image_name)
"""
import argparse
import csv
import json
import unicodedata
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

ROOT = Path(__file__).resolve().parents[1]
HEADER = ["STT", "image_name", "chart_title", "chart_type", "unit", "x_axis_label", "categories", "series_name",
          "values", "Người kiểm tra", "Trạng thái kiểm tra", "Vấn đề với model", "Ghi chú nhãn"]
DRIVE = "https://drive.google.com/drive/folders/15aZg7BMKpSu5yffvsls9AQFF6Hj2VtcV?hl=vi"
TYPE_ORDER = {"line": 0, "pie": 1, "bar": 2, "area": 3, "combo": 4}


def nfc(s):
    return unicodedata.normalize("NFC", str(s if s is not None else "")).strip()


def vn_num(v):
    """1063.7 -> '1063,7'; 19.257 -> '19,2570' (tránh bị đọc thành 19257); 1200 -> '1200'."""
    f = float(v)
    if f == int(f):
        return str(int(f))
    ip, dp = f"{f:.4f}".rstrip("0").split(".")
    if len(dp) == 3:
        dp += "0"
    return f"{ip},{dp}"


def chart_type_vn(rec):
    t = rec["chart_type"]
    if t == "bar":
        return {"grouped": "cột ghép", "stacked": "cột chồng"}.get(rec.get("bar_mode"), "cột")
    return t


def to_row(rec):
    xs = list(dict.fromkeys(nfc(d["x"]) for d in rec["data"]))
    ss = list(dict.fromkeys(nfc(d["series"]) for d in rec["data"]))
    cell = {(nfc(d["series"]), nfc(d["x"])): d["y"] for d in rec["data"]}
    values = " || ".join(" | ".join(vn_num(cell[(s, x)]) if (s, x) in cell else "-" for x in xs) for s in ss)
    u1 = nfc((rec.get("y_axis") or {}).get("unit"))
    u2 = nfc((rec.get("y2_axis") or {}).get("unit"))
    notes = []
    if rec.get("values_shown_on_chart") is False:
        notes.append("ẢNH KHÔNG GHI SỐ: giá trị ước lượng theo vạch trục")
    if rec.get("duplicate_of"):
        notes.append(f"TRÙNG SỐ LIỆU VỚI {rec['duplicate_of']}")
    extra = nfc(rec.get("notes"))
    if extra and "KHÔNG GHI SỐ" not in extra.upper():
        notes.append(extra)
    return {"chart_title": nfc(rec.get("title")), "chart_type": chart_type_vn(rec),
            "unit": " | ".join(u for u in (u1, u2) if u), "x_axis_label": nfc((rec.get("x_axis") or {}).get("label")),
            "categories": " | ".join(xs), "series_name": " | ".join(ss), "values": values,
            "Ghi chú nhãn": "; ".join(notes)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(ROOT / "data/labels"))
    ap.add_argument("--manifest", default=str(ROOT / "data/manifest.csv"))
    ap.add_argument("--old", default=str(ROOT / "docs/archive/Benchmark_truoc_soat_22-11.xlsx"))
    ap.add_argument("--out", default=str(ROOT / "docs/Benchmark.xlsx"))
    a = ap.parse_args()

    names = {r["id"]: nfc(r["original_file"]).split("/")[-1]
             for r in csv.DictReader(open(a.manifest, encoding="utf-8-sig"))}
    old = {}
    if Path(a.old).exists():
        ws = openpyxl.load_workbook(a.old, read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        ix = {nfc(h): i for i, h in enumerate(rows[2]) if h}
        for r in rows[3:]:
            if r[ix["image_name"]]:
                old[nfc(r[ix["image_name"]])] = {k: r[ix[k]] for k in ("Người kiểm tra", "Vấn đề với model")}

    recs = []
    for p in sorted(Path(a.labels).glob("*.json")):
        if p.name.startswith("example_"):
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec.get("status") in ("todo", "excluded") or not rec.get("data"):
            continue
        recs.append(rec)
    recs.sort(key=lambda r: (TYPE_ORDER.get(r["chart_type"], 9), r["id"]))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data_Labeling"
    ws["A1"] = DRIVE
    ws["A2"] = ("Xuất từ data/labels/*.json bằng src/export_benchmark.py (nhãn đã soát 24–25/11). "
                "Không sửa tay file này: sửa JSON rồi chạy lại script.")
    ws.append(HEADER)
    for c in ws[3]:
        c.font = Font(bold=True)
    for i, rec in enumerate(recs, 1):
        name = names.get(rec["id"]) or nfc(rec["source"]["original_file"]).split("/")[-1]
        row = to_row(rec)
        o = old.get(name, {})
        ws.append([i, name, row["chart_title"], row["chart_type"], row["unit"], row["x_axis_label"], row["categories"],
                   row["series_name"], row["values"], o.get("Người kiểm tra") or rec.get("reviewer") or rec.get("annotator"),
                   "đã soát 24–25/11", o.get("Vấn đề với model"), row["Ghi chú nhãn"]])
    ws.freeze_panes = "A4"
    for col, w in zip("ABCDEFGHIJKLM", (6, 26, 48, 11, 16, 16, 40, 30, 50, 12, 16, 30, 40)):
        ws.column_dimensions[col].width = w
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    wb.save(a.out)
    print(f"{len(recs)} biểu đồ -> {a.out}")


if __name__ == "__main__":
    main()
