"""Bảng tần suất lỗi thường gặp (tác vụ 20) cho báo cáo Mức 1.

Chạy SAU score_extract.py, check_describe.py:
  python eval/error_stats.py [data/labeling/sheet/Data_Labeling.csv]
-> eval/results/error_frequency.csv        lỗi đo TỰ ĐỘNG trên outputs/*__extract__* và *__describe__*
                                            (số biểu đồ mắc lỗi / số biểu đồ có thể mắc lỗi đó)
-> eval/results/error_examples.csv         id ví dụ của từng lỗi, để chọn minh hoạ cho báo cáo
-> eval/results/error_manual_notes.csv     nhận xét tay của nhóm (cột "Vấn đề với model" trên Sheet)
                                            được xếp vào cùng nhóm lỗi bằng từ khoá

Lưu ý: cột "Vấn đề với model" nhận xét output trong tab Data_Labeling_AI (notebook ChartToText, prompt mẫu có
"123.4 | 567.8"), KHÔNG phải output prompt v1 trong outputs/. Hai bảng bổ sung cho nhau, đừng cộng gộp.
"""
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from score_extract import load_labels, norm, norm_unit, norm_x, pred_points, read_pred  # noqa: E402

RES = Path("eval/results")
OUT = Path("outputs")

# (mã, mô tả) theo thứ tự in trong báo cáo
CODES = [
    ("L1_sai_loai_bieu_do", "Gán sai loại biểu đồ (vd combo/area -> bar)"),
    ("L2_thieu_chuoi", "Biểu đồ nhiều chuỗi: lấy được < một nửa số chuỗi (thường chỉ 1 chuỗi)"),
    ("L3_thieu_diem", "Thiếu >= 30% điểm dữ liệu so với nhãn"),
    ("L4_sai_gia_tri", ">= 1 điểm lệch > 5% (E2)"),
    ("L5_bac_so", "Đọc sai dấu chấm/phẩy -> lệch đúng 10/100/1000 lần (E1)"),
    ("L6_sai_don_vi", "Sai hoặc thiếu đơn vị trục y (chấm nới)"),
    ("L7_bia_tieu_de", "Ảnh không có tiêu đề nhưng mô hình tự đặt tiêu đề"),
    ("L8_sai_tieu_de", "Ảnh có tiêu đề nhưng chép sai (độ giống < 0.8)"),
    ("L9_json_hong", "Output extract không phải JSON hợp lệ (kể cả cứu được)"),
    ("L10_lap", "Lặp một điểm/cụm >= 5 lần"),
    ("L11_cham_gioi_han", "Chạm giới hạn max_new_tokens"),
    ("D1_so_khong_khop", "Mô tả: có >= 1 con số không khớp số liệu (bịa/đọc sai)"),
    ("D2_so_sai_dinh_dang", "Mô tả: có số lệch bậc 10/100/1000 (đọc nhầm 1.200 / 12,5)"),
    ("D3_thieu_don_vi", "Mô tả: không nhắc đơn vị của trục y"),
    ("D4_chen_tieng_anh", "Mô tả: chen từ tiếng Anh"),
    ("D5_khong_co_so", "Mô tả: không nêu con số nào"),
]

# từ khoá -> nhóm lỗi, cho nhận xét tay của nhóm
MANUAL_RULES = [
    ("L1_sai_loai_bieu_do", ["sai loại biểu đồ", "column thay vì", "gán loại"]),
    ("L2_thieu_chuoi", ["không phân tích ra hết", "chỉ lấy chuỗi", "chỉ lấy 1", "chỉ phân tích 1", "thiếu 2 thành phần",
                        "thiếu 3 thành phần", "thiếu 1 thành phần", "k đọc đc cột ghép", "k đọc được cột ghép",
                        "không đọc được các giá trị từng phần", "không tách được", "chưa tách bạch", "gộp 2 hình",
                        "bỏ đường", "bỏ cột", "bỏ 2 chuỗi", "bỏ toàn bộ"]),
    ("L3_thieu_diem", ["thiếu giá trị", "thiếu values", "thiếu 4 giá trị", "thiếu 6 giá trị", "thiếu 10 giá trị",
                       "thiếu phần lớn", "chỉ ra 3 số", "chỉ có 2 số", "chỉ lấy 2 số", "chỉ lấy 3", "thiếu 1 tháng"]),
    ("L4_sai_gia_tri", ["sai số liệu", "sai giá trị", "values hơi lệch", "đọc lệch", "giá trị từng phần không khớp",
                        "không khớp giá trị", "đọc số liệu sai", "thứ tự giá trị ngược", "sai hết"]),
    ("L5_bac_so", ["bậc số", "dấu phẩy thập phân", "ngăn cách hàng nghìn", "ngăn cách dấu ,"]),
    ("L6_sai_don_vi", ["sai đơn vị", "đơn vị", "chỉ đọc được \"km\""]),
    ("L7_bia_tieu_de", ["bịa title", "bịa tiêu", "tự bịa", "model bịa"]),
    ("L8_sai_tieu_de", ["sai title", "sai tiêu đề", "title chung chung", "title sai", "sai chính tả title",
                        "sai chính tả tên biểu đồ", "trích xuất sai title"]),
    ("M1_chep_mau_prompt", ["123.4", "mẫu prompt", "placeholder", "1234 | 5678"]),
    ("M2_sai_chinh_ta", ["chính tả", "mất dấu", "sai dấu"]),
    ("M3_bia_du_lieu", ["bịa dữ", "bịa cả", "tự đẻ", "bịa categories", "bịa chú giải", "bịa thêm"]),
    ("M4_khong_doc_duoc", ["không đọc được gì", "không đọc được biểu đồ", "không đọc được dữ liệu",
                           "không trích xuất được gì", "không p-hân tích", "lỗi không đọc", "không phân tích được"]),
    ("D4_chen_tieng_anh", ["tiếng anh", "tiếng anh"]),
    ("M5_nham_truc", ["nhầm giá trị trục hoành", "categories là", "không đọc được trục x", "x_axis"]),
    ("M6_dung", ["ai đọc đúng", "đúng"]),
]


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def nfc(s):
    return unicodedata.normalize("NFC", str(s or "")).strip()


def model_of(p):
    """'Qwen..__extract__v2' -> 'Qwen..@v2' (prompt v1 giữ tên cũ)."""
    parts = Path(p).stem.split("__")
    return parts[0] + (f"@{parts[2]}" if len(parts) > 2 and parts[2] != "v1" else "")


def extract_errors(path, done):
    """-> {code: (n_mắc, n_áp_dụng, [ids])}"""
    pts = defaultdict(list)
    pfile = RES / f"{Path(path).stem}__points.csv"
    for r in read_csv(pfile):
        pts[r["id"]].append(r)
    charts = {r["id"]: r for r in read_csv(RES / f"{Path(path).stem}__charts.csv")}
    allr = {r["id"]: r for r in read_csv(RES / f"{Path(path).stem}__all.csv")}
    res = {c: [0, 0, []] for c, _ in CODES if c.startswith("L")}

    def hit(code, applies, cond, id_):
        if not applies:
            return
        res[code][1] += 1
        if cond:
            res[code][0] += 1
            res[code][2].append(id_)

    for o in (json.loads(l) for l in open(path, encoding="utf-8") if l.strip()):
        id_ = o["id"]
        if id_ not in allr:
            continue
        a = allr[id_]
        hit("L9_json_hong", True, a["json_status"] != "ok", id_)
        hit("L10_lap", True, a["loop"] == "1", id_)
        hit("L11_cham_gioi_han", True, a["hit_limit"] == "1", id_)
        gt = done.get(id_)
        if not gt:
            continue
        pred, status = read_pred(o["output"])
        parsed = pred is not None
        hit("L1_sai_loai_bieu_do", parsed, parsed and norm(pred.get("chart_type")) != gt["chart_type"], id_)
        gser = {norm_x(d["series"]) for d in gt["data"]}
        if len(gser) > 1 and parsed:
            pser = {norm_x(p["series"]) for p in pred_points(pred)} | {norm_x(p["x"]) for p in pred_points(pred)}
            got = sum(any(SequenceMatcher(None, g, p).ratio() >= 0.6 for p in pser if p) for g in gser)
            hit("L2_thieu_chuoi", True, got < len(gser) / 2, id_)
        rows = pts.get(id_, [])
        if rows and parsed:
            miss = sum(r["err_lenient"].startswith(("E8", "E0b")) for r in rows) / len(rows)
            hit("L3_thieu_diem", True, miss >= 0.3, id_)
            shown = gt.get("values_shown_on_chart") is not False
            hit("L4_sai_gia_tri", shown, any(r["err_lenient"].startswith("E2") for r in rows), id_)
            hit("L5_bac_so", shown, any(r["err_lenient"].startswith("E1") for r in rows), id_)
        c = charts.get(id_)
        if c and c.get("unit_ok_lenient") not in ("", None):
            hit("L6_sai_don_vi", parsed, c["unit_ok_lenient"] in ("0", "0.0"), id_)
        if status == "ok":   # bản cứu JSON không có trường title
            pt = norm(pred.get("title"))
            if not gt.get("title"):
                hit("L7_bia_tieu_de", True, bool(pt), id_)
            else:
                hit("L8_sai_tieu_de", True, SequenceMatcher(None, pt, norm(gt["title"])).ratio() < 0.8, id_)
    return res


def describe_errors(path, done):
    stem = Path(path).stem
    summ = {r["id"]: r for r in read_csv(RES / f"{stem}__desc_summary.csv")}
    allr = {r["id"]: r for r in read_csv(RES / f"{stem}__desc_all.csv")}
    res = {c: [0, 0, []] for c, _ in CODES if c.startswith("D")}

    def hit(code, cond, id_):
        res[code][1] += 1
        if cond:
            res[code][0] += 1
            res[code][2].append(id_)

    for id_, a in allr.items():
        hit("D4_chen_tieng_anh", a["chen_tieng_anh"] == "1", id_)
        hit("D5_khong_co_so", a["n_numbers_all"] == "0", id_)
    for id_, s in summ.items():
        hit("D1_so_khong_khop", int(s["chua_khop"]) > 0, id_)
        hit("D2_so_sai_dinh_dang", int(s["E1_dinh_dang"]) > 0, id_)
        if (done.get(id_, {}).get("y_axis") or {}).get("unit"):
            hit("D3_thieu_don_vi", s["E3_thieu_don_vi"] == "1", id_)
    return res


def manual_notes(sheet):
    with open(sheet, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    hi = next(i for i, r in enumerate(rows) if "image_name" in r)
    h = rows[hi]
    ci, cn, ct = h.index("image_name"), h.index("Vấn đề với model"), h.index("chart_type")
    out, cnt, n = [], Counter(), 0
    for r in rows[hi + 1:]:
        if len(r) <= cn or not nfc(r[cn]):
            continue
        n += 1
        txt = nfc(r[cn]).lower()
        cats = [c for c, kws in MANUAL_RULES if any(k in txt for k in kws)]
        if "M6_dung" in cats and len(cats) > 1:
            cats.remove("M6_dung")
        cats = cats or ["M9_khac"]
        cnt.update(cats)
        out.append({"image_name": r[ci], "chart_type": r[ct], "nhan_xet": nfc(r[cn]), "nhom_loi": " ".join(cats)})
    return out, cnt, n


def write(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main(sheet="data/labeling/sheet/Data_Labeling.csv"):
    _, done = load_labels()
    table = defaultdict(dict)
    examples = []
    for p in sorted(OUT.glob("*__extract__*.jsonl")):
        for code, (k, n, ids) in extract_errors(p, done).items():
            table[code][model_of(p)] = (k, n)
            examples.append({"model": model_of(p), "ma_loi": code, "n": k, "vi_du": " ".join(ids[:8])})
    for p in sorted(OUT.glob("*__describe__*.jsonl")):
        for code, (k, n, ids) in describe_errors(p, done).items():
            table[code][model_of(p)] = (k, n)
            examples.append({"model": model_of(p), "ma_loi": code, "n": k, "vi_du": " ".join(ids[:8])})
    models = sorted({m for v in table.values() for m in v})
    rows = []
    for code, desc in CODES:
        row = {"ma_loi": code, "mo_ta": desc}
        for m in models:
            k, n = table[code].get(m, (0, 0))
            row[f"{m}_so_bd"] = k
            row[f"{m}_%"] = round(100 * k / n, 1) if n else None
            row[f"{m}_tren"] = n
        rows.append(row)
    RES.mkdir(parents=True, exist_ok=True)
    write(RES / "error_frequency.csv", rows)
    write(RES / "error_examples.csv", examples)

    print("### Tần suất lỗi tự động (số biểu đồ mắc lỗi / số biểu đồ áp dụng)\n")
    print("| Mã | Lỗi | " + " | ".join(models) + " |")
    print("|---|---|" + "---|" * len(models))
    for r in rows:
        cells = [f"{r[m + '_so_bd']}/{r[m + '_tren']} ({r[m + '_%']}%)" for m in models]
        print(f"| {r['ma_loi'].split('_')[0]} | {r['mo_ta']} | " + " | ".join(cells) + " |")

    if Path(sheet).exists():
        notes, cnt, n = manual_notes(sheet)
        write(RES / "error_manual_notes.csv", notes)
        print(f"\n### Nhận xét tay của nhóm (tab Data_Labeling_AI), {n} ảnh có nhận xét\n")
        print("| Nhóm lỗi | Số ảnh | % |\n|---|---|---|")
        for c, k in cnt.most_common():
            print(f"| {c} | {k} | {round(100 * k / n, 1)} |")


if __name__ == "__main__":
    main(*sys.argv[1:])
