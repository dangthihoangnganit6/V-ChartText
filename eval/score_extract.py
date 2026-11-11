"""Chấm kết quả prompt 'extract' (chart-to-table) so với nhãn.

  python eval/score_extract.py outputs/Qwen3-VL-2B-Instruct__extract__v1.jsonl
  -> eval/results/<tên>__points.csv   (từng điểm dữ liệu, có mã lỗi tự động)
  -> eval/results/<tên>__charts.csv   (từng biểu đồ)
  -> in bảng tổng hợp theo loại biểu đồ

Chỉ số:
  RA@5%   : tỉ lệ điểm dữ liệu có sai số tương đối <= 5% (relaxed accuracy, như ChartQA/UniChart)
  RNSS    : Relative Number Set Similarity (ChartQA), khớp tập số bằng bài toán gán tối ưu
  field_* : đúng loại biểu đồ / đơn vị trục y / chú giải
"""
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).parent))
from vn_number import is_scale_error, parse_pred, rel_err  # noqa: E402

LABEL_DIR = Path("data/labels")


def norm(s):
    s = unicodedata.normalize("NFC", str(s or "")).lower().strip()
    return re.sub(r"\s+", " ", s)


def norm_unit(s):
    """Chuẩn hoá đơn vị để so khớp chính xác: 'Nghìn km' == 'nghìn km', 'tỷ đồng' == 'tỉ đồng',
    '(%)' == '%'. KHÔNG so khớp chuỗi con, vì 'km' khác 'nghìn km' (lệch 1000 lần)."""
    s = norm(s).replace("tỷ", "tỉ").replace("ngàn", "nghìn")
    return re.sub(r"[()\[\]\s]+", " ", s).strip()


def parse_json(text):
    text = re.sub(r"```(?:json)?", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def rnss(gt_vals, pr_vals):
    if not gt_vals:
        return None
    if not pr_vals:
        return 0.0
    k = max(len(gt_vals), len(pr_vals))
    C = np.ones((k, k))
    for i, g in enumerate(gt_vals):
        for j, p in enumerate(pr_vals):
            C[i, j] = min(1.0, rel_err(p, g))
    r, c = linear_sum_assignment(C)
    return 1 - C[r, c].sum() / k


def score_chart(gt, out_text):
    pred = parse_json(out_text)
    rows = []
    gt_pts = gt["data"]
    multi = len({p["series"] for p in gt_pts}) > 1
    if pred is None:
        for g in gt_pts:
            rows.append({**_base(gt, g), "pred_raw": "", "pred": "", "err": "E0_khong_parse_duoc_JSON"})
        return rows, {"json_ok": 0, "rnss": 0.0, "type_ok": 0, "unit_ok": 0, "legend_ok": 0}

    pred_pts = []
    for p in pred.get("data") or []:
        try:
            v, kind = parse_pred(p.get("y"))
        except (ValueError, TypeError):
            continue
        pred_pts.append({"series": norm(p.get("series")), "x": norm(p.get("x")), "y": v, "raw": p.get("y"), "kind": kind})

    used = set()
    for g in gt_pts:
        cand = [i for i, p in enumerate(pred_pts) if i not in used and p["x"] == norm(g["x"])
                and (not multi or SequenceMatcher(None, p["series"], norm(g["series"])).ratio() > 0.6)]
        if not cand:
            rows.append({**_base(gt, g), "pred_raw": "", "pred": "", "err": "E8_thieu_diem_du_lieu"})
            continue
        i = min(cand, key=lambda i: rel_err(pred_pts[i]["y"], g["y"]))
        used.add(i)
        p = pred_pts[i]
        e = rel_err(p["y"], g["y"])
        if e <= 0.05:
            err = ""
        elif is_scale_error(p["y"], g["y"]):
            err = "E1_sai_dinh_dang_hoac_bac_so"
        else:
            err = "E2_sai_gia_tri"
        rows.append({**_base(gt, g), "pred_raw": p["raw"], "pred": p["y"], "rel_err": round(e, 4), "err": err})

    gt_unit = norm_unit((gt.get("y_axis") or {}).get("unit"))
    pr_unit = norm_unit((pred.get("y_axis") or {}).get("unit"))
    gt_leg = {norm(x) for x in gt.get("legend") or []}
    pr_leg = {norm(x) for x in pred.get("legend") or []}
    chart = {
        "json_ok": 1,
        "rnss": rnss([g["y"] for g in gt_pts], [p["y"] for p in pred_pts]),
        "type_ok": int(norm(pred.get("chart_type")) == norm(gt["chart_type"])),
        "unit_ok": int(gt_unit == pr_unit) if gt_unit else None,
        "legend_ok": int(gt_leg == pr_leg) if gt_leg else None,
        "n_extra_points": len(pred_pts) - len(used),
    }
    return rows, chart


def _base(gt, g):
    return {"id": gt["id"], "chart_type": gt["chart_type"], "series": g["series"], "x": g["x"],
            "gt_raw": g.get("y_raw", g["y"]), "gt": g["y"]}


def main(path):
    labels = {}
    for p in LABEL_DIR.glob("*.json"):
        if not p.name.startswith("example_"):
            r = json.loads(p.read_text(encoding="utf-8"))
            if r.get("data") and r.get("status") != "todo":  # chỉ chấm ảnh đã gán nhãn
                labels[r["id"]] = r
    outs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

    all_rows, charts = [], []
    for o in outs:
        if o["id"] not in labels:
            continue
        rows, ch = score_chart(labels[o["id"]], o["output"])
        all_rows += rows
        charts.append({"id": o["id"], "chart_type": labels[o["id"]]["chart_type"], **ch,
                       "ra5": np.mean([r["err"] == "" for r in rows]) if rows else None})

    name = Path(path).stem
    res = Path("eval/results")
    res.mkdir(parents=True, exist_ok=True)
    _write(res / f"{name}__points.csv", all_rows)
    _write(res / f"{name}__charts.csv", charts)

    by = defaultdict(list)
    for c in charts:
        by[c["chart_type"]].append(c)
        by["TỔNG"].append(c)
    print(f"\n{name}")
    print(f"{'loại':<8}{'n':>5}{'JSON ok':>9}{'RA@5%':>8}{'RNSS':>7}{'loại ok':>9}{'đơn vị':>8}")
    for k, cs in sorted(by.items(), key=lambda kv: kv[0] == "TỔNG"):
        f = lambda key: np.nanmean([c[key] if c.get(key) is not None else np.nan for c in cs])
        print(f"{k:<8}{len(cs):>5}{f('json_ok'):>9.2f}{f('ra5'):>8.2f}{f('rnss'):>7.2f}{f('type_ok'):>9.2f}{f('unit_ok'):>8.2f}")
    errs = defaultdict(int)
    for r in all_rows:
        if r["err"]:
            errs[r["err"]] += 1
    print("Lỗi điểm dữ liệu:", dict(errs), f"/ {len(all_rows)} điểm")


def _write(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main(sys.argv[1])
