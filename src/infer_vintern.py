"""Chạy zero-shot Vintern-1B-v3.5 (5CD-AI, nền InternVL2.5-1B) trên bộ dữ liệu.

Ví dụ:
  python src/infer_vintern.py --task describe
  python src/infer_vintern.py --task extract --limit 5

Cần: pip install transformers timm einops sentencepiece pillow torchvision
Vintern dùng trust_remote_code (mã InternVL). Nếu lỗi khi nạp với transformers mới
(bản >= 4.57 cho Qwen3-VL), tạo môi trường/notebook Colab riêng và hạ transformers
xuống bản cũ hơn (vd 4.4x) thay vì dùng chung môi trường với Qwen3-VL.
"""
import argparse
import platform

import torch
import torchvision.transforms as T
from PIL import Image
from torchvision.transforms.functional import InterpolationMode
from transformers import AutoModel, AutoTokenizer

from common import Timer, append_result, done_ids, list_images
from prompts import PROMPT_VERSION, PROMPTS

MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


def pick_dtype(name):
    """T4/P100 (compute capability < 8) không có bf16 thật: torch.cuda.is_bf16_supported() vẫn
    trả True vì giả lập, nhưng chạy rất chậm. 'auto' = bf16 trên Ampere+, fp16 trên GPU cũ."""
    if name != "auto":
        return {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}[name]
    if torch.cuda.is_available() and torch.cuda.get_device_capability(0)[0] >= 8:
        return torch.bfloat16
    return torch.float16


def build_transform(size):
    return T.Compose([
        T.Lambda(lambda im: im.convert("RGB")),
        T.Resize((size, size), interpolation=InterpolationMode.BICUBIC),
        T.ToTensor(), T.Normalize(MEAN, STD)])


def find_closest_aspect_ratio(ar, ratios, w, h, size):
    best_diff, best = float("inf"), (1, 1)
    area = w * h
    for r in ratios:
        diff = abs(ar - r[0] / r[1])
        if diff < best_diff:
            best_diff, best = diff, r
        elif diff == best_diff and area > 0.5 * size * size * r[0] * r[1]:
            best = r
    return best


def dynamic_preprocess(img, min_num=1, max_num=6, size=448, use_thumbnail=True):
    w, h = img.size
    ratios = sorted({(i, j) for n in range(min_num, max_num + 1)
                     for i in range(1, n + 1) for j in range(1, n + 1)
                     if min_num <= i * j <= max_num}, key=lambda x: x[0] * x[1])
    r = find_closest_aspect_ratio(w / h, ratios, w, h, size)
    tw, th = size * r[0], size * r[1]
    resized = img.resize((tw, th))
    tiles = []
    for i in range(r[0] * r[1]):
        box = ((i % (tw // size)) * size, (i // (tw // size)) * size,
               ((i % (tw // size)) + 1) * size, ((i // (tw // size)) + 1) * size)
        tiles.append(resized.crop(box))
    if use_thumbnail and len(tiles) != 1:
        tiles.append(img.resize((size, size)))
    return tiles


def load_image(path, max_num=6, size=448):
    img = Image.open(path).convert("RGB")
    tf = build_transform(size)
    return torch.stack([tf(t) for t in dynamic_preprocess(img, max_num=max_num, size=size)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="5CD-AI/Vintern-1B-v3_5")
    ap.add_argument("--task", choices=list(PROMPTS), default="describe")
    ap.add_argument("--labels", default="data/labels")
    ap.add_argument("--images", default="data/images")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max_tiles", type=int, default=6)
    ap.add_argument("--max_new_tokens", type=int, default=2048)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dtype", default="auto", choices=["auto", "fp16", "bf16", "fp32"])
    ap.add_argument("--repetition_penalty", type=float, default=1.5,
                    help="model card khuyên 1.5; với --task extract nên thử 1.05 nếu JSON bị hỏng")
    ap.add_argument("--ids", default="", help="chỉ chạy các id này, cách nhau bởi dấu phẩy")
    args = ap.parse_args()

    short = args.model.split("/")[-1]
    out = args.out or f"outputs/{short}__{args.task}__{PROMPT_VERSION}.jsonl"
    dtype = pick_dtype(args.dtype)
    print("dtype:", dtype)

    model = AutoModel.from_pretrained(args.model, torch_dtype=dtype, low_cpu_mem_usage=True,
                                      trust_remote_code=True, use_flash_attn=False).eval().cuda()
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True, use_fast=False)
    gen_cfg = dict(max_new_tokens=args.max_new_tokens, do_sample=False, num_beams=1,
                   repetition_penalty=args.repetition_penalty)

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
        pv = load_image(path, max_num=args.max_tiles).to(dtype).cuda()
        q = "<image>\n" + PROMPTS[args.task]
        with Timer() as t, torch.inference_mode():
            text = model.chat(tok, pv, q, gen_cfg)
        # model.chat chỉ trả văn bản: đếm lại token bằng chính tokenizer của Vintern (xấp xỉ, sai lệch ±1-2)
        n_new = len(tok(text, add_special_tokens=False).input_ids)
        append_result(out, {
            "id": cid, "model": args.model, "task": args.task, "prompt_version": PROMPT_VERSION,
            "output": text, "latency_s": t.sec, "max_tiles": args.max_tiles, "dtype": str(dtype),
            "repetition_penalty": args.repetition_penalty,
            "n_new_tokens": n_new, "max_new_tokens": args.max_new_tokens,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else platform.processor(),
        })
        print(cid, f"{t.sec}s")


if __name__ == "__main__":
    main()
