"""Chấm kết quả prompt 'extract' (chart-to-table) so với nhãn.

  python eval/score_extract.py outputs/Qwen3-VL-2B-Instruct__extract__v1.jsonl [file2 ...]
  -> eval/results/<tên>__points.csv   (từng điểm dữ liệu, mã lỗi theo 2 chế độ: err, err_lenient)
  -> eval/results/<tên>__charts.csv   (từng biểu đồ đã có nhãn, chỉ số theo 2 chế độ)
  -> eval/results/<tên>__all.csv      (MỌI biểu đồ, kể cả chưa gán nhãn: JSON, bị cắt, lặp, loại biểu đồ)
  -> in 3 bảng: thống kê không cần nhãn, điểm CHẶT, điểm NỚI

Hai chế độ chấm:
  CHẶT (strict)  : như phiên bản cũ. JSON không parse được -> mọi điểm E0. x phải khớp tuyệt đối
                   (sau chuẩn hoá chữ thường, khoảng trắng); biểu đồ nhiều chuỗi phải khớp cả series.
  NỚI  (lenient) : đo khả năng ĐỌC SỐ, bỏ qua lỗi tuân thủ định dạng:
                   - cứu JSON bị cắt/sai cú pháp: lấy mọi điểm {series, x, y} viết trọn vẹn;
                   - so x gần đúng: kỳ/kì (y/i có dấu), bỏ tiền tố "Năm", 2010 == "2010" == 2010.0,
                     gạch nối, độ giống chuỗi >= 0.85;
                   - chấp nhận tráo vai trò series <-> x (vd tên nước nằm ở series, x = null);
                   - đơn vị: chấp nhận khi đơn vị đúng nằm ở trường label hoặc trong ngoặc của label.
  Báo cả hai: chênh lệch CHẶT - NỚI = phần lỗi do không theo đúng mẫu JSON, không phải do đọc sai số.

Chỉ số:
  RA@5%   : tỉ lệ điểm dữ liệu có sai số tương đối <= 5% (relaxed accuracy, như ChartQA/UniChart)
  RNSS    : Relative Number Set Similarity (ChartQA), khớp tập số bằng bài toán gán tối ưu
  type_ok / unit_ok / legend_ok : đúng loại biểu đồ / đơn vị trục y / chú giải

Mã lỗi điểm dữ liệu:
  E0  không parse được JSON (chỉ ở chế độ chặt)
  E0b điểm bị mất vì output bị cắt hoặc hỏng giữa chừng (chế độ nới, JSON phải cứu)
  E1  sai định dạng hoặc bậc số (lệch đúng 10/100/1000 lần: đọc nhầm dấu chấm/phẩy)
  E2  sai giá trị
  E8  thiếu điểm dữ liệu (output hoàn chỉnh nhưng không có điểm này)
Cờ mức biểu đồ (file __all.csv): hit_limit (chạm max_new_tokens), loop (một điểm hoặc một cặp
series × x lặp >= 5 lần), type_valid (chart_type thuộc tập cho phép; "bar|line" là không hợp lệ).
type_ok_norm (file __charts.csv): như type_ok nhưng quy "bar|line", "cột và đường"... về combo (xem canon_type).
"""
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).parent))
from vn_number import is_scale_error, parse_pred, rel_err  # noqa: E402

LABEL_DIR = Path("data/labels")
VALID_TYPES = {"bar", "line", "pie", "combo", "area", "other"}
LOOP_MIN = 5          # một điểm lặp từ 5 lần trở lên -> coi là lặp
LIMIT_MARGIN = 8      # n_new_tokens >= max_new_tokens - 8 -> coi là chạm giới hạn
Y2I = str.maketrans("ỳýỷỹỵ", "ìíỉĩị")


def canon_type(t):
    """Quy chart_type về tập hợp lệ: mô hình hay chép nguyên mẫu "bar|line" (hoặc line|bar, bar+line,
    cột và đường) cho biểu đồ kết hợp -> coi là combo. Dùng cho type_ok_norm; type_ok giữ nguyên cách chấm cũ."""
    t = norm(t)
    parts = set(re.split(r"\s*(?:\||\+|/|,|&| và | and )\s*", t)) - {""}
    parts = {{"cột": "bar", "đường": "line", "column": "bar"}.get(x, x) for x in parts}
    if len(parts) >= 2 and parts <= VALID_TYPES - {"other"}:
        return "combo"
    return t


# ---------------------------------------------------------------- chuẩn hoá
def norm(s):
    s = unicodedata.normalize("NFC", str(s if s is not None else "")).lower().strip()
    return re.sub(r"\s+", " ", s)


def norm_unit(s):
    """Chuẩn hoá đơn vị để so khớp chính xác: 'Nghìn km' == 'nghìn km', 'tỷ đồng' == 'tỉ đồng',
    '(%)' == '%'. KHÔNG so khớp chuỗi con, vì 'km' khác 'nghìn km' (lệch 1000 lần)."""
    s = norm(s).replace("tỷ", "tỉ").replace("ngàn", "nghìn")
    return re.sub(r"[()\[\]\s]+", " ", s).strip()


def norm_x(v):
    """Chuẩn hoá nhãn x / series cho chế độ nới."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = norm(v).translate(Y2I)
    s = re.sub(r"^năm\s+", "", s)
    s = re.sub(r"(?<=\d)\.0+$", "", s)
    s = re.sub(r"\s*[-–—]\s*", "-", s)
    s = re.sub(r"[\"'“”()\[\]]", "", s)
    return s.strip(" .:")


def similar(a, b, thr):
    if not a or not b:
        return False
    return a == b or SequenceMatcher(None, a, b).ratio() >= thr


# ---------------------------------------------------------------- đọc output
def _strip(text):
    return re.sub(r"```(?:json)?", "", text or "")


def parse_json(text):
    """Parse nghiêm ngặt: đối tượng JSON đầu-cuối. Trả dict hoặc None."""
    m = re.search(r"\{.*\}", _strip(text), re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _field(t, key, opener, closer):
    m = re.search(r'"%s"\s*:\s*(\%s[^%s%s]*\%s)' % (key, opener, opener, closer, closer), t)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def salvage_json(text):
    """Cứu output bị cắt hoặc sai cú pháp: lấy các trường đầu và mọi điểm dữ liệu viết trọn vẹn."""
    t = _strip(text)
    pts = []
    for m in re.finditer(r"\{[^{}]*\}", t):
        try:
            o = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and "y" in o and ("x" in o or "series" in o):
            pts.append(o)
    if not pts:
        return None
    ct = re.search(r'"chart_type"\s*:\s*"([^"]*)"', t)
    return {
        "chart_type": ct.group(1) if ct else None,
        "x_axis": _field(t, "x_axis", "{", "}"),
        "y_axis": _field(t, "y_axis", "{", "}"),
        "legend": _field(t, "legend", "[", "]"),
        "data": pts,
    }


def read_pred(text):
    """-> (dict | None, trạng thái 'ok' | 'salvaged' | 'fail')"""
    p = parse_json(text)
    if p is not None:
        return p, "ok"
    p = salvage_json(text)
    return (p, "salvaged") if p is not None else (None, "fail")


def pred_points(pred):
    pts = []
    for p in (pred or {}).get("data") or []:
        if not isinstance(p, dict):
            continue
        try:
            v, kind = parse_pred(p.get("y"))
        except (ValueError, TypeError):
            continue
        pts.append({"series": p.get("series"), "x": p.get("x"), "y": v, "raw": p.get("y"), "kind": kind})
    return pts


def chart_flags(rec, pred):
    n, mx = rec.get("n_new_tokens"), rec.get("max_new_tokens")
    hit = int(n is not None and mx is not None and n >= mx - LIMIT_MARGIN)
    data = [p for p in (pred or {}).get("data") or [] if isinstance(p, dict)]
    full = Counter(json.dumps(p, sort_keys=True, ensure_ascii=False) for p in data)
    keys = Counter((norm_x(p.get("series")), norm_x(p.get("x"))) for p in data)
    rep = max(list(full.values()) + list(keys.values()) + [0])
    ct = norm((pred or {}).get("chart_type"))
    return {"hit_limit": hit, "loop": int(rep >= LOOP_MIN), "max_repeat": rep,
            "pred_type": ct, "type_valid": int(ct in VALID_TYPES), "n_pred_points": len(data)}


# ---------------------------------------------------------------- chấm
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


def _match_strict(p, g, multi):
    return norm(p["x"]) == norm(g["x"]) and (
        not multi or SequenceMatcher(None, norm(p["series"]), norm(g["series"])).ratio() > 0.6)


def _match_lenient(p, g, single):
    gx, gs = norm_x(g["x"]), norm_x(g["series"])
    px, ps = norm_x(p["x"]), norm_x(p["series"])
    direct = similar(px, gx, 0.85) and (single or similar(ps, gs, 0.6))
    swap = similar(ps, gx, 0.85) and (single or similar(px, gs, 0.6))
    return direct or swap


def unit_ok(gt, pred, lenient):
    gt_unit = norm_unit((gt.get("y_axis") or {}).get("unit"))
    if not gt_unit:
        return None
    ya = (pred or {}).get("y_axis") or {}
    if not isinstance(ya, dict):
        return 0
    if norm_unit(ya.get("unit")) == gt_unit:
        return 1
    if lenient:
        label = str(ya.get("label") or "")
        inner = re.findall(r"\(([^)]*)\)", label)
        if norm_unit(label) == gt_unit or any(norm_unit(x) == gt_unit for x in inner):
            return 1
    return 0


def score_chart(gt, rec, lenient):
    text = rec["output"]
    if lenient:
        pred, status = read_pred(text)
    else:
        pred = parse_json(text)
        status = "ok" if pred is not None else "fail"
    gt_pts = gt["data"]
    rows = []
    if pred is None:
        code = "E0b_bi_cat_hoac_hong" if lenient else "E0_khong_parse_duoc_JSON"
        for g in gt_pts:
            rows.append({**_base(gt, g), "pred_raw": "", "pred": "", "err": code})
        return rows, {"json_ok": 0, "salvaged": 0, "rnss": 0.0, "type_ok": 0, "type_ok_norm": 0, "unit_ok": 0,
                      "legend_ok": 0, "n_extra_points": 0}

    pts = pred_points(pred)
    gseries = {norm_x(g["series"]) for g in gt_pts}
    single = len(gseries) == 1 or all(norm_x(g["series"]) == norm_x(g["x"]) for g in gt_pts)
    multi = len({g["series"] for g in gt_pts}) > 1
    missing_code = "E0b_bi_cat_hoac_hong" if status == "salvaged" else "E8_thieu_diem_du_lieu"

    used = set()
    for g in gt_pts:
        if lenient:
            cand = [i for i, p in enumerate(pts) if i not in used and _match_lenient(p, g, single)]
        else:
            cand = [i for i, p in enumerate(pts) if i not in used and _match_strict(p, g, multi)]
        if not cand:
            rows.append({**_base(gt, g), "pred_raw": "", "pred": "", "err": missing_code})
            continue
        i = min(cand, key=lambda i: rel_err(pts[i]["y"], g["y"]))
        used.add(i)
        p = pts[i]
        e = rel_err(p["y"], g["y"])
        if e <= 0.05:
            err = ""
        elif is_scale_error(p["y"], g["y"]):
            err = "E1_sai_dinh_dang_hoac_bac_so"
        else:
            err = "E2_sai_gia_tri"
        rows.append({**_base(gt, g), "pred_raw": p["raw"], "pred": p["y"], "rel_err": round(e, 4), "err": err})

    nx = norm_x if lenient else norm
    gt_leg = {nx(x) for x in gt.get("legend") or []}
    pr_leg = {nx(x) for x in (pred.get("legend") or []) if isinstance(x, (str, int, float))}
    chart = {
        "json_ok": int(status == "ok"),
        "salvaged": int(status == "salvaged"),
        "rnss": rnss([g["y"] for g in gt_pts], [p["y"] for p in pts]),
        "type_ok": int(norm(pred.get("chart_type")) == norm(gt["chart_type"])),
        "type_ok_norm": int(canon_type(pred.get("chart_type")) == norm(gt["chart_type"])),
        "unit_ok": unit_ok(gt, pred, lenient),
        "legend_ok": int(gt_leg == pr_leg) if gt_leg else None,
        "n_extra_points": len(pts) - len(used),
    }
    return rows, chart


def _base(gt, g):
    return {"id": gt["id"], "chart_type": gt["chart_type"], "series": g["series"], "x": g["x"],
            "gt_raw": g.get("y_raw", g["y"]), "gt": g["y"]}


# ---------------------------------------------------------------- in bảng
def _mean(cs, key):
    xs = [c[key] for c in cs if c.get(key) is not None]
    return float(np.mean(xs)) if xs else float("nan")


def _table(title, charts, rows, suffix=""):
    by = defaultdict(list)
    for c in charts:
        by[c["chart_type"]].append(c)
        by["TỔNG"].append(c)
    print(f"\n  [{title}]")
    print(f"  {'loại':<8}{'n':>5}{'JSON ok':>9}{'cứu':>6}{'RA@5%':>8}{'RNSS':>7}{'loại ok':>9}{'đơn vị':>8}")
    for k, cs in sorted(by.items(), key=lambda kv: kv[0] == "TỔNG"):
        print(f"  {k:<8}{len(cs):>5}{_mean(cs, 'json_ok'):>9.2f}{_mean(cs, 'salvaged' + suffix):>6.2f}"
              f"{_mean(cs, 'ra5' + suffix):>8.2f}{_mean(cs, 'rnss' + suffix):>7.2f}"
              f"{_mean(cs, 'type_ok'):>9.2f}{_mean(cs, 'unit_ok' + suffix):>8.2f}")
    errs = Counter(r["err" + suffix] for r in rows if r["err" + suffix])
    print(f"  Lỗi điểm dữ liệu: {dict(errs)} / {len(rows)} điểm")


def load_labels():
    """-> (mọi nhãn kể cả chưa gán, nhãn đã gán xong để chấm)"""
    every, done = {}, {}
    for p in LABEL_DIR.glob("*.json"):
        if p.name.startswith("example_"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("status") == "excluded":  # ảnh bị loại khỏi bộ dữ liệu
            continue
        every[r["id"]] = r
        if r.get("data") and r.get("status") != "todo":
            done[r["id"]] = r
    return every, done


def score_file(path, every, done):
    outs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    outs = [o for o in outs if o["id"] in every]   # bỏ id không còn trong bộ dữ liệu (ảnh trùng đã xoá)
    name = Path(path).stem

    # 1) thống kê không cần nhãn, trên mọi biểu đồ
    allrows = []
    for o in outs:
        pred, status = read_pred(o["output"])
        allrows.append({"id": o["id"], "chart_type": every[o["id"]]["chart_type"], "json_status": status,
                        "n_new_tokens": o.get("n_new_tokens"), **chart_flags(o, pred)})
    n = len(allrows)
    st = Counter(r["json_status"] for r in allrows)
    print(f"\n=== {name}")
    print(f"  [Mọi biểu đồ, không cần nhãn] n = {n}: JSON ok {st['ok']} | cứu được {st['salvaged']} | "
          f"hỏng hẳn {st['fail']} | chạm giới hạn {sum(r['hit_limit'] for r in allrows)} | "
          f"lặp {sum(r['loop'] for r in allrows)} | chart_type không hợp lệ "
          f"{sum(1 for r in allrows if r['json_status'] != 'fail' and not r['type_valid'])}")
    conf = Counter((r["chart_type"], r["pred_type"] or "-") for r in allrows if r["json_status"] != "fail")
    print("  Nhầm loại (nhãn -> dự đoán):",
          ", ".join(f"{a}->{b}: {c}" for (a, b), c in sorted(conf.items()) if a != b) or "không")

    # 2) chấm trên ảnh đã có nhãn, hai chế độ
    pts_rows, charts = [], []
    for o in outs:
        if o["id"] not in done:
            continue
        gt = done[o["id"]]
        r_s, c_s = score_chart(gt, o, lenient=False)
        r_l, c_l = score_chart(gt, o, lenient=True)
        for a, b in zip(r_s, r_l):
            a.update({"pred_raw_lenient": b["pred_raw"], "pred_lenient": b["pred"], "err_lenient": b["err"]})
            pts_rows.append(a)
        ra = lambda rs: float(np.mean([r["err"] == "" for r in rs])) if rs else None
        charts.append({"id": o["id"], "chart_type": gt["chart_type"],
                       "values_shown": int(gt.get("values_shown_on_chart") is not False),
                       "duplicate": int(bool(gt.get("duplicate_of"))), **c_s, "ra5": ra(r_s),
                       **{k + "_lenient": v for k, v in c_l.items() if k not in ("json_ok", "type_ok", "type_ok_norm")},
                       "ra5_lenient": ra(r_l)})

    res = Path("eval/results")
    res.mkdir(parents=True, exist_ok=True)
    _write(res / f"{name}__all.csv", allrows)
    _write(res / f"{name}__points.csv", pts_rows)
    _write(res / f"{name}__charts.csv", charts)
    if not charts:
        print("  (chưa có biểu đồ nào đã gán nhãn để chấm)")
        return
    _table("CHẶT", charts, pts_rows)
    _table("NỚI: cứu JSON + ghép gần đúng", charts, pts_rows, suffix="_lenient")


def _write(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    every, done = load_labels()
    for path in sys.argv[1:]:
        score_file(path, every, done)
