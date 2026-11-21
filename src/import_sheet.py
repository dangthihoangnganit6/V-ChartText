"""Nhập nhãn từ Google Sheet "Data_Labeling" vào data/labels/*.json.

Cách dùng:
  1. Google Sheet -> mở tab Data_Labeling -> Tệp > Tải xuống > CSV
     rồi lưu thành data/labeling/sheet/Data_Labeling.csv  (ghi đè bản cũ)
  2. python src/import_sheet.py                 # chạy thử: chỉ báo cáo, KHÔNG ghi file
     python src/import_sheet.py --write         # ghi data/labels/*.json
  3. python eval/validate_labels.py

Quy tắc:
  - Ghép dòng Sheet với id qua tên file gốc (cột image_name == tên file trong manifest.csv / original_file).
  - Chỉ nhập dòng "đã kiểm tra". Dòng khác giữ nguyên status=todo.
  - KHÔNG ghi đè nhãn gán tay (file JSON không có status "todo" và không có label_source "sheet...").
    Thêm --force nếu thật sự muốn ghi đè.
  - Cột "Ghi chú nhãn" (M) có "LOẠI KHỎI BENCHMARK" hoặc ô values không có số -> status = excluded.
  - Cột M có "ẢNH KHÔNG GHI SỐ" -> values_shown_on_chart = false (giá trị là ước lượng).
  - values: " | " ngăn các điểm trong một chuỗi, " || " ngăn các chuỗi (theo thứ tự series_name).
    Số trong Sheet viết dấu chấm thập phân, không có dấu phân cách nghìn (12.5, 4296).
  - unit dạng "A | B" (biểu đồ hai trục) -> y_axis.unit = A, y2_axis.unit = B.
  - "cột" / "cột ghép" / "cột chồng" -> chart_type bar, bar_mode single / grouped / stacked.
  - Hai ảnh có cùng bảng số liệu -> ảnh sau có "duplicate_of": <id ảnh đầu>.
"""
import argparse
import csv
import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

LABELS = Path("data/labels")
MANIFEST = Path("data/manifest.csv")
DEFAULT_CSV = Path("data/labeling/sheet/Data_Labeling.csv")

TYPE_MAP = {"line": ("line", None), "pie": ("pie", None), "combo": ("combo", None), "area": ("area", None),
            "bar": ("bar", "single"), "column": ("bar", "single"), "cột": ("bar", "single"),
            "cột đơn": ("bar", "single"), "cột ghép": ("bar", "grouped"), "cột chồng": ("bar", "stacked")}
NONE_WORDS = {"", "không có", "thiếu dữ liệu", "none", "null", "-"}
NO_TITLE = {"thiếu tên biểu đồ", "biểu đồ không có tên", "không có tên"}
EXCLUDE_MARK = "LOẠI KHỎI BENCHMARK"
ESTIMATE_MARK = "ẢNH KHÔNG GHI SỐ"
CHECKED = "đã kiểm tra"
# Từ khoá để đoán môn "khac" (biểu đồ không thuộc Địa lí / Lịch sử). Chỉ là gợi ý: subject_guessed = true.
KHAC_WORDS = ["học sinh", "lớp 6", "đại biểu", "học viên", "clb", "áo sơ mi", "con vật", "trái cây", "điểm của",
              "điểm kiểm tra", "marketing", "bán hàng", "ngành a", "khán giả", "quán", "giá vàng", "bạc miếng",
              "tỷ giá", "lãi suất", "cpi", "thiết bị", "khóa học", "natri", "nguyên tố", "chiều cao", "nobel",
              "nước uống", "scotland", "liên hệ", "máy bán", "tìm việc", "nhóm nghề", "bán lẻ tại canada",
              "tổng tài sản", "quãng đường", "tai nạn", "tăng trưởng của ngành công nghiệp"]


def nfc(s):
    return unicodedata.normalize("NFC", str(s or "")).strip()


def clean(s):
    s = re.sub(r"\s+", " ", nfc(s))
    return None if s.lower() in NONE_WORDS else s


def split_bar(s):
    return [x.strip() for x in nfc(s).split("|") if x.strip()]


def parse_num(tok):
    t = tok.strip().replace("−", "-").replace(" ", "")
    if "," in t and "." not in t:
        t = t.replace(",", ".")
    return float(t)


def vn_raw(tok):
    """Chuỗi số theo quy ước VN (dấu phẩy thập phân) để khớp y_raw / parse_vn."""
    return tok.strip().replace("−", "-").replace(" ", "").replace(".", ",")


def parse_values(s):
    """-> list các chuỗi, mỗi chuỗi là list token số. Lỗi -> ValueError."""
    s = nfc(s).replace("\r", " ").replace("\n", " ")
    groups = [g for g in s.split("||")]
    out = []
    for g in groups:
        toks = [t.strip() for t in g.split("|") if t.strip()]
        for t in toks:
            parse_num(t)
        out.append(toks)
    return out


def read_sheet(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    hi = next(i for i, r in enumerate(rows) if "image_name" in r)
    head = rows[hi]
    col = {name: head.index(name) for name in head if name}
    get = lambda r, k: r[col[k]] if k in col and col[k] < len(r) else ""
    out = []
    for i, r in enumerate(rows[hi + 1:], start=hi + 2):   # số dòng như trên Google Sheet
        if not get(r, "image_name").strip():
            continue
        out.append({
            "sheet_row": i, "image_name": nfc(get(r, "image_name")), "title": get(r, "chart_title"),
            "type": get(r, "chart_type"), "unit": get(r, "unit"), "x_label": get(r, "x_axis_label"),
            "categories": get(r, "categories"), "series": get(r, "series_name"), "values": get(r, "values"),
            "reviewer": get(r, "Người kiểm tra"), "status": get(r, "Trạng thái kiểm tra"),
            "model_issue": get(r, "Vấn đề với model"), "note": get(r, "Ghi chú nhãn"),
        })
    return out


def build(row, base):
    """-> (record, lỗi). record là nhãn JSON hoàn chỉnh."""
    note = nfc(row["note"])
    ctype_raw = nfc(row["type"]).lower()
    if ctype_raw not in TYPE_MAP:
        return None, f"chart_type '{row['type']}' không nhận ra"
    ctype, bar_mode = TYPE_MAP[ctype_raw]
    title = clean(row["title"]) or ""
    if title.lower() in NO_TITLE:
        title = ""
    units = [clean(u) for u in nfc(row["unit"]).split("|")] if "|" in row["unit"] else [clean(row["unit"])]
    cats = split_bar(row["categories"])
    series = split_bar(row["series"]) or [None]

    rec = {k: base.get(k) for k in ("id", "image", "source", "annotator", "subject")}
    rec.update({
        "status": "done", "label_source": "sheet:Data_Labeling", "sheet_row": row["sheet_row"],
        "chart_type": ctype, "title": title,
        "x_axis": {"label": clean(row["x_label"]), "unit": None},
        "y_axis": {"label": None, "unit": units[0]},
        "legend": [], "values_shown_on_chart": ESTIMATE_MARK not in note.upper(), "data": [],
        "reviewer": clean(row["reviewer"]), "notes": note,
    })
    if bar_mode:
        rec["bar_mode"] = bar_mode
    if len(units) > 1:
        rec["y2_axis"] = {"label": None, "unit": units[1]}

    if EXCLUDE_MARK in note.upper():
        rec.update(status="excluded", exclude_reason=note)
        return rec, None
    if not re.search(r"\d", row["values"]):
        rec.update(status="excluded", exclude_reason=f"ô values không có số: '{nfc(row['values'])[:40]}'")
        return rec, None
    try:
        groups = parse_values(row["values"])
    except ValueError as e:
        return None, f"values có token không phải số ({e})"
    if len(groups) != len(series):
        return None, f"{len(groups)} nhóm giá trị (ngăn bởi ||) nhưng {len(series)} series"
    for s, g in zip(series, groups):
        if len(g) != len(cats):
            return None, f"series '{s}': {len(g)} giá trị nhưng {len(cats)} categories"
    single = len(series) == 1
    sname = series[0] or title or "Giá trị"
    for s, g in zip(series, groups):
        for x, tok in zip(cats, g):
            rec["data"].append({"series": sname if single else s, "x": x, "y": parse_num(tok), "y_raw": vn_raw(tok)})
    rec["legend"] = [] if single else series
    if rec["subject"] not in ("dia_li", "lich_su", "khac"):
        text = (title + " " + " ".join(cats) + " " + " ".join(s or "" for s in series)).lower()
        rec["subject"] = "khac" if any(w in text for w in KHAC_WORDS) else "dia_li"
        rec["subject_guessed"] = True
    return rec, None


def fingerprint(rec):
    return tuple(round(d["y"], 6) for d in rec["data"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default=str(DEFAULT_CSV))
    ap.add_argument("--write", action="store_true", help="ghi file JSON (mặc định chỉ chạy thử)")
    ap.add_argument("--force", action="store_true", help="ghi đè cả nhãn gán tay")
    a = ap.parse_args()

    with open(MANIFEST, encoding="utf-8-sig") as f:
        by_name = {nfc(Path(r["original_file"]).name): r["id"] for r in csv.DictReader(f)}
    rows = read_sheet(a.csv)
    stats = {"nhap": 0, "loai": 0, "giu_nhan_tay": 0, "chua_kiem_tra": 0, "loi": 0, "khong_ghep": 0}
    errors, recs, seen_ids = [], {}, {}
    for row in rows:
        id_ = by_name.get(row["image_name"])
        if not id_:
            stats["khong_ghep"] += 1
            errors.append(f"dòng {row['sheet_row']} {row['image_name']}: không có trong manifest.csv")
            continue
        if id_ in seen_ids:
            errors.append(f"dòng {row['sheet_row']} {row['image_name']}: trùng với dòng {seen_ids[id_]}")
            stats["loi"] += 1
            continue
        seen_ids[id_] = row["sheet_row"]
        p = LABELS / f"{id_}.json"
        if not p.exists():
            errors.append(f"dòng {row['sheet_row']} {row['image_name']} ({id_}): không có file {p}, bỏ qua")
            stats["khong_ghep"] += 1
            continue
        base = json.loads(p.read_text(encoding="utf-8"))
        hand = base.get("status") != "todo" and not str(base.get("label_source", "")).startswith("sheet")
        if hand and not a.force:
            stats["giu_nhan_tay"] += 1
            continue
        if nfc(row["status"]).lower() != CHECKED:
            stats["chua_kiem_tra"] += 1
            errors.append(f"dòng {row['sheet_row']} {row['image_name']} ({id_}): trạng thái '{row['status']}', chưa nhập")
            continue
        rec, err = build(row, base)
        if err:
            stats["loi"] += 1
            errors.append(f"dòng {row['sheet_row']} {row['image_name']} ({id_}): {err}")
            continue
        recs[id_] = rec
        stats["loai" if rec["status"] == "excluded" else "nhap"] += 1

    # ảnh trùng số liệu (tính cả nhãn gán tay)
    pool = {}
    for p in sorted(LABELS.glob("*.json")):
        if p.name.startswith("example_"):
            continue
        r = recs.get(p.stem) or json.loads(p.read_text(encoding="utf-8"))
        if r.get("status") in ("todo", "excluded") or not r.get("data"):
            continue
        r.pop("duplicate_of", None)
        fp = fingerprint(r)
        if len(fp) >= 3 and fp in pool:
            if p.stem in recs:
                recs[p.stem]["duplicate_of"] = pool[fp]
        else:
            pool.setdefault(fp, p.stem)
    dups = {k: v["duplicate_of"] for k, v in recs.items() if v.get("duplicate_of")}

    print(f"Sheet: {len(rows)} dòng | {stats}")
    print(f"Ảnh trùng số liệu ({len(dups)}): " + ", ".join(f"{k}={v}" for k, v in sorted(dups.items())))
    est = sorted(k for k, v in recs.items() if v["status"] == "done" and not v["values_shown_on_chart"])
    print(f"Ảnh không ghi số ({len(est)}): {', '.join(est)}")
    print(f"Môn đoán tự động: khac = {sorted(k for k, v in recs.items() if v.get('subject_guessed') and v['subject'] == 'khac')}")
    if errors:
        print(f"\n{len(errors)} vấn đề cần sửa trên Sheet:")
        for e in errors:
            print("  -", e)

    if not a.write:
        print("\n(Chạy thử, chưa ghi gì. Thêm --write để ghi data/labels/*.json)")
        return
    stamp = dt.date.today().isoformat()
    for id_, rec in recs.items():
        rec["imported_at"] = stamp
        (LABELS / f"{id_}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nĐã ghi {len(recs)} file vào {LABELS}/")


if __name__ == "__main__":
    main()
