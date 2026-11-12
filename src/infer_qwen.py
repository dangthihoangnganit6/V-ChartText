"""Chạy zero-shot Qwen-VL (Qwen3-VL hoặc Qwen2-VL) trên bộ dữ liệu.

Ví dụ (Colab T4):
  python src/infer_qwen.py --model Qwen/Qwen3-VL-2B-Instruct --task describe
  python src/infer_qwen.py --model Qwen/Qwen3-VL-4B-Instruct --task extract --limit 5
  python src/infer_qwen.py --model Qwen/Qwen2-VL-2B-Instruct --task describe

Cần: pip install "transformers>=4.57.0" accelerate pillow
"""
import argparse
import platform

import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

from common import Timer, append_result, done_ids, list_images
from prompts import PROMPT_VERSION, PROMPTS


def pick_dtype(name):
    """T4/P100 (compute capability < 8) không có bf16 thật: torch.cuda.is_bf16_supported() vẫn
    trả True vì giả lập, nhưng chạy rất chậm. 'auto' = bf16 trên Ampere+, fp16 trên GPU cũ."""
    if name != "auto":
        return {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}[name]
    if torch.cuda.is_available() and torch.cuda.get_device_capability(0)[0] >= 8:
        return torch.bfloat16
    return torch.float16


def load_img(path, max_side):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    s = max_side / max(w, h)
    if s < 1:
        img = img.resize((int(w * s), int(h * s)), Image.BICUBIC)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-VL-2B-Instruct")
    ap.add_argument("--task", choices=list(PROMPTS), default="describe")
    ap.add_argument("--labels", default="data/labels")
    ap.add_argument("--images", default="data/images")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max_side", type=int, default=1280, help="cạnh dài tối đa của ảnh (px)")
    ap.add_argument("--max_new_tokens", type=int, default=2048)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dtype", default="auto", choices=["auto", "fp16", "bf16", "fp32"])
    ap.add_argument("--ids", default="", help="chỉ chạy các id này, cách nhau bởi dấu phẩy")
    args = ap.parse_args()

    short = args.model.split("/")[-1]
    out = args.out or f"outputs/{short}__{args.task}__{PROMPT_VERSION}.jsonl"

    dtype = pick_dtype(args.dtype)
    print("dtype:", dtype)
    model = AutoModelForImageTextToText.from_pretrained(args.model, dtype=dtype, device_map="auto").eval()
    processor = AutoProcessor.from_pretrained(args.model)

    items = list_images(args.labels, args.images)
    skip = done_ids(out)
    items = [it for it in items if it[0] not in skip]
    if args.ids:
        want = {x.strip() for x in args.ids.split(",")}
        items = [it for it in items if it[0] in want]
    if args.limit:
        items = items[: args.limit]
    print(f"{len(items)} ảnh cần chạy -> {out}")

    for cid, path in items:
        messages = [{"role": "user", "content": [
            {"type": "image", "image": load_img(path, args.max_side)},
            {"type": "text", "text": PROMPTS[args.task]},
        ]}]
        inputs = processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt").to(model.device)
        with Timer() as t, torch.inference_mode():
            gen = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
        text = processor.batch_decode(gen[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0]
        append_result(out, {
            "id": cid, "model": args.model, "task": args.task, "prompt_version": PROMPT_VERSION,
            "output": text, "latency_s": t.sec, "max_side": args.max_side, "dtype": str(dtype),
            "n_new_tokens": int(gen.shape[1] - inputs.input_ids.shape[1]),
            "max_new_tokens": args.max_new_tokens,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else platform.processor(),
        })
        print(cid, f"{t.sec}s")


if __name__ == "__main__":
    main()
