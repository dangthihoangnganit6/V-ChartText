"""Bước 1 cho demo: nạp Qwen3-VL-2B vừa GPU nhỏ (4 GB) và đọc ảnh thành JSON, trả kết quả dần (streaming).

GPU 4 GB (vd RTX 3050 Ti Laptop): fp16/bf16 cần ~4,5 GB -> không vừa. Mặc định 'auto':
  VRAM < 7 GB  -> 4-bit nf4 (bitsandbytes) cho phần ngôn ngữ, giữ bộ mã hoá ảnh ('visual') ở bf16/fp16 -> ~2-2,5 GB
  VRAM >= 7 GB -> bf16/fp16 đầy đủ (giống cấu hình chấm điểm trên Kaggle)
  không có GPU -> fp32 trên CPU (chạy được nhưng rất chậm, vài phút mỗi ảnh)
Lưu ý khi báo cáo: lượng tử hoá 4-bit có thể làm kết quả lệch nhẹ so với bảng điểm (chạy fp16 trên T4).
"""
import gc
import sys
import threading
import time
from pathlib import Path

import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MODEL_ID = "Qwen/Qwen3-VL-2B-Instruct"


def gpu_info():
    if not torch.cuda.is_available():
        return None
    p = torch.cuda.get_device_properties(0)
    return {"name": p.name, "vram_gb": round(p.total_memory / 1024 ** 3, 1), "cc": (p.major, p.minor)}


def _dtype():
    if torch.cuda.is_available():
        return torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16
    return torch.float32


class Extractor:
    def __init__(self, quant="auto", max_side=1024, model_id=MODEL_ID):
        self.quant_req, self.max_side, self.model_id = quant, max_side, model_id
        self.model = self.proc = None
        self.quant = None
        self.error = None
        self.load_sec = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ nạp mô hình
    def resolved_quant(self):
        if self.quant_req != "auto":
            return self.quant_req
        g = gpu_info()
        if not g:
            return "none"
        return "4bit" if g["vram_gb"] < 7 else "none"

    def load(self):
        with self._lock:
            if self.model is not None:
                return
            from transformers import AutoModelForImageTextToText, AutoProcessor
            t0 = time.time()
            q = self.resolved_quant()
            kw = {"dtype": _dtype()}
            if q in ("4bit", "8bit") and torch.cuda.is_available():
                from transformers import BitsAndBytesConfig
                skip = ["visual", "lm_head"]          # giữ bộ mã hoá ảnh và lớp ra ở bf16: đọc số chính xác hơn
                kw["quantization_config"] = (
                    BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                       bnb_4bit_compute_dtype=_dtype(), llm_int8_skip_modules=skip)
                    if q == "4bit" else BitsAndBytesConfig(load_in_8bit=True, llm_int8_skip_modules=skip))
                kw["device_map"] = {"": 0}
            elif torch.cuda.is_available():
                kw["device_map"] = "auto"             # thiếu VRAM thì tự đẩy bớt lớp sang RAM
            else:
                q = "cpu"
            try:
                self.model = AutoModelForImageTextToText.from_pretrained(self.model_id, **kw).eval()
                self.proc = AutoProcessor.from_pretrained(self.model_id)
                self.quant, self.error = q, None
            except Exception as e:  # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"
                raise
            self.load_sec = round(time.time() - t0, 1)

    def load_async(self):
        def _run():
            try:
                self.load()
            except Exception:  # noqa: BLE001  (lỗi đã lưu ở self.error, hiển thị trên giao diện)
                pass
        threading.Thread(target=_run, daemon=True).start()

    def status(self):
        g = gpu_info()
        dev = f"{g['name']} ({g['vram_gb']} GB)" if g else "CPU (không có GPU, sẽ rất chậm)"
        if self.error:
            return f"Lỗi nạp mô hình: {self.error}"
        if self.model is None:
            return f"Đang nạp {self.model_id.split('/')[-1]} trên {dev}…"
        used = f", đang dùng {torch.cuda.memory_allocated() / 1024 ** 3:.1f} GB VRAM" if g else ""
        return f"{self.model_id.split('/')[-1]} · {self.quant} · {dev}{used} · nạp trong {self.load_sec}s"

    # ------------------------------------------------------------------ hỏi ngắn (không streaming)
    def generate(self, prompt, image=None, max_new_tokens=384):
        """Một lượt hỏi ngắn: có ảnh (hỏi lại trường bị thiếu) hoặc chỉ văn bản (viết lại văn phong)."""
        self.load()
        content = ([{"type": "image", "image": self._prep(image, self.max_side)}] if image is not None else [])
        content.append({"type": "text", "text": prompt})
        inputs = self.proc.apply_chat_template([{"role": "user", "content": content}], tokenize=True,
                                               add_generation_prompt=True, return_dict=True,
                                               return_tensors="pt").to(self.model.device)
        with torch.inference_mode():
            gen = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        return self.proc.batch_decode(gen[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0].strip()

    # ------------------------------------------------------------------ đọc ảnh
    def _prep(self, img, max_side):
        img = img.convert("RGB")
        s = max_side / max(img.size)
        # ảnh nhỏ (vd 674x328, chữ số cao ~8px): phóng to tới max_side để mô hình có nhiều token ảnh hơn,
        # chữ số rõ hơn; ảnh lớn thì thu nhỏ như cũ
        if s < 1 or max(img.size) < 0.8 * max_side:
            img = img.resize((int(img.size[0] * s), int(img.size[1] * s)), Image.BICUBIC)
        return img

    def stream(self, image, prompt, max_new_tokens=2048):
        """Sinh output dần: yield (văn bản đến hiện tại, số token). Hết VRAM -> thử lại với ảnh nhỏ hơn."""
        from transformers import TextIteratorStreamer
        self.load()
        for side in (self.max_side, 768, 512):
            try:
                img = self._prep(image, side)
                msgs = [{"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": prompt}]}]
                inputs = self.proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                                       return_dict=True, return_tensors="pt").to(self.model.device)
                streamer = TextIteratorStreamer(self.proc.tokenizer, skip_prompt=True, skip_special_tokens=True,
                                                timeout=600)
                err = {}

                def _gen():
                    try:
                        with torch.inference_mode():
                            self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                                streamer=streamer)
                    except Exception as e:  # noqa: BLE001
                        err["e"] = e
                        streamer.end()
                th = threading.Thread(target=_gen, daemon=True)
                th.start()
                text, n = "", 0
                for chunk in streamer:
                    text += chunk
                    n += 1
                    yield text, n
                th.join()
                if "e" in err:
                    raise err["e"]
                return
            except torch.cuda.OutOfMemoryError:
                gc.collect()
                torch.cuda.empty_cache()
                if side == 512:
                    raise
                yield f"[hết VRAM với ảnh {side}px, thử lại với ảnh nhỏ hơn…]", 0
