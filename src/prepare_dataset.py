"""Nhập ảnh biểu đồ từ thư mục Drive (đã tải về) vào data/images + tạo khung nhãn JSON.

  python src/prepare_dataset.py --raw "raw_drive/Ảnh biểu đồ"

Thư mục raw có các thư mục con mang tên chứa: "cột", "đường", "tròn", "kết hợp", "miền".
Script chạy lại bao nhiêu lần cũng được (idempotent):
  - ảnh đã có nhãn (khớp theo source.original_file) -> giữ nguyên id, chỉ chép lại ảnh
  - ảnh mới -> cấp id kế tiếp (bar_075, ...) + tạo file nhãn khung với "status": "todo"
  - KHÔNG BAO GIỜ ghi đè file nhãn đã có
Kết quả: data/images/<id>.<ext>, data/labels/<id>.json, data/manifest.csv
Báo cáo: ảnh trùng nhau, ảnh quá nhỏ (< 800 px cạnh dài).
"""
import argparse
import csv
import hashlib
import re
import json
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
# thứ tự quan trọng: "kết hợp" kiểm tra trước để không nhầm với "cột"/"đường"
TYPE_KEYWORDS = [("kết hợp", "combo"), ("ket hop", "combo"), ("miền", "area"), ("mien", "area"),
                 ("tròn", "pie"), ("tron", "pie"), ("đường", "line"), ("duong", "line"),
                 ("cột", "bar"), ("cot", "bar")]
# Phân công gán nhãn mặc định (~71 ảnh/người). (người, số lượng) theo thứ tự id; None = phần còn lại
ASSIGN = {
    "bar": [("ngan", None)],
    "line": [("nhi", None)],
    "pie": [("nhi", 19), ("giang", None)],
    "combo": [("giang", None)],
    "area": [("giang", None)],
}


def nfc(s):
    return unicodedata.normalize("NFC", s)


def natural_key(s):
    """Hình 2 đứng trước Hình 10."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", nfc(s).lower())]


def folder_type(name):
    n = nfc(name).lower()
    for kw, t in TYPE_KEYWORDS:
        if kw in n:
            return t
    return None


def ahash(img, n=8):
    g = img.convert("L").resize((n, n), Image.BILINEAR)
    px = list(g.tobytes())
    avg = sum(px) / len(px)
    return sum(1 << i for i, p in enumerate(px) if p > avg)


def annotator_for(t, idx):
    k = 0
    for who, cnt in ASSIGN.get(t, [("chua_phan_cong", None)]):
        if cnt is None or idx < k + cnt:
            return who
        k += cnt
    return "chua_phan_cong"


def skeleton(cid, t, img_name, orig, who):
    return {
        "id": cid,
        "image": f"images/{img_name}",
        "status": "todo",
        "source": {"type": None, "book": None, "page": None, "url": None, "original_file": orig},
        "annotator": who,
        "subject": None,
        "chart_type": t,
        "title": "",
        "x_axis": {"label": None, "unit": None},
        "y_axis": {"label": None, "unit": None},
        "legend": [],
        "values_shown_on_chart": None,
        "data": [],
        "notes": "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="thư mục chứa các thư mục con theo loại biểu đồ")
    ap.add_argument("--data", default="data")
    ap.add_argument("--min_side", type=int, default=800)
    args = ap.parse_args()

    raw, data = Path(args.raw), Path(args.data)
    img_dir, lab_dir = data / "images", data / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lab_dir.mkdir(parents=True, exist_ok=True)

    # nhãn đã có -> map original_file -> id
    known, used_nums = {}, defaultdict(set)
    for p in lab_dir.glob("*.json"):
        if p.name.startswith("example_"):
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        orig = (rec.get("source") or {}).get("original_file")
        if orig:
            known[nfc(orig)] = rec["id"]
        t, _, num = rec["id"].rpartition("_")
        if num.isdigit():
            used_nums[t].add(int(num))

    rows, md5s, hashes = [], defaultdict(list), []
    created = Counter()
    skipped_dirs = []
    for sub in sorted(d for d in raw.iterdir() if d.is_dir()):
        t = folder_type(sub.name)
        if t is None:
            skipped_dirs.append(sub.name)
            continue
        files = sorted((f for f in sub.rglob("*") if f.suffix.lower() in IMG_EXT),
                       key=lambda f: natural_key(f.relative_to(sub).as_posix()))
        for f in files:
            orig = nfc(f"{sub.name}/{f.relative_to(sub).as_posix()}")
            if orig in known:
                cid = known[orig]
            else:
                n = 1
                while n in used_nums[t]:
                    n += 1
                used_nums[t].add(n)
                cid = f"{t}_{n:03d}"
            idx = int(cid.rsplit("_", 1)[1]) - 1
            name = f"{cid}{f.suffix.lower()}"
            shutil.copy2(f, img_dir / name)

            lab = lab_dir / f"{cid}.json"
            if not lab.exists():
                rec = skeleton(cid, t, name, orig, annotator_for(t, idx))
                lab.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
                created[t] += 1

            with Image.open(f) as im:
                w, h = im.size
                hashes.append((cid, ahash(im)))
            md5s[hashlib.md5(f.read_bytes()).hexdigest()].append(cid)
            who = json.loads(lab.read_text(encoding="utf-8")).get("annotator")
            rows.append({"id": cid, "chart_type": t, "annotator": who, "width": w, "height": h,
                         "small": int(max(w, h) < args.min_side), "original_file": orig})

    rows.sort(key=lambda r: r["id"])
    with open(data / "manifest.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)

    print(f"Đã nhập {len(rows)} ảnh, tạo mới {sum(created.values())} file nhãn khung.")
    print("Theo loại:", dict(Counter(r["chart_type"] for r in rows)))
    print("Theo người gán:", dict(Counter(r["annotator"] for r in rows)))
    if skipped_dirs:
        print("[BỎ QUA] không nhận ra loại biểu đồ của thư mục:", skipped_dirs)
    dup = [ids for ids in md5s.values() if len(ids) > 1]
    if dup:
        print("[TRÙNG HỆT] ", dup)
    near = [(a, b) for i, (a, ha) in enumerate(hashes) for b, hb in hashes[i + 1:]
            if bin(ha ^ hb).count("1") <= 3 and not any(a in d and b in d for d in dup)]
    if near:
        print(f"[CÓ THỂ TRÙNG] {len(near)} cặp, xem lại bằng mắt:", near[:20])
    small = [r["id"] for r in rows if r["small"]]
    if small:
        print(f"[ẢNH NHỎ < {args.min_side}px] {len(small)} ảnh:", small[:30])
    print(f"Danh sách: {data / 'manifest.csv'}")


if __name__ == "__main__":
    main()
