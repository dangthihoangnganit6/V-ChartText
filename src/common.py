"""Hàm dùng chung cho các script chạy mô hình."""
import json
import os
import time
from pathlib import Path


def list_images(label_dir, image_root):
    """Đọc mọi file nhãn *.json, trả về (id, đường dẫn ảnh). Bỏ qua file example_*."""
    items = []
    for p in sorted(Path(label_dir).glob("*.json")):
        if p.name.startswith("example_"):
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        img = Path(image_root) / Path(rec["image"]).name
        if img.exists():
            items.append((rec["id"], str(img)))
        else:
            print(f"[WARN] thiếu ảnh cho {rec['id']}: {img}")
    return items


def done_ids(out_path):
    """Cho phép chạy tiếp khi Colab bị ngắt: bỏ qua id đã có trong file kết quả."""
    if not os.path.exists(out_path):
        return set()
    with open(out_path, encoding="utf-8") as f:
        return {json.loads(line)["id"] for line in f if line.strip()}


def append_result(out_path, record):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class Timer:
    def __enter__(self):
        self.t = time.time()
        return self

    def __exit__(self, *a):
        self.sec = round(time.time() - self.t, 2)
