"""Gộp hai bản cài đặt bước 2–3 vào CÙNG một thực nghiệm, chấm bằng CẢ HAI bộ chỉ số.

  python eval/run_team_pipeline.py
  (chạy sau src/pipeline/run.py, xem README_pipeline.md)

Hai bản cài đặt bước 2–3 (kiểm chứng + mô tả 3 cấp):
  nhóm  : vichartfact_metrics.py ở gốc repo (validate_chart_data -> apply_uncertainty_flagging -> generate_3level_descriptions)
  Giang : src/pipeline/verify.py + describe.py (luật R1–R9)
Cả hai nhận CÙNG bảng bước 1 (outputs/<mô hình>__extract__v1.jsonl) hoặc bảng nhãn (mức trần). File này chỉ import
vichartfact_metrics.py, không sửa gì trong đó.

Các nhánh:
  A_<mô hình>        VLM mô tả thẳng từ ảnh                     outputs/<mô hình>__describe__v1.jsonl
  B-nhom_<mô hình>   bước 1 của mô hình -> bước 2–3 của nhóm      (tạo ở đây -> outputs/pipeline_nhom/)
  B_<mô hình>        bước 1 của mô hình -> bước 2–3 của Giang     outputs/pipeline/pipeline__<mô hình>__omit.jsonl
  C-nhom / C         bảng nhãn thay bước 1 (mức trần)

Chỉ số (mọi nhánh, so với nhãn đã soát data/labels/):
  Bộ của Giang (eval/compare_pipeline.py), chấm trên mức "diễn giải" (desc_study / dien_giai; nhánh A: cả đoạn):
    %bd_co_so_sai, %so_sai, do_phu_%, %thieu_don_vi      : con số phải khớp một ô của bảng nhãn (sai số <= 5%)
    %bd_co_so_sai_ps, %so_sai_ps                         : như trên nhưng chấp nhận thêm số PHÁI SINH đúng tính từ bảng nhãn
        (hiệu, tổng, % thay đổi, số lần giữa hai ô cùng chuỗi hoặc cùng mốc; sai số <= 0,5% hoặc <= 0,05) và số đếm
        mốc/chuỗi. Cần biến thể này vì mô tả của nhóm có nêu chênh lệch, mức tăng ("tăng thêm 32,4 nghìn ha").
  Bộ của Nhi (vichartfact_metrics.py), chấm trên cả 3 mức:
    vichartfact_%   : fact_check_against_ground_truth (ViChartFact end-to-end so với nhãn)
    so_lech_tb      : số thực thể số không khớp nhãn, trung bình mỗi biểu đồ
    day_du_%        : evaluate_description_completeness (4 tiêu chí x 25 điểm)
Khoảng tin cậy 95%: bootstrap ghép cặp theo biểu đồ (2000 lần).
Kết quả: eval/results/compare_team_pipeline.md / .csv / _diff.csv
"""
import csv
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "eval", ROOT / "src" / "pipeline"):
    sys.path.insert(0, str(p))

import vichartfact_metrics as vm  # noqa: E402  (bước 2–3 + thước đo của nhóm, chỉ import)
from compare_pipeline import agg, label_number_tokens, load_labels, norm, score  # noqa: E402
from score_extract import read_pred  # noqa: E402
from vn_number import alt_readings, find_numbers, rel_err  # noqa: E402

OUT, RES = ROOT / "outputs", ROOT / "eval" / "results"
MODELS = ["Qwen3-VL-2B-Instruct", "Vintern-1B-v3_5"]
N_BOOT, SEED = 2000, 2026


# ---------------------------------------------------------------- chuyển bảng sang định dạng phẳng của nhóm
def vn_str(v):
    """Số -> chuỗi kiểu Việt mà clean_vietnamese_number đọc đúng (tránh '0,125' bị hiểu là 125)."""
    if isinstance(v, str):
        return v.strip() or "nan"
    if v is None:
        return "nan"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "nan"
    if f == int(f):
        return str(int(f))
    s = f"{f:.4f}".rstrip("0")
    ip, dp = s.split(".")
    if len(dp) == 3:
        dp += "0"
    return f"{ip},{dp}"


def to_flat(title, ctype, unit, points):
    """points: [(series, x, y)] -> dict chart_title/chart_type/unit/categories/series_name/values (như Benchmark.xlsx)."""
    xs = list(dict.fromkeys(str(x) for _, x, _ in points))
    ss = list(dict.fromkeys(str(s) if s not in (None, "") else "Giá trị" for s, _, _ in points))
    cell = {}
    for s, x, y in points:
        cell.setdefault((str(s) if s not in (None, "") else "Giá trị", str(x)), y)
    values = " || ".join(" | ".join(vn_str(cell.get((s, x))) for x in xs) for s in ss)
    return {"chart_title": title or "", "chart_type": ctype or "", "unit": unit or "", "x_axis_label": "",
            "categories": " | ".join(xs), "series_name": " | ".join(ss), "values": values}


def flat_gold(g):
    return to_flat(g.get("title"), g["chart_type"], (g.get("y_axis") or {}).get("unit"),
                   [(d["series"], d["x"], d["y"]) for d in g["data"]])


def flat_pred(pred):
    pred = pred or {}
    ya = pred.get("y_axis") if isinstance(pred.get("y_axis"), dict) else {}
    pts = [(d.get("series"), d.get("x"), d.get("y")) for d in pred.get("data") or [] if isinstance(d, dict)]
    return to_flat(pred.get("title"), pred.get("chart_type"), ya.get("unit"), pts)


def team_describe(flat):
    """Bước 2–3 của nhóm, đúng như evaluate_vichartfact_completeness.py gọi."""
    try:
        _, notes, parsed = vm.validate_chart_data(flat)
        flagged = vm.apply_uncertainty_flagging(parsed, notes)
        return vm.generate_3level_descriptions(flagged), flagged["has_uncertainty"], None
    except Exception as e:  # noqa: BLE001  bảng bước 1 hỏng -> mô tả rỗng, ghi lỗi
        return {"desc_5s": "", "desc_30s": "", "desc_study": ""}, True, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- biến thể chấp nhận số phái sinh đúng
def derived_pool(gt):
    by_s, by_x = {}, {}
    for d in gt["data"]:
        by_s.setdefault(str(d["series"]), []).append(float(d["y"]))
        by_x.setdefault(str(d["x"]), []).append(float(d["y"]))
    allv = [float(d["y"]) for d in gt["data"]]
    pool = {len(by_s), len(by_x), max(allv) - min(allv)}          # số đếm mốc/chuỗi, biên độ toàn biểu đồ
    for group in list(by_s.values()) + list(by_x.values()):
        pool.add(sum(group))                                       # tổng một chuỗi / một mốc (vd tổng các lát = 100%)
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pool |= {abs(a - b), a + b}
                for lo, hi in ((a, b), (b, a)):
                    if lo:
                        pool |= {abs(hi - lo) / abs(lo) * 100, abs(hi / lo)}
    return pool


def score_ps(text, gt, pool):
    vals = [float(d["y"]) for d in gt["data"]]
    skip = label_number_tokens(gt)
    n = bad = 0
    for tok in find_numbers(text):
        if norm(tok) in skip:
            continue
        n += 1
        reads = alt_readings(tok)
        if any(rel_err(r, v) <= 0.05 for r in reads for v in vals):
            continue
        if any(abs(r - p) <= 0.05 or rel_err(r, p) <= 0.005 for r in reads for p in pool):
            continue
        bad += 1
    return {"n_so_ps": n, "sai_ps": bad, "co_so_sai_ps": int(bad > 0)}


# ---------------------------------------------------------------- chấm một mô tả bằng cả hai bộ chỉ số
THOUSANDS = re.compile(r"(?<![\d.,])(\d{1,3})((?:\.\d{3})+)(?![\d.])")


def no_thousands(text):
    """'6.586,6' -> '6586,6'. Bộ tách số của vichartfact_metrics đọc '6.586,6' thành '6' và '586,6' (tính oan là số sai),
    nên trước khi đưa vào thước đo của nhóm, mọi nhánh đều bỏ dấu chấm nghìn (chỉ đổi cách viết, không đổi giá trị)."""
    return THOUSANDS.sub(lambda m: m.group(1) + m.group(2).replace(".", ""), text or "")


def score_all(desc, text_main, gt, gflat, pool, has_unc):
    r = score(text_main, gt)
    r.update(score_ps(text_main, gt, pool))
    desc = {k: no_thousands(v) for k, v in desc.items()}
    fc = vm.fact_check_against_ground_truth(desc, gflat, has_uncertainty=has_unc)
    cp = vm.evaluate_description_completeness(desc, gflat, has_uncertainty=has_unc)
    r.update({"vf": float(fc.get("accuracy", 0.0)), "lech": int(fc.get("unmatched_count", 0)),
              "dd": float(cp.get("completeness_score", 0.0))})
    return r


def agg_all(rows):
    a = agg(rows)
    n = max(1, len(rows))
    nps = max(1, sum(r["n_so_ps"] for r in rows))
    return {"n_bd": a["n_bd"], "%bd_co_so_sai": a["%bd_co_so_sai"], "%so_sai": a["%so_sai"], "do_phu_%": a["do_phu_%"],
            "%thieu_don_vi": a["%thieu_don_vi"],
            "%bd_co_so_sai_ps": round(100 * sum(r["co_so_sai_ps"] for r in rows) / n, 1),
            "%so_sai_ps": round(100 * sum(r["sai_ps"] for r in rows) / nps, 1),
            "vichartfact_%": round(sum(r["vf"] for r in rows) / n, 1),
            "so_lech_tb": round(sum(r["lech"] for r in rows) / n, 2),
            "day_du_%": round(sum(r["dd"] for r in rows) / n, 1),
            "so_tu_tb": a["so_tu_tb"]}


METRICS = {  # tên cột -> hàm tính trên một tập biểu đồ (dùng cho bootstrap)
    "%bd_co_so_sai": lambda R, ids: 100 * sum(R[i]["co_so_sai"] for i in ids) / len(ids),
    "%bd_co_so_sai_ps": lambda R, ids: 100 * sum(R[i]["co_so_sai_ps"] for i in ids) / len(ids),
    "vichartfact_%": lambda R, ids: sum(R[i]["vf"] for i in ids) / len(ids),
    "day_du_%": lambda R, ids: sum(R[i]["dd"] for i in ids) / len(ids),
}


def boot(a, b, key):
    ids = sorted(set(a) & set(b))
    rng, f = random.Random(SEED), METRICS[key]
    point = f(b, ids) - f(a, ids)
    bs = sorted(f(b, s) - f(a, s) for s in ([rng.choice(ids) for _ in ids] for _ in range(N_BOOT)))
    return round(point, 1), round(bs[int(0.025 * N_BOOT)], 1), round(bs[int(0.975 * N_BOOT)], 1)


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def md_table(rows):
    keys = list(rows[0])
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    lines += ["| " + " | ".join(str(r[k]) for k in keys) + " |" for r in rows]
    return "\n".join(lines)


def main():
    gts = load_labels()
    gflat = {i: flat_gold(g) for i, g in gts.items()}
    pools = {i: derived_pool(g) for i, g in gts.items()}
    per, errors = {}, {}
    (OUT / "pipeline_nhom").mkdir(parents=True, exist_ok=True)

    def run_team(name, tables):
        per[name], errors[name] = {}, 0
        out = []
        for cid, flat in tables.items():
            desc, unc, err = team_describe(flat)
            errors[name] += err is not None
            per[name][cid] = score_all(desc, desc["desc_study"], gts[cid], gflat[cid], pools[cid], unc)
            out.append({"id": cid, "output": desc["desc_study"], "levels": desc, "has_uncertainty": unc,
                        "input_table": flat, "error": err})
        with open(OUT / "pipeline_nhom" / f"pipeline_nhom__{name.split('_', 1)[1]}.jsonl", "w", encoding="utf-8") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    for m in MODELS:
        # A: VLM mô tả thẳng (một đoạn văn -> đưa vào mức "diễn giải" cho thước đo của nhóm)
        p = OUT / f"{m}__describe__v1.jsonl"
        if p.exists():
            per["A_" + m] = {}
            for o in read_jsonl(p):
                if o["id"] in gts:
                    desc = {"desc_5s": "", "desc_30s": "", "desc_study": o["output"]}
                    per["A_" + m][o["id"]] = score_all(desc, o["output"], gts[o["id"]], gflat[o["id"]], pools[o["id"]], False)
        # B-nhóm: cùng bảng bước 1 -> bước 2–3 của nhóm
        p = OUT / f"{m}__extract__v1.jsonl"
        if p.exists():
            tables = {o["id"]: flat_pred(read_pred(o["output"])[0]) for o in read_jsonl(p) if o["id"] in gts}
            run_team("B-nhom_" + m, tables)
        # B: bước 2–3 của Giang (đã chạy bằng src/pipeline/run.py)
        p = OUT / "pipeline" / f"pipeline__{m}__omit.jsonl"
        if not p.exists():
            sys.exit(f"Thiếu {p}. Chạy src/pipeline/run.py trước (xem README_pipeline.md).")
        per["B_" + m] = {}
        for o in read_jsonl(p):
            if o["id"] in gts:
                lv = o["levels"]
                desc = {"desc_5s": lv["nghe_5s"], "desc_30s": lv["nghe_30s"], "desc_study": lv["dien_giai"]}
                per["B_" + m][o["id"]] = score_all(desc, o["output"], gts[o["id"]], gflat[o["id"]], pools[o["id"]],
                                                   o["n_uncertain"] > 0)
    # mức trần: bảng nhãn thay bước 1
    run_team("C-nhom_nhan", dict(gflat))
    p = OUT / "pipeline" / "pipeline__gold__omit.jsonl"
    if p.exists():
        per["C_nhan"] = {}
        for o in read_jsonl(p):
            if o["id"] in gts:
                lv = o["levels"]
                desc = {"desc_5s": lv["nghe_5s"], "desc_30s": lv["nghe_30s"], "desc_study": lv["dien_giai"]}
                per["C_nhan"][o["id"]] = score_all(desc, o["output"], gts[o["id"]], gflat[o["id"]], pools[o["id"]],
                                                   o["n_uncertain"] > 0)

    table = [{"nhanh": n, **agg_all(list(r.values()))} for n, r in per.items()]
    diffs = []
    pairs = [(f"B-nhom_{m}", f"A_{m}") for m in MODELS] + [(f"B_{m}", f"A_{m}") for m in MODELS] \
        + [(f"B_{m}", f"B-nhom_{m}") for m in MODELS] + [("C_nhan", "C-nhom_nhan")]
    for b, a in pairs:
        if a in per and b in per:
            for key in METRICS:
                d, lo, hi = boot(per[a], per[b], key)
                diffs.append({"so_sanh": f"{b} - {a}", "chi_so": key, "hieu": d, "CI95": f"[{lo}; {hi}]",
                              "co_y_nghia": "có" if lo > 0 or hi < 0 else "không"})

    RES.mkdir(parents=True, exist_ok=True)
    write_csv(RES / "compare_team_pipeline.csv", table)
    write_csv(RES / "compare_team_pipeline_diff.csv", diffs)
    err_note = ", ".join(f"{n}: {k}" for n, k in errors.items() if k) or "không có"
    text = f"""# Hai bản cài đặt bước 2–3 trên cùng dữ liệu, chấm bằng hai bộ chỉ số

Sinh bởi `python eval/run_team_pipeline.py`. 200 biểu đồ, nhãn `data/labels/` (đã soát).
`B-nhom` / `C-nhom` = bước 2–3 của nhóm (`vichartfact_metrics.py`); `B` / `C` = bước 2–3 của Giang (`src/pipeline/`).
Cùng bảng bước 1 (`outputs/<mô hình>__extract__v1.jsonl`); C dùng bảng nhãn thay bước 1 (mức trần).

- `%bd_co_so_sai`, `%so_sai`, `do_phu_%`, `%thieu_don_vi`: thước đo của `eval/compare_pipeline.py` (con số phải khớp một ô nhãn),
  chấm trên mức diễn giải.
- `..._ps`: như trên nhưng chấp nhận thêm số phái sinh đúng (hiệu, tổng, % thay đổi, số lần giữa hai ô cùng chuỗi/mốc) và số đếm mốc/chuỗi.
- `vichartfact_%`, `so_lech_tb`, `day_du_%`: thước đo của nhóm (`fact_check_against_ground_truth`,
  `evaluate_description_completeness`), chấm trên cả 3 mức, so với nhãn đã soát.
- Lỗi khi chạy bước 2–3 của nhóm (mô tả rỗng): {err_note}.

{md_table(table)}

## Hiệu giữa các nhánh (CI 95% bootstrap ghép cặp)

{md_table(diffs)}
"""
    (RES / "compare_team_pipeline.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
