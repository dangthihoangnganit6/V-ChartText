"""Kiểm định ghép cặp theo biểu đồ: so 2 phiên bản prompt trích xuất (mặc định Qwen v1 -> v2).

  python eval/score_extract.py outputs/<model>__extract__v1.jsonl outputs/<model>__extract__v2.jsonl
  python eval/paired_test.py [--model Qwen3-VL-2B-Instruct] [--a v1] [--b v2]
  -> eval/results/paired_<a>_<b>.md, paired_<a>_<b>.csv

Hai họ chỉ số, đều tính trên cùng tập biểu đồ có ở cả hai phiên bản (ghép cặp theo id):
  1) Bước 1 (trích xuất), từ eval/results/<model>__extract__<v>__charts.csv / __points.csv:
     RA@5% (chặt, nới), RNSS (chặt, nới), đơn vị đúng (chặt, nới), loại đúng (type_ok_norm),
     %điểm thiếu (E8 + E0b, chế độ nới).
  2) Pipeline (bước 2-3), từ outputs/pipeline/pipeline__<model>[@<v>]__{omit,hedge}.jsonl,
     chấm bằng đúng hàm của eval/compare_pipeline.py: %bd_co_so_sai, %so_sai, do_phu, %thieu_don_vi.
Thống kê: hiệu (b - a); CI 95% bootstrap ghép cặp theo biểu đồ (10 000 lần, percentile);
p hai phía bằng kiểm định hoán vị ghép cặp (đổi chỗ a/b ngẫu nhiên trong từng biểu đồ, 10 000 lần);
p_Holm hiệu chỉnh đa so sánh trong mỗi bảng tổng; thắng/thua/hoà = số biểu đồ b tốt hơn/kém hơn/bằng a.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import compare_pipeline as cp  # noqa: E402

RES = Path("eval/results")
N, SEED = 10000, 2026

# (cột, tên hiển thị, hướng: +1 = càng cao càng tốt)
EXTRACT = [("ra5", "RA@5% chặt", 1), ("ra5_lenient", "RA@5% nới", 1),
           ("rnss", "RNSS chặt", 1), ("rnss_lenient", "RNSS nới", 1),
           ("unit_ok", "Đơn vị đúng chặt", 1), ("unit_ok_lenient", "Đơn vị đúng nới", 1),
           ("type_ok_norm", "Loại đúng (quy bar|line→combo)", 1),
           ("miss_lenient", "%điểm thiếu (nới)", -1)]


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_extract(model, v):
    stem = f"{model}__extract__{v}"
    charts = {r["id"]: r for r in read_csv(RES / f"{stem}__charts.csv")}
    miss = defaultdict(lambda: [0, 0])
    for r in read_csv(RES / f"{stem}__points.csv"):
        miss[r["id"]][1] += 1
        miss[r["id"]][0] += r["err_lenient"] in ("E8_thieu_diem_du_lieu", "E0b_bi_cat_hoac_hong")
    out = {}
    for i, r in charts.items():
        d = {k: fnum(r.get(k)) for k, _, _ in EXTRACT if k != "miss_lenient"}
        d["miss_lenient"] = miss[i][0] / miss[i][1] if miss[i][1] else np.nan
        d["chart_type"] = r["chart_type"]
        d["clean"] = r.get("values_shown") == "1" and r.get("duplicate") == "0"
        out[i] = d
    return out


def paired(a, b, stat=None, rng=None):
    """a, b: mảng (n,) cùng thứ tự biểu đồ; stat(a_idx_vals, b_idx_vals) mặc định = mean(b) - mean(a)."""
    stat = stat or (lambda x, y: np.nanmean(y) - np.nanmean(x))
    n = len(a)
    point = stat(a, b)
    idx = rng.integers(0, n, size=(N, n))
    boots = np.array([stat(a[k], b[k]) for k in idx])
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    flips = rng.random((N, n)) < 0.5
    fx = (lambda f: f[:, None]) if a.ndim == 2 else (lambda f: f)
    perm = np.array([stat(np.where(fx(f), b, a), np.where(fx(f), a, b)) for f in flips])
    p = (1 + np.sum(np.abs(perm) >= abs(point) - 1e-12)) / (N + 1)
    return point, lo, hi, p


def holm(ps):
    order = np.argsort(ps)
    adj, run = np.empty(len(ps)), 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - r) * ps[i]))
        adj[i] = run
    return adj


def fmt(x, pct):
    return f"{100 * x:+.1f}" if pct else f"{x:+.3f}"


def extract_table(A, B, ids, rng, with_holm=True):
    rows = []
    for k, name, sign in EXTRACT:
        a = np.array([A[i][k] for i in ids]); b = np.array([B[i][k] for i in ids])
        ok = ~(np.isnan(a) | np.isnan(b)); a, b = a[ok], b[ok]
        d, lo, hi, p = paired(a, b, rng=rng)
        better = int(np.sum(sign * (b - a) > 1e-9)); worse = int(np.sum(sign * (b - a) < -1e-9))
        rows.append({"chi_so": name, "n": int(ok.sum()), "a": np.mean(a), "b": np.mean(b), "hieu": d,
                     "lo": lo, "hi": hi, "p": p, "thang": better, "thua": worse, "hoa": int(ok.sum()) - better - worse})
    if with_holm:
        for r, q in zip(rows, holm(np.array([r["p"] for r in rows]))):
            r["p_holm"] = q
    return rows


def pipeline_rows(model, va, vb, gts, rng):
    def path(v, mode):
        tag = model if v == "v1" else f"{model}@{v}"
        return Path("outputs/pipeline") / f"pipeline__{tag}__{mode}.jsonl"

    rows = []
    for mode, br in (("omit", "B"), ("hedge", "B'")):
        pa, pb = path(va, mode), path(vb, mode)
        if not (pa.exists() and pb.exists()):
            continue
        S = {}
        for v, p in ((va, pa), (vb, pb)):
            S[v] = {}
            for line in open(p, encoding="utf-8"):
                if line.strip():
                    o = json.loads(line)
                    if o["id"] in gts:
                        S[v][o["id"]] = cp.score(o["output"], gts[o["id"]])
        ids = sorted(set(S[va]) & set(S[vb]))
        get = lambda v, k: np.array([S[v][i][k] for i in ids], dtype=float)
        bad = lambda v: get(v, "E1") + get(v, "sai")
        specs = [("%bd_co_so_sai", get(va, "co_so_sai"), get(vb, "co_so_sai"), None, -1),
                 ("%so_sai", np.stack([bad(va), get(va, "n_so")], 1), np.stack([bad(vb), get(vb, "n_so")], 1),
                  lambda x, y: y[:, 0].sum() / max(1, y[:, 1].sum()) - x[:, 0].sum() / max(1, x[:, 1].sum()), -1),
                 ("do_phu_%", get(va, "do_phu"), get(vb, "do_phu"), None, 1),
                 ("%thieu_don_vi", get(va, "thieu_don_vi"), get(vb, "thieu_don_vi"), None, -1),
                 ("so_con_so_tb", get(va, "n_so"), get(vb, "n_so"), None, 0)]
        block = []
        for name, a, b, stat, sign in specs:
            if stat is None:
                d, lo, hi, p = paired(a, b, rng=rng)
                av, bv = a.mean(), b.mean()
                diff = (b - a)
            else:
                d, lo, hi, p = paired(a, b, stat=stat, rng=rng)
                av, bv = a[:, 0].sum() / a[:, 1].sum(), b[:, 0].sum() / b[:, 1].sum()
                diff = b[:, 0] / np.maximum(1, b[:, 1]) - a[:, 0] / np.maximum(1, a[:, 1])
            better = int(np.sum(sign * diff > 1e-9)) if sign else None
            worse = int(np.sum(sign * diff < -1e-9)) if sign else None
            block.append({"nhanh": br, "chi_so": name, "n": len(ids), "a": av, "b": bv, "hieu": d, "lo": lo, "hi": hi,
                          "p": p, "thang": better, "thua": worse})
        for r, q in zip(block, holm(np.array([r["p"] for r in block]))):
            r["p_holm"] = q
        rows += block
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen3-VL-2B-Instruct")
    ap.add_argument("--a", default="v1")
    ap.add_argument("--b", default="v2")
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)
    A, B = load_extract(args.model, args.a), load_extract(args.model, args.b)
    ids = sorted(set(A) & set(B))
    L = [f"# Kiểm định ghép cặp {args.model}: prompt {args.a} → {args.b}\n",
         f"Hiệu = {args.b} − {args.a}. CI 95% bootstrap ghép cặp theo biểu đồ ({N} lần); p = kiểm định hoán vị ghép cặp "
         f"hai phía ({N} lần); p_Holm hiệu chỉnh đa so sánh trong bảng. Thắng/thua = số biểu đồ {args.b} tốt hơn/kém hơn {args.a}.\n"]
    csv_rows = []

    def emit(title, rows, pct_keys):
        L.append(f"\n## {title}\n")
        hdr = "| chỉ số | n | " + args.a + " | " + args.b + " | hiệu | CI 95% | p | p_Holm | thắng / thua / hoà |"
        L.append(hdr); L.append("|" + "---|" * 9)
        for r in rows:
            pct = r["chi_so"] in pct_keys
            sc = (lambda x: f"{100 * x:.1f}") if pct else (lambda x: f"{x:.3f}")
            tl = "" if r.get("thang") is None else f"{r['thang']} / {r['thua']}" + (f" / {r['hoa']}" if "hoa" in r else "")
            L.append(f"| {r.get('nhanh', '') + ' ' if r.get('nhanh') else ''}{r['chi_so']} | {r['n']} | {sc(r['a'])} | {sc(r['b'])} | "
                     f"{fmt(r['hieu'], pct)} | [{fmt(r['lo'], pct)}; {fmt(r['hi'], pct)}] | {r['p']:.3f} | "
                     f"{r.get('p_holm', float('nan')):.3f} | {tl} |")
            csv_rows.append({"bang": title, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}})

    emit(f"Bước 1 – tất cả biểu đồ có nhãn", extract_table(A, B, ids, rng), {"%điểm thiếu (nới)"})
    clean = [i for i in ids if A[i]["clean"]]
    emit(f"Bước 1 – tập sạch (có ghi số, không trùng)", extract_table(A, B, clean, rng), {"%điểm thiếu (nới)"})
    L.append("\n## Bước 1 – theo loại biểu đồ (không hiệu chỉnh Holm; n nhỏ, chỉ để định hướng)\n")
    L.append(f"| loại | n | chỉ số | {args.a} | {args.b} | hiệu | CI 95% | p | thắng / thua / hoà |")
    L.append("|" + "---|" * 9)
    for t in sorted({A[i]["chart_type"] for i in ids}):
        tid = [i for i in ids if A[i]["chart_type"] == t]
        for r in extract_table(A, B, tid, rng, with_holm=False):
            if r["chi_so"] in ("RA@5% nới", "RNSS nới", "Đơn vị đúng chặt", "%điểm thiếu (nới)"):
                pct = r["chi_so"] == "%điểm thiếu (nới)"
                sc = (lambda x: f"{100 * x:.1f}") if pct else (lambda x: f"{x:.3f}")
                L.append(f"| {t} | {r['n']} | {r['chi_so']} | {sc(r['a'])} | {sc(r['b'])} | {fmt(r['hieu'], pct)} | "
                         f"[{fmt(r['lo'], pct)}; {fmt(r['hi'], pct)}] | {r['p']:.3f} | {r['thang']} / {r['thua']} / {r['hoa']} |")
                csv_rows.append({"bang": f"theo_loai_{t}", **{k: (round(v, 4) if isinstance(v, float) else v)
                                                             for k, v in r.items()}})
    gts = cp.load_labels()
    pr = pipeline_rows(args.model, args.a, args.b, gts, rng)
    if pr:
        emit("Pipeline (bước 2–3) dùng bảng của từng phiên bản – B = bỏ số bị gắn cờ, B' = đọc kèm 'khoảng'", pr,
             {"%bd_co_so_sai", "%so_sai", "do_phu_%", "%thieu_don_vi"})
    out = RES / f"paired_{args.a}_{args.b}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    keys = list(dict.fromkeys(k for r in csv_rows for k in r))
    with open(RES / f"paired_{args.a}_{args.b}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(csv_rows)
    print("\n".join(L))
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
