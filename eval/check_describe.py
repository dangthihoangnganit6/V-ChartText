"""Kiểm tra bán tự động các con số trong mô tả trực tiếp (prompt 'describe').

  python eval/check_describe.py outputs/Qwen3-VL-2B-Instruct__describe__v1.jsonl [file2 ...]

Mỗi con số trong mô tả được xếp vào:
  ok          : khớp một giá trị trong bảng nhãn (sai số <= 5%) hoặc là nhãn trục x (năm...)
  E1_dinh_dang: khớp sau khi nhân/chia 10, 100, 1000 -> đọc nhầm dấu phân cách / bậc
  chua_khop   : không khớp giá trị nào -> có thể là số suy ra (tổng, hiệu, %) hoặc số bịa.
                Người chấm xem lại cột này bằng tay và gán E2/E6 trong errors_manual.csv.
Ngoài ra: có nhắc đơn vị trục y không (E3), có trả lời bằng tiếng Việt không (E9).

Cờ không cần nhãn, tính trên MỌI biểu đồ:
  hit_limit      : chạm max_new_tokens
  loop           : một câu (>= 20 ký tự) lặp >= 3 lần, một con số lặp >= 8 lần liên tiếp,
                   hoặc một cụm 20 từ lặp >= 3 lần
  chen_tieng_anh : có từ tiếng Anh thường gặp (chart, bar, line, axis, ...)

Kết quả: eval/results/<tên>__numbers.csv, <tên>__desc_summary.csv (ảnh đã gán nhãn)
         và <tên>__desc_all.csv (mọi ảnh, chỉ các cờ không cần nhãn)
"""
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vn_number import alt_readings, find_numbers, is_scale_error, rel_err  # noqa: E402

VI_CHARS = set("ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")
EN_WORDS = re.compile(r"\b(chart|bar|line|pie|graph|axis|legend|the|and|of|shows?|data|value)\b", re.I)
LIMIT_MARGIN = 8


def norm(s):
    return unicodedata.normalize("NFC", str(s or "")).lower()


def is_vietnamese(text):
    t = norm(text)
    return sum(c in VI_CHARS for c in t) / max(1, len(t)) > 0.02


def loop_flags(text):
    sents = [s.strip() for s in re.split(r"[.\n;]", text) if len(s.strip()) >= 20]
    sent_rep = max(Counter(sents).values(), default=0)
    nums = find_numbers(text)
    run = best = 0
    for a, b in zip(nums, nums[1:]):
        run = run + 1 if a == b else 0
        best = max(best, run + 1 if run else 1)
    words = text.split()
    grams = Counter(tuple(words[i:i + 20]) for i in range(len(words) - 19))
    gram_rep = max(grams.values(), default=0)
    return {"sentence_repeat": sent_rep, "number_run": best if nums else 0, "ngram20_repeat": gram_rep,
            "loop": int(sent_rep >= 3 or best >= 8 or gram_rep >= 3)}


def flags(o):
    text = o["output"]
    n, mx = o.get("n_new_tokens"), o.get("max_new_tokens")
    en = sorted({m.group(0).lower() for m in EN_WORDS.finditer(text)})
    return {"hit_limit": int(n is not None and mx is not None and n >= mx - LIMIT_MARGIN),
            **loop_flags(text), "chen_tieng_anh": int(bool(en)), "tu_tieng_anh": " ".join(en),
            "n_words": len(text.split()), "n_numbers_all": len(find_numbers(text))}


def load_labels():
    every, done = {}, {}
    for p in Path("data/labels").glob("*.json"):
        if p.name.startswith("example_"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        every[r["id"]] = r
        if r.get("data") and r.get("status") != "todo":  # chỉ chấm số trên ảnh đã gán nhãn
            done[r["id"]] = r
    return every, done


def main(path, every, done):
    outs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    outs = [o for o in outs if o["id"] in every]  # bỏ id không còn trong bộ dữ liệu
    name = Path(path).stem

    allrows = [{"id": o["id"], "chart_type": every[o["id"]]["chart_type"], **flags(o)} for o in outs]
    n = len(allrows)
    print(f"\n=== {name}")
    print(f"  [Mọi biểu đồ, không cần nhãn] n = {n}: chạm giới hạn {sum(r['hit_limit'] for r in allrows)} | "
          f"lặp {sum(r['loop'] for r in allrows)} | chen tiếng Anh {sum(r['chen_tieng_anh'] for r in allrows)} | "
          f"không phải tiếng Việt {sum(not is_vietnamese(o['output']) for o in outs)} | "
          f"không có con số nào {sum(r['n_numbers_all'] == 0 for r in allrows)} | "
          f"số từ TB {sum(r['n_words'] for r in allrows) / max(1, n):.0f}")

    num_rows, summ = [], []
    for o in outs:
        gt = done.get(o["id"])
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
        k = sum(cnt.values())
        f = flags(o)
        summ.append({
            "id": o["id"], "chart_type": gt["chart_type"], "n_numbers": k, **cnt,
            "pct_ok": round(cnt["ok"] / k, 3) if k else None,
            "E3_thieu_don_vi": int(bool(unit) and unit not in norm(text)),
            "E9_khong_phai_tieng_viet": int(not is_vietnamese(text)),
            "n_words": f["n_words"], "hit_limit": f["hit_limit"], "loop": f["loop"],
            "chen_tieng_anh": f["chen_tieng_anh"],
        })

    res = Path("eval/results")
    res.mkdir(parents=True, exist_ok=True)
    for fn, rows in ((f"{name}__numbers.csv", num_rows), (f"{name}__desc_summary.csv", summ),
                     (f"{name}__desc_all.csv", allrows)):
        if rows:
            with open(res / fn, "w", newline="", encoding="utf-8-sig") as fo:
                w = csv.DictWriter(fo, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    if not summ:
        print("  (chưa có biểu đồ nào đã gán nhãn để chấm số)")
        return
    tot = {k: sum(s[k] for s in summ) for k in ("n_numbers", "ok", "E1_dinh_dang", "chua_khop",
                                                 "E3_thieu_don_vi", "E9_khong_phai_tieng_viet")}
    print(f"  [Ảnh đã gán nhãn] {len(summ)} biểu đồ: {tot}")


if __name__ == "__main__":
    every, done = load_labels()
    for p in sys.argv[1:]:
        main(p, every, done)
