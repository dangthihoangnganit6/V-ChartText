"""Kiểm tra chéo nhãn (tác vụ 15): mỗi người soát ~20% ảnh do người KHÁC gán.

  python eval/cross_check.py sample      # tạo data/labeling/kiem_tra_cheo.csv (40 ảnh, seed cố định)
  (mỗi người mở file, lọc cột nguoi_soat = tên mình, mở ảnh + file JSON, điền 3 cột cuối)
  python eval/cross_check.py report      # tính tỉ lệ bất đồng -> eval/results/cross_check_summary.csv

Cột cần điền:
  ket_qua      : dat (khớp hoàn toàn) | sua (có chỗ sai)
  so_diem_sai  : số điểm dữ liệu sai (0 nếu đạt)
  loi_khac     : tieu_de / don_vi / chu_giai / truc_x / loai ... (cách nhau bởi dấu cách), có thể để trống
  ghi_chu      : sai ở đâu, giá trị đúng là gì
Sửa nhãn sai trực tiếp trên Google Sheet (tab Data_Labeling) rồi chạy lại src/import_sheet.py --write.
"""
import csv
import math
import json
import random
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

LABELS = Path("data/labels")
OUT = Path("data/labeling/kiem_tra_cheo.csv")
PEOPLE = ["ngan", "nhi", "giang"]
RATE, SEED = 0.22, 2026   # 22% ảnh không trùng ~ 20% của 200 ảnh


def who(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()
    return s if s in PEOPLE else None


def sample():
    if OUT.exists() and "--force" not in sys.argv:
        sys.exit(f"{OUT} đã có (có thể đã điền). Thêm --force để tạo lại.")
    by = defaultdict(list)
    for p in sorted(LABELS.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if p.name.startswith("example_") or r.get("status") in ("todo", "excluded") or r.get("duplicate_of"):
            continue
        labeler = who(r.get("reviewer")) or who(r.get("annotator"))
        by[labeler].append(r)
    rng = random.Random(SEED)
    rows, load = [], defaultdict(int)
    for labeler, recs in sorted(by.items()):
        # phân tầng theo loại biểu đồ trong phần của từng người
        types = defaultdict(list)
        for r in recs:
            types[r["chart_type"]].append(r)
        k = math.ceil(len(recs) * RATE)
        picked = []
        for t, rs in sorted(types.items()):
            rng.shuffle(rs)
            picked += rs[:max(1, math.ceil(len(rs) * RATE))]
        rng.shuffle(picked)
        for r in picked[:k]:
            others = [p for p in PEOPLE if p != labeler]
            rv = min(others, key=lambda p: (load[p], rng.random()))
            load[rv] += 1
            rows.append({"id": r["id"], "anh": f"data/images/{Path(r['image']).name}",
                         "ten_goc": Path(r["source"]["original_file"]).name, "dong_sheet": r.get("sheet_row", ""),
                         "loai": r["chart_type"], "so_diem": len(r["data"]), "nguoi_gan": labeler, "nguoi_soat": rv,
                         "ket_qua": "", "so_diem_sai": "", "loi_khac": "", "ghi_chu": ""})
    rows.sort(key=lambda r: (r["nguoi_soat"], r["id"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Đã tạo {OUT}: {len(rows)} ảnh. Mỗi người soát: {dict(load)}")


def report():
    rows = list(csv.DictReader(open(OUT, encoding="utf-8-sig")))
    done = [r for r in rows if r["ket_qua"].strip()]
    if not done:
        sys.exit("Chưa có dòng nào được điền cột ket_qua.")
    agg = defaultdict(lambda: {"n_anh": 0, "anh_sai": 0, "so_diem": 0, "diem_sai": 0})
    for r in done:
        for key in ("TỔNG", f"gán:{r['nguoi_gan']}", f"loại:{r['loai']}"):
            a = agg[key]
            a["n_anh"] += 1
            a["anh_sai"] += r["ket_qua"].strip().lower() != "dat"
            a["so_diem"] += int(r["so_diem"])
            a["diem_sai"] += int(r["so_diem_sai"] or 0)
    out = [{"nhom": k, **v, "%_anh_bat_dong": round(100 * v["anh_sai"] / v["n_anh"], 1),
            "%_diem_bat_dong": round(100 * v["diem_sai"] / max(1, v["so_diem"]), 2)} for k, v in sorted(agg.items())]
    Path("eval/results").mkdir(parents=True, exist_ok=True)
    with open("eval/results/cross_check_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"Đã soát {len(done)}/{len(rows)} ảnh")
    for o in out:
        print(f"  {o['nhom']:<14} {o['n_anh']:>3} ảnh | bất đồng {o['%_anh_bat_dong']}% ảnh, {o['%_diem_bat_dong']}% điểm")


if __name__ == "__main__":
    {"sample": sample, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "sample"]()
