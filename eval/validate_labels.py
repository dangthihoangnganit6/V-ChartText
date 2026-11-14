"""Kiểm tra file nhãn trước khi ghép dataset (dùng cho mục 15-16).

  python eval/validate_labels.py            # kiểm tra data/labels/*.json
  -> báo lỗi từng file + thống kê phân bố (loại biểu đồ, môn, người gán, nguồn)
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vn_number import parse_vn  # noqa: E402

REQ = ["id", "image", "source", "annotator", "subject", "chart_type", "title", "x_axis", "y_axis", "legend", "data"]
TYPES = {"bar", "line", "pie", "combo", "area", "other"}
SUBJECTS = {"dia_li", "lich_su", "khac"}


def check(rec, path, img_root):
    errs = []
    for k in REQ:
        if k not in rec:
            errs.append(f"thiếu trường '{k}'")
    if errs:
        return errs
    if path.stem != rec["id"]:
        errs.append(f"tên file ({path.stem}) khác id ({rec['id']})")
    if rec["chart_type"] not in TYPES:
        errs.append(f"chart_type '{rec['chart_type']}' không thuộc {sorted(TYPES)}")
    if rec["subject"] not in SUBJECTS:
        errs.append(f"subject '{rec['subject']}' không thuộc {sorted(SUBJECTS)}")
    if not (Path(img_root) / Path(rec["image"]).name).exists():
        errs.append("không thấy file ảnh")
    if not rec["data"]:
        errs.append("data rỗng")
    series = set()
    for i, d in enumerate(rec["data"]):
        for k in ("series", "x", "y"):
            if k not in d:
                errs.append(f"data[{i}] thiếu '{k}'")
        series.add(d.get("series"))
        if "y_raw" in d and "y" in d:
            try:
                if abs(parse_vn(d["y_raw"]) - float(d["y"])) > 1e-6:
                    errs.append(f"data[{i}]: y={d['y']} không khớp y_raw='{d['y_raw']}' (quy ước VN)")
            except ValueError:
                errs.append(f"data[{i}]: y_raw='{d['y_raw']}' không đọc được")
    legend = set(rec["legend"] or [])
    if legend and series - legend:
        errs.append(f"series không có trong legend: {series - legend}")
    if rec["chart_type"] == "pie":
        tot = sum(float(d["y"]) for d in rec["data"] if "y" in d)
        if (rec["y_axis"] or {}).get("unit") == "%" and abs(tot - 100) > 1.5:
            errs.append(f"biểu đồ tròn: tổng {tot} khác 100%")
    return errs


def main(label_dir="data/labels", img_root="data/images"):
    files = [p for p in sorted(Path(label_dir).glob("*.json")) if not p.name.startswith("example_")]
    bad, recs, todo, excluded = 0, [], [], []
    for p in files:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[LỖI] {p.name}: JSON hỏng ({e})")
            bad += 1
            continue
        if rec.get("status") == "excluded":
            excluded.append(rec["id"])
            continue
        if rec.get("status") == "todo":
            todo.append(rec)
            recs.append(rec)
            continue
        errs = check(rec, p, img_root)
        if errs:
            bad += 1
            for e in errs:
                print(f"[LỖI] {p.name}: {e}")
        recs.append(rec)
    n_done = len(files) - len(todo) - len(excluded)
    print(f"\n{len(files)} file: {n_done} đã gán ({bad} có lỗi), {len(todo)} chưa gán (status=todo), "
          f"{len(excluded)} bị loại (status=excluded)")
    if excluded:
        print("Bị loại:", ", ".join(excluded))
    if todo:
        print("Chưa gán theo người:", dict(Counter(r.get("annotator") for r in todo)))
    for key in ("chart_type", "subject", "annotator"):
        print(key, dict(Counter(r.get(key) for r in recs)))
    print("source.type", dict(Counter((r.get("source") or {}).get("type") for r in recs)))
    print("số điểm dữ liệu:", sum(len(r.get("data") or []) for r in recs))


if __name__ == "__main__":
    main(*sys.argv[1:])
