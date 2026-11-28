"""Tìm các output bị cắt vì chạm max_new_tokens, sao lưu file gốc rồi xoá các dòng đó
để infer_*.py chạy lại đúng những id này (script bỏ qua id đã có trong file).

  python src/find_truncated.py outputs/Qwen3-VL-2B-Instruct__extract__v1.jsonl --drop
  python src/find_truncated.py outputs/Vintern-1B-v3_5__*.jsonl --tokenizer 5CD-AI/Vintern-1B-v3_5 --drop

Qwen: dùng trường n_new_tokens đã ghi sẵn. Vintern (bản chạy cũ không ghi n_new_tokens):
đếm lại bằng tokenizer, coi là bị cắt nếu >= limit - margin.
In ra danh sách id, cách nhau bởi dấu phẩy, để dùng với --ids.
"""
import argparse
import json
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--limit", type=int, default=768, help="max_new_tokens của lần chạy cũ")
    ap.add_argument("--margin", type=int, default=8, help="dung sai khi đếm lại token")
    ap.add_argument("--tokenizer", default=None, help="đếm lại token khi file không có n_new_tokens")
    ap.add_argument("--backup", default="outputs_v768", help="thư mục sao lưu file gốc")
    ap.add_argument("--drop", action="store_true", help="xoá các dòng bị cắt khỏi file")
    args = ap.parse_args()

    tok = None
    if args.tokenizer:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True, use_fast=False)

    all_ids = {}
    for f in args.files:
        rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        cut = []
        for r in rows:
            n = r.get("n_new_tokens")
            if n is None:
                if tok is None:
                    raise SystemExit(f"{f}: không có n_new_tokens, cần --tokenizer")
                n = len(tok(r["output"], add_special_tokens=False).input_ids)
            if n >= args.limit - (args.margin if r.get("n_new_tokens") is None else 0):
                cut.append(r["id"])
        print(f"{Path(f).name}: {len(cut)}/{len(rows)} bị cắt")
        print("  " + ",".join(cut))
        all_ids[f] = cut
        if args.drop and cut:
            bk = Path(args.backup)
            bk.mkdir(parents=True, exist_ok=True)
            if not (bk / Path(f).name).exists():  # chỉ sao lưu bản gốc lần đầu
                shutil.copy(f, bk / Path(f).name)
            keep = [r for r in rows if r["id"] not in set(cut)]
            with open(f, "w", encoding="utf-8") as fo:
                for r in keep:
                    fo.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"  đã xoá {len(cut)} dòng, sao lưu gốc ở {bk / Path(f).name}")
    Path("rerun_ids.json").write_text(json.dumps(all_ids, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
