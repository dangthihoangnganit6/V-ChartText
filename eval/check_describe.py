"""Kiểm tra bán tự động các con số trong mô tả trực tiếp (prompt 'describe').

  python eval/check_describe.py outputs/Qwen3-VL-2B-Instruct__describe__v1.jsonl

Mỗi con số trong mô tả được xếp vào:
  ok          : khớp một giá trị trong bảng nhãn (sai số <= 5%) hoặc là nhãn trục x (năm...)
  E1_dinh_dang: khớp sau khi nhân/chia 10, 100, 1000 -> đọc nhầm dấu phân cách / bậc
  chua_khop   : không khớp giá trị nào -> có thể là số suy ra (tổng, hiệu, %) hoặc số bịa.
                Người chấm xem lại cột này bằng tay và gán E2/E6 trong errors_manual.csv.
Ngoài ra: có nhắc đơn vị trục y không (E3), có trả lời bằng tiếng Việt không (E9).

Kết quả: eval/results/<tên>__numbers.csv và eval/results/<tên>__desc_summary.csv
"""
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vn_number import alt_readings, find_numbers, is_scale_error, rel_err  # noqa: E402

VI_CHARS = set("ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")


def norm(s):
    return unicodedata.normalize("NFC", str(s or "")).lower()


def is_vietnamese(text):
    t = norm(text)
    return sum(c in VI_CHARS for c in t) / max(1, len(t)) > 0.02


def main(path):
    labels = {}
    for p in Path("data/labels").glob("*.json"):
        if not p.name.startswith("example_"):
            r = json.loads(p.read_text(encoding="utf-8"))
            if r.get("data") and r.get("status") != "todo":  # chỉ chấm ảnh đã gán nhãn
                labels[r["id"]] = r
    num_rows, summ = [], []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        o = json.loads(line)
        gt = labels.get(o["id"])
        if not gt:
            continue
        text = o["output"]
        vals = [d["y"] for d in gt["data"]]
        xs = {norm(d["x"]) for d in gt["data"]}
        cnt = {"ok": 0, "E1_dinh_dang": 0, "chua_khop": 0}
        for tok in find_numbers(text):
            if norm(tok) in xs:
                continue  # nhãn trục x (năm, tháng) -> không tính
            reads = alt_readings(tok)
            if any(rel_err(r, v) <= 0.05 for r in reads for v in vals):
                cls = "ok"
            elif any(is_scale_error(r, v) for r in reads for v in vals):
                cls = "E1_dinh_dang"
            else:
                cls = "chua_khop"
            cnt[cls] += 1
            num_rows.append({"id": o["id"], "chart_type": gt["chart_type"], "number": tok, "class": cls})
        unit = norm((gt.get("y_axis") or {}).get("unit"))
        n = sum(cnt.values())
        summ.append({
            "id": o["id"], "chart_type": gt["chart_type"], "n_numbers": n, **cnt,
            "pct_ok": round(cnt["ok"] / n, 3) if n else None,
            "E3_thieu_don_vi": int(bool(unit) and unit not in norm(text)),
            "E9_khong_phai_tieng_viet": int(not is_vietnamese(text)),
            "n_words": len(text.split()),
        })
    name = Path(path).stem
    res = Path("eval/results")
    res.mkdir(parents=True, exist_ok=True)
    for fn, rows in ((f"{name}__numbers.csv", num_rows), (f"{name}__desc_summary.csv", summ)):
        if rows:
            with open(res / fn, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    tot = {k: sum(s[k] for s in summ) for k in ("n_numbers", "ok", "E1_dinh_dang", "chua_khop",
                                                 "E3_thieu_don_vi", "E9_khong_phai_tieng_viet")}
    print(name, f"({len(summ)} biểu đồ)", tot)


if __name__ == "__main__":
    main(sys.argv[1])
