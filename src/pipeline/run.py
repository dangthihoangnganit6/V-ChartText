"""Chạy pipeline 4 bước trên cả bộ dữ liệu (bước 1 lấy từ output extract đã có, không cần GPU).

  python src/pipeline/run.py --source pred --extract outputs/Qwen3-VL-2B-Instruct__extract__v1.jsonl
  python src/pipeline/run.py --source pred --extract outputs/Vintern-1B-v3_5__extract__v1.jsonl
  python src/pipeline/run.py --source gold          # nhánh C: bảng nhãn thay bước 1 (mức trần)
  thêm --uncertain hedge để đọc số bị gắn cờ kèm "khoảng" thay vì bỏ

-> outputs/pipeline/pipeline__<nguồn>__<cách xử lý>.jsonl, mỗi dòng:
   id, source, output (= mô tả diễn giải, dùng để chấm), levels{nghe_5s, nghe_30s, dien_giai},
   speech{...: văn bản đã đổi số thành chữ}, table (bảng sau bước 2), flags, n_uncertain
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "eval"))

from describe import describe  # noqa: E402
from score_extract import read_pred  # noqa: E402
from speech import speech_text  # noqa: E402
from verify import from_gold, from_pred, verify  # noqa: E402


def load_labels(label_dir):
    out = {}
    for p in sorted(Path(label_dir).glob("*.json")):
        if p.name.startswith("example_"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("status") in ("todo", "excluded") or not r.get("data"):
            continue
        out[r["id"]] = r
    return out


def process(raw_table, uncertain="omit"):
    t = verify(raw_table)
    lv = describe(t, uncertain)
    return t, lv


def run_one(cid, raw_table, source, uncertain):
    t, lv = process(raw_table, uncertain)
    levels = {k: lv[k] for k in ("nghe_5s", "nghe_30s", "dien_giai")}
    return {"id": cid, "source": source, "uncertain_mode": uncertain, "output": levels["dien_giai"],
            "levels": levels, "speech": {k: speech_text(v) for k, v in levels.items()},
            "table": t, "flags": t["flags"], "n_uncertain": t["n_uncertain"], "omitted": lv["omitted"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["pred", "gold"], default="pred")
    ap.add_argument("--extract", default="outputs/Qwen3-VL-2B-Instruct__extract__v1.jsonl")
    ap.add_argument("--labels", default="data/labels")
    ap.add_argument("--uncertain", choices=["omit", "hedge"], default="omit")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    labels = load_labels(a.labels)
    rows = []
    if a.source == "gold":
        name = "gold"
        for cid, rec in labels.items():
            rows.append(run_one(cid, from_gold(rec), "gold", a.uncertain))
    else:
        name = Path(a.extract).stem.split("__")[0]
        for line in open(a.extract, encoding="utf-8"):
            if not line.strip():
                continue
            o = json.loads(line)
            if o["id"] not in labels:
                continue
            pred, status = read_pred(o["output"])
            raw = from_pred(pred)
            r = run_one(o["id"], raw, name, a.uncertain)
            r["json_status"] = status
            rows.append(r)
    out = Path(a.out or f"outputs/pipeline/pipeline__{name}__{a.uncertain}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_unc = sum(r["n_uncertain"] > 0 for r in rows)
    print(f"{len(rows)} biểu đồ -> {out} | có điểm bị gắn cờ: {n_unc} | "
          f"số điểm bị gắn cờ: {sum(r['n_uncertain'] for r in rows)}")


if __name__ == "__main__":
    main()
