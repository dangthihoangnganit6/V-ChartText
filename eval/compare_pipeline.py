"""Thí nghiệm Mức 2: pipeline 4 bước có giảm lỗi số liệu so với VLM mô tả trực tiếp không?

  python eval/compare_pipeline.py
  (chạy sau src/pipeline/run.py cho --source pred và --source gold)

Các nhánh (tự tìm file, nhánh nào thiếu thì bỏ qua):
  A_<mô hình>   : outputs/<mô hình>__describe__v1.jsonl          VLM mô tả trực tiếp từ ảnh (Mức 1)
  B_<mô hình>   : outputs/pipeline/pipeline__<mô hình>__omit.jsonl  pipeline: bước 1 = output extract của chính mô hình đó
  B'_<mô hình>  : ...__hedge.jsonl                                  như B nhưng đọc cả số bị gắn cờ, kèm "khoảng"
  C_nhan        : outputs/pipeline/pipeline__gold__omit.jsonl       pipeline với bảng nhãn thay bước 1 (mức trần)

Chấm MỌI nhánh bằng cùng một luật (giống check_describe.py, thêm 2 điểm cho công bằng):
  - con số trùng với số trong nhãn chữ của biểu đồ (tiêu đề, đơn vị, tên chuỗi, nhãn trục x) không tính
    (vd "Cơ cấu năm 2010", "15-24 tuổi");
  - mỗi con số còn lại: ok (khớp một giá trị nhãn, sai số <= 5%) | E1 (lệch đúng 10/100/1000 lần) | sai (không khớp).
Chỉ số mỗi nhánh:
  %so_sai      : (E1 + sai) / tổng số con số            -> độ chính xác của các con số được đọc ra
  %bd_co_so_sai: tỉ lệ biểu đồ có >= 1 con số sai        -> chỉ số chính
  do_phu       : tỉ lệ giá trị nhãn được nhắc đúng       -> tránh "đúng vì nói ít số"
  %thieu_don_vi: mô tả không nhắc đơn vị trục y
Khoảng tin cậy 95%: bootstrap ghép cặp theo biểu đồ (2000 lần), cho hiệu B - A.
Kết quả: eval/results/compare_pipeline.csv, compare_by_type.csv, compare_examples.md
"""
import csv
import json
import random
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vn_number import alt_readings, find_numbers, is_scale_error, rel_err  # noqa: E402

OUT = Path("outputs")
RES = Path("eval/results")
N_BOOT, SEED = 2000, 2026


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s or "")).lower()).strip()


def load_labels():
    out = {}
    for p in sorted(Path("data/labels").glob("*.json")):
        if p.name.startswith("example_"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("status") in ("todo", "excluded") or not r.get("data"):
            continue
        out[r["id"]] = r
    return out


def label_number_tokens(gt):
    texts = [gt.get("title") or "", str((gt.get("y_axis") or {}).get("unit") or ""),
             str((gt.get("y2_axis") or {}).get("unit") or "")]
    texts += [str(d["series"]) for d in gt["data"]] + [str(d["x"]) for d in gt["data"]]
    toks = set()
    for t in texts:
        toks |= {norm(n) for n in find_numbers(t)}
    return toks


def score(text, gt):
    vals = [float(d["y"]) for d in gt["data"]]
    skip = label_number_tokens(gt)
    ok = e1 = bad = 0
    hit = set()
    for tok in find_numbers(text):
        if norm(tok) in skip:
            continue
        reads = alt_readings(tok)
        match = [i for i, v in enumerate(vals) if any(rel_err(r, v) <= 0.05 for r in reads)]
        if match:
            ok += 1
            hit.update(match)
        elif any(is_scale_error(r, v) for r in reads for v in vals):
            e1 += 1
        else:
            bad += 1
    unit = norm((gt.get("y_axis") or {}).get("unit"))
    t = norm(text)
    unit_missing = int(bool(unit) and unit not in t and unit.replace("tỷ", "tỉ") not in t.replace("tỷ", "tỉ"))
    return {"n_so": ok + e1 + bad, "ok": ok, "E1": e1, "sai": bad, "co_so_sai": int(e1 + bad > 0),
            "do_phu": len(hit) / len(vals), "thieu_don_vi": unit_missing, "so_tu": len(text.split())}


def branches():
    br = {}
    for p in sorted(OUT.glob("*__describe__v1.jsonl")):
        br["A_" + p.stem.split("__")[0]] = p
    for p in sorted((OUT / "pipeline").glob("pipeline__*__omit.jsonl")):
        name = p.stem.split("__")[1]
        br["C_nhan" if name == "gold" else "B_" + name] = p
    for p in sorted((OUT / "pipeline").glob("pipeline__*__hedge.jsonl")):
        name = p.stem.split("__")[1]
        if name != "gold":
            br["B'_" + name] = p
    return br


def agg(rows):
    n = sum(r["n_so"] for r in rows)
    return {"n_bd": len(rows), "n_so": n,
            "%so_sai": round(100 * sum(r["E1"] + r["sai"] for r in rows) / max(1, n), 1),
            "%so_E1": round(100 * sum(r["E1"] for r in rows) / max(1, n), 1),
            "%bd_co_so_sai": round(100 * sum(r["co_so_sai"] for r in rows) / max(1, len(rows)), 1),
            "do_phu_%": round(100 * sum(r["do_phu"] for r in rows) / max(1, len(rows)), 1),
            "%thieu_don_vi": round(100 * sum(r["thieu_don_vi"] for r in rows) / max(1, len(rows)), 1),
            "so_tu_tb": round(sum(r["so_tu"] for r in rows) / max(1, len(rows)))}


def boot_diff(a_rows, b_rows, key):
    """Hiệu B - A (điểm %) với CI 95% bootstrap ghép cặp. key: 'bd' (tỉ lệ bđ có số sai) | 'so' (tỉ lệ số sai)."""
    ids = sorted(set(a_rows) & set(b_rows))
    rng = random.Random(SEED)

    def stat(sample):
        if key == "bd":
            a = sum(a_rows[i]["co_so_sai"] for i in sample) / len(sample)
            b = sum(b_rows[i]["co_so_sai"] for i in sample) / len(sample)
        else:
            a = sum(a_rows[i]["E1"] + a_rows[i]["sai"] for i in sample) / max(1, sum(a_rows[i]["n_so"] for i in sample))
            b = sum(b_rows[i]["E1"] + b_rows[i]["sai"] for i in sample) / max(1, sum(b_rows[i]["n_so"] for i in sample))
        return 100 * (b - a)

    point = stat(ids)
    bs = sorted(stat([rng.choice(ids) for _ in ids]) for _ in range(N_BOOT))
    return round(point, 1), round(bs[int(0.025 * N_BOOT)], 1), round(bs[int(0.975 * N_BOOT)], 1)


def write(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def md(rows):
    keys = list(rows[0])
    print("| " + " | ".join(keys) + " |\n|" + "---|" * len(keys))
    for r in rows:
        print("| " + " | ".join(str(r[k]) for k in keys) + " |")


def main():
    gts = load_labels()
    clean = {i for i, g in gts.items() if g.get("values_shown_on_chart") is not False and not g.get("duplicate_of")}
    per = {}
    texts = {}
    for name, path in branches().items():
        per[name], texts[name] = {}, {}
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            o = json.loads(line)
            if o["id"] in gts:
                per[name][o["id"]] = score(o["output"], gts[o["id"]])
                texts[name][o["id"]] = o["output"]
    if not per:
        sys.exit("Không thấy file nào. Chạy src/pipeline/run.py trước.")

    table, by_type = [], []
    for subset, ids in (("tat_ca", set(gts)), ("sach", clean)):
        for name, rows in per.items():
            table.append({"nhanh": name, "tap": subset, **agg([rows[i] for i in rows if i in ids])})
    for name, rows in per.items():
        groups = defaultdict(list)
        for i, r in rows.items():
            groups[gts[i]["chart_type"]].append(r)
        for t, rs in sorted(groups.items()):
            by_type.append({"nhanh": name, "loai": t, **{k: v for k, v in agg(rs).items()
                                                        if k in ("n_bd", "%so_sai", "%bd_co_so_sai", "do_phu_%")}})
    diffs = []
    for name in per:
        if not name.startswith(("B_", "B'_")):
            continue
        model = name.split("_", 1)[1]
        a = per.get("A_" + model)
        if not a:
            continue
        for key in ("bd", "so"):
            d, lo, hi = boot_diff(a, per[name], key)
            diffs.append({"so_sanh": f"{name} - A_{model}",
                          "chi_so": "%bd_co_so_sai" if key == "bd" else "%so_sai", "hieu": d, "CI95": f"[{lo}; {hi}]"})
    RES.mkdir(parents=True, exist_ok=True)
    write(RES / "compare_pipeline.csv", table)
    write(RES / "compare_by_type.csv", by_type)
    if diffs:
        write(RES / "compare_diff.csv", diffs)

    print("### So sánh mô tả trực tiếp (A), pipeline (B) và pipeline + nhãn đúng (C)\n")
    md(table)
    if diffs:
        print("\n### Hiệu so với mô tả trực tiếp cùng mô hình (âm = pipeline ít lỗi hơn), CI 95% bootstrap\n")
        md(diffs)
    print("\n### Theo loại biểu đồ\n")
    md(by_type)

    # ví dụ trước / sau cho báo cáo
    ex_lines = ["# Ví dụ trước / sau (A = VLM mô tả trực tiếp, B = pipeline 4 bước)\n"]
    for model in [n[2:] for n in per if n.startswith("A_")]:
        a, b = per.get("A_" + model), per.get("B_" + model)
        if not a or not b:
            continue
        cand = [i for i in a if i in b and a[i]["sai"] + a[i]["E1"] >= 2 and b[i]["co_so_sai"] == 0
                and b[i]["do_phu"] >= 0.5 and i in clean]
        cand.sort(key=lambda i: -(a[i]["sai"] + a[i]["E1"]))
        seen_t = set()
        picks = []
        for i in cand:
            if gts[i]["chart_type"] not in seen_t:
                picks.append(i)
                seen_t.add(gts[i]["chart_type"])
        bad_b = [i for i in b if b[i]["co_so_sai"] and i in clean][:1]
        ex_lines.append(f"\n## {model}\n")
        for i in picks[:4] + bad_b:
            g = gts[i]
            tbl = "; ".join(f"{d['series']} / {d['x']}: {d['y']}" for d in g["data"][:12])
            tag = " (pipeline vẫn sai: lỗi từ bước 1)" if i in bad_b else ""
            ex_lines += [f"\n### {i} ({g['chart_type']}){tag}\n",
                         f"- Nhãn: {tbl}{' ...' if len(g['data']) > 12 else ''}",
                         f"- **A** ({a[i]['sai'] + a[i]['E1']} số sai / {a[i]['n_so']}): {texts['A_' + model][i]}",
                         f"- **B** ({b[i]['sai'] + b[i]['E1']} số sai / {b[i]['n_so']}): {texts['B_' + model][i]}"]
    (RES / "compare_examples.md").write_text("\n".join(ex_lines) + "\n", encoding="utf-8")
    print(f"\nVí dụ trước/sau: {RES / 'compare_examples.md'}")


if __name__ == "__main__":
    main()
