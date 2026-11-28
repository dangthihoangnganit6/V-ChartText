"""Tổng hợp kết quả Mức 1 thành bảng cho báo cáo (mục 20).

Chạy SAU score_extract.py và check_describe.py cho mọi file trong outputs/:
  python eval/summarize.py
-> eval/results/summary_models.csv    (hàng = mô hình)
-> eval/results/summary_by_type.csv   (mô hình x loại biểu đồ)
-> eval/results/summary_errors.csv    (tần suất mã lỗi E0-E9, gộp tự động + chấm tay)
-> eval/results/summary_errors_noi.csv (tần suất mã lỗi theo chế độ chấm nới)
và in bảng markdown để dán vào báo cáo.
Chấm tay: điền eval/errors_manual.csv (cùng cột với errors_manual_template.csv).
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

RES = Path("eval/results")


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def model_of(stem):
    """'Qwen..__extract__v2__charts' -> 'Qwen..@v2' (prompt v1 giữ tên cũ để không đổi bảng cũ)."""
    parts = stem.split("__")
    return parts[0] + (f"@{parts[2]}" if len(parts) > 2 and parts[2] != "v1" else "")


def main():
    models = defaultdict(dict)
    by_type = defaultdict(dict)
    errors = defaultdict(Counter)
    errors_noi = defaultdict(Counter)

    for p in RES.glob("*__extract__*__charts.csv"):
        m, rows = model_of(p.stem), read_csv(p)
        models[m].update({
            "n_charts_extract": len(rows),
            "json_ok": mean([fnum(r["json_ok"]) for r in rows]),
            "RA@5%": mean([fnum(r.get("ra5")) for r in rows]),
            "RNSS": mean([fnum(r.get("rnss")) for r in rows]),
            "type_ok": mean([fnum(r.get("type_ok")) for r in rows]),
            "unit_ok": mean([fnum(r.get("unit_ok")) for r in rows]),
            "RA@5%_noi": mean([fnum(r.get("ra5_lenient")) for r in rows]),
            "RNSS_noi": mean([fnum(r.get("rnss_lenient")) for r in rows]),
            "unit_ok_noi": mean([fnum(r.get("unit_ok_lenient")) for r in rows]),
            # tập con sạch: ảnh có in số trên hình và không trùng số liệu với ảnh khác
            "n_sach": len(clean := [r for r in rows if r.get("values_shown", "1") == "1" and r.get("duplicate", "0") == "0"]),
            "RA@5%_sach": mean([fnum(r.get("ra5")) for r in clean]),
            "RA@5%_noi_sach": mean([fnum(r.get("ra5_lenient")) for r in clean]),
        })
        groups = defaultdict(list)
        for r in rows:
            groups[r["chart_type"]].append(r)
        for t, rs in groups.items():
            by_type[(m, t)].update({"n": len(rs), "RA@5%": mean([fnum(r.get("ra5")) for r in rs]),
                                    "RA@5%_noi": mean([fnum(r.get("ra5_lenient")) for r in rs]),
                                    "RNSS": mean([fnum(r.get("rnss")) for r in rs])})
    # thống kê không cần nhãn, trên mọi biểu đồ (file __all.csv của score_extract.py)
    for p in RES.glob("*__extract__*__all.csv"):
        m, rows = model_of(p.stem), read_csv(p)
        parsed = [r for r in rows if r["json_status"] != "fail"]
        models[m].update({
            "n_tat_ca": len(rows),
            "json_ok_tat_ca": mean([float(r["json_status"] == "ok") for r in rows]),
            "json_cuu_duoc": sum(r["json_status"] == "salvaged" for r in rows),
            "extract_cham_gioi_han": sum(r["hit_limit"] == "1" for r in rows),
            "extract_lap": sum(r["loop"] == "1" for r in rows),
            "loai_dung_tat_ca": mean([float(r["pred_type"] == r["chart_type"]) for r in parsed]),
            "loai_khong_hop_le": sum(r["type_valid"] == "0" for r in parsed),
        })
        for t in {r["chart_type"] for r in rows}:
            rs = [r for r in parsed if r["chart_type"] == t]
            by_type[(m, t)]["loai_dung_tat_ca"] = mean([float(r["pred_type"] == t) for r in rs])
    for p in RES.glob("*__extract__*__points.csv"):
        m = model_of(p.stem)
        for r in read_csv(p):
            if r["err"]:
                errors[m][r["err"].split("_")[0]] += 1
            if r.get("err_lenient"):
                errors_noi[m][r["err_lenient"].split("_")[0]] += 1

    for p in RES.glob("*__describe__*__desc_summary.csv"):
        m, rows = model_of(p.stem), read_csv(p)
        n_num = sum(int(r["n_numbers"]) for r in rows)
        models[m].update({
            "n_charts_describe": len(rows),
            "desc_%so_dung": round(sum(int(r["ok"]) for r in rows) / n_num, 3) if n_num else None,
            "desc_so_chua_khop": sum(int(r["chua_khop"]) for r in rows),
            "desc_E1": sum(int(r["E1_dinh_dang"]) for r in rows),
            "desc_E3_thieu_don_vi_%": mean([fnum(r["E3_thieu_don_vi"]) for r in rows]),
            "desc_E9_khong_TV_%": mean([fnum(r["E9_khong_phai_tieng_viet"]) for r in rows]),
            "desc_so_tu_tb": mean([fnum(r["n_words"]) for r in rows]),
        })
        pa = RES / p.name.replace("__desc_summary.csv", "__desc_all.csv")
        if pa.exists():
            ra = read_csv(pa)
            models[m].update({
                "desc_lap_tat_ca": sum(r["loop"] == "1" for r in ra),
                "desc_chen_tieng_Anh_%": mean([float(r["chen_tieng_anh"]) for r in ra]),
                "desc_khong_co_so": sum(r["n_numbers_all"] == "0" for r in ra),
            })
        groups = defaultdict(list)
        for r in rows:
            groups[r["chart_type"]].append(r)
        for t, rs in groups.items():
            nn = sum(int(r["n_numbers"]) for r in rs)
            by_type[(m, t)]["desc_%so_dung"] = round(sum(int(r["ok"]) for r in rs) / nn, 3) if nn else None

    lat = defaultdict(list)
    for p in Path("outputs").glob("*.jsonl"):
        lat[model_of(p.stem)] += [json.loads(l)["latency_s"] for l in open(p, encoding="utf-8") if l.strip()]
    for m, xs in lat.items():
        models[m]["giay_moi_lan_goi"] = mean(xs)

    manual = Path("eval/errors_manual.csv")
    if manual.exists():
        for r in read_csv(manual):
            errors[r["model"]][r["error_code"].strip().upper()] += 1

    RES.mkdir(parents=True, exist_ok=True)
    _write(RES / "summary_models.csv", [{"model": m, **v} for m, v in sorted(models.items())])
    _write(RES / "summary_by_type.csv", [{"model": m, "chart_type": t, **v} for (m, t), v in sorted(by_type.items())])
    codes = sorted({c for cnt in errors.values() for c in cnt})
    _write(RES / "summary_errors.csv", [{"model": m, **{c: cnt.get(c, 0) for c in codes}} for m, cnt in sorted(errors.items())])
    codes_n = sorted({c for cnt in errors_noi.values() for c in cnt})
    _write(RES / "summary_errors_noi.csv", [{"model": m, **{c: cnt.get(c, 0) for c in codes_n}}
                                             for m, cnt in sorted(errors_noi.items())])

    for title, path in (("Theo mô hình", "summary_models.csv"), ("Theo loại biểu đồ", "summary_by_type.csv"),
                        ("Tần suất lỗi (chặt)", "summary_errors.csv"),
                        ("Tần suất lỗi (nới)", "summary_errors_noi.csv")):
        p = RES / path
        if p.exists():
            rows = read_csv(p)
            if rows:
                print(f"\n### {title}\n")
                print("| " + " | ".join(rows[0]) + " |")
                print("|" + "---|" * len(rows[0]))
                for r in rows:
                    print("| " + " | ".join(str(v) for v in r.values()) + " |")


def _write(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
