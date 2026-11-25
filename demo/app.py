"""Demo web V-ChartText: ảnh biểu đồ -> bảng số liệu đã kiểm chứng -> mô tả 3 cấp -> nghe.

Chạy trên laptop (không cần GPU, dùng kết quả tính sẵn của 200 biểu đồ):
  pip install gradio edge-tts
  python demo/app.py                       # mở http://127.0.0.1:7860
  python demo/app.py --share               # thêm link công khai tạm thời (72 giờ) để trình bày
Bật chế độ tải ảnh mới (cần GPU, vd Kaggle/Colab; trên CPU mất vài phút mỗi ảnh):
  python demo/app.py --live --share

Giọng đọc: edge-tts (giọng Microsoft tiếng Việt, cần Internet). Không có mạng: nút "Đọc bằng trình duyệt"
dùng Web Speech API (giọng tiếng Việt có sẵn trên Windows/Chrome/Edge).
Toàn bộ thao tác dùng được bằng bàn phím (Tab / Enter), các thành phần đều có nhãn cho trình đọc màn hình.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import gradio as gr

GR6 = int(gr.__version__.split(".")[0]) >= 6   # Gradio 6 chuyển css sang launch(), bỏ show_copy_button

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "pipeline"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from describe import describe  # noqa: E402
from speech import speech_text, synthesize  # noqa: E402
from verify import from_pred, verify  # noqa: E402

PIPE = ROOT / "outputs/pipeline/pipeline__Qwen3-VL-2B-Instruct__omit.jsonl"
DIRECT = ROOT / "outputs/Qwen3-VL-2B-Instruct__describe__v1.jsonl"
LABELS = ROOT / "data/labels"
IMAGES = ROOT / "data/images"
LEVELS = {"Nghe nhanh (5 giây)": "nghe_5s", "Nghe chi tiết (30 giây)": "nghe_30s", "Diễn giải học tập": "dien_giai"}
TYPE_VI = {"bar": "cột", "line": "đường", "pie": "tròn", "combo": "kết hợp", "area": "miền", "other": "khác"}


def load_cache():
    pipe = {}
    if PIPE.exists():
        for line in open(PIPE, encoding="utf-8"):
            o = json.loads(line)
            pipe[o["id"]] = o
    direct = {}
    if DIRECT.exists():
        for line in open(DIRECT, encoding="utf-8"):
            o = json.loads(line)
            direct[o["id"]] = o["output"]
    meta = {}
    for p in sorted(LABELS.glob("*.json")):
        if p.name.startswith("example_"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        if r["id"] in pipe:
            meta[r["id"]] = {"image": str(IMAGES / Path(r["image"]).name), "title": r.get("title") or "(không có tiêu đề)",
                             "type": r["chart_type"]}
    return pipe, direct, meta


PIPE_CACHE, DIRECT_CACHE, META = load_cache()
CHOICES = [f"{i} | {TYPE_VI.get(m['type'], m['type'])} | {m['title'][:70]}" for i, m in META.items()]


def table_rows(t):
    rows = []
    for p in t["points"]:
        rows.append([p["series"], str(p["x"]), p["y"], "⚠ chưa chắc chắn: " + "; ".join(p["flags"]) if p["flags"] else "✓"])
    return rows


def show(result, level):
    t = result["table"]
    lv = result["levels"][LEVELS[level]]
    info = "Cảnh báo mức biểu đồ: " + "; ".join(t["flags"]) if t["flags"] else "Không có cảnh báo mức biểu đồ."
    summary = (f"Loại: {TYPE_VI.get(t['chart_type'], t['chart_type'])} | Đơn vị: {t['unit'] or 'không rõ'}"
               f"{' và ' + t['unit2'] if t['unit2'] else ''} | Điểm chưa chắc chắn: {t['n_uncertain']}/{len(t['points'])}")
    return table_rows(t), summary + "\n" + info, lv, speech_text(lv)


def pick(choice, level):
    if not choice:
        return None, [], "", "", "", ""
    cid = choice.split(" | ")[0]
    r = PIPE_CACHE[cid]
    rows, info, text, spoken = show(r, level)
    return META[cid]["image"], rows, info, text, spoken, DIRECT_CACHE.get(cid, "(không có)")


_MODEL = {}


def run_live(image, level):
    """Chạy bước 1 bằng Qwen3-VL trên ảnh tải lên, rồi bước 2-4."""
    if image is None:
        return [], "Chưa có ảnh.", "", "", ""
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    from infer_qwen import pick_dtype
    from prompts import EXTRACT_TABLE
    from score_extract import read_pred
    if "m" not in _MODEL:
        name = "Qwen/Qwen3-VL-2B-Instruct"
        _MODEL["m"] = AutoModelForImageTextToText.from_pretrained(name, dtype=pick_dtype("auto"),
                                                                  device_map="auto").eval()
        _MODEL["p"] = AutoProcessor.from_pretrained(name)
    model, proc = _MODEL["m"], _MODEL["p"]
    img = image.convert("RGB")
    s = 1280 / max(img.size)
    if s < 1:
        img = img.resize((int(img.size[0] * s), int(img.size[1] * s)))
    msgs = [{"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": EXTRACT_TABLE}]}]
    inputs = proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True,
                                      return_tensors="pt").to(model.device)
    with torch.inference_mode():
        gen = model.generate(**inputs, max_new_tokens=2048, do_sample=False)
    text = proc.batch_decode(gen[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0]
    pred, _ = read_pred(text)
    t = verify(from_pred(pred))
    lv = describe(t)
    result = {"table": t, "levels": {k: lv[k] for k in LEVELS.values()}}
    _MODEL["last"] = result
    rows, info, txt, spoken = show(result, level)
    return rows, info, txt, spoken, text


def tts(text, voice):
    if not text:
        return None, "Chưa có nội dung để đọc."
    out = Path(tempfile.gettempdir()) / f"vchart_{abs(hash((text, voice)))}.mp3"
    try:
        if not out.exists():
            synthesize(text, out, engine="edge", voice=voice)
        return str(out), "Đã tạo âm thanh. Nhấn phát trong ô Âm thanh."
    except RuntimeError as e:
        return None, f"Không tạo được âm thanh ({e}). Hãy dùng nút 'Đọc bằng trình duyệt'."


BROWSER_TTS = """(text) => {
  if (!('speechSynthesis' in window)) { alert('Trình duyệt không hỗ trợ đọc.'); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'vi-VN'; u.rate = 0.95;
  const v = window.speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith('vi'));
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
}"""

CSS = """
.gradio-container {font-size: 18px}
textarea {font-size: 18px !important; line-height: 1.6}
:focus-visible {outline: 3px solid #f5a623 !important; outline-offset: 2px}
"""


def build(live):
    kw = {} if GR6 else {"css": CSS}
    with gr.Blocks(title="V-ChartText: đọc biểu đồ cho học sinh khiếm thị", **kw) as app:
        gr.Markdown("# V-ChartText\nĐọc biểu đồ học tập thành lời. Chọn biểu đồ, chọn mức mô tả, rồi bấm **Đọc**. "
                    "Dùng phím Tab để di chuyển, Enter để bấm.")
        level = gr.Radio(list(LEVELS), value="Nghe chi tiết (30 giây)", label="Mức mô tả")
        with gr.Tabs():
            with gr.Tab("Biểu đồ có sẵn (200 ảnh)"):
                choice = gr.Dropdown(CHOICES, label="Chọn biểu đồ (gõ để tìm)", filterable=True)
                with gr.Row():
                    img = gr.Image(label="Ảnh biểu đồ", type="filepath", interactive=False, height=360)
                    with gr.Column():
                        info = gr.Textbox(label="Thông tin kiểm chứng (bước 2)", lines=3)
                        table = gr.Dataframe(headers=["Chuỗi", "Mốc", "Giá trị", "Kiểm chứng"],
                                             label="Bảng số liệu đã kiểm chứng", wrap=True)
                text = gr.Textbox(label="Mô tả (bước 3)", lines=6)
                spoken = gr.Textbox(label="Văn bản để đọc: số đã đổi thành chữ (bước 4)", lines=4)
                with gr.Accordion("So sánh: VLM mô tả trực tiếp (không qua pipeline)", open=False):
                    direct = gr.Textbox(label="Mô tả trực tiếp của Qwen3-VL-2B", lines=6)
                ins = [choice, level]
                outs = [img, table, info, text, spoken, direct]
                choice.change(pick, ins, outs)
                level.change(pick, ins, outs)
            if live:
                with gr.Tab("Tải ảnh mới (cần GPU)"):
                    up = gr.Image(label="Tải ảnh biểu đồ lên", type="pil")
                    run = gr.Button("Phân tích ảnh", variant="primary")
                    info2 = gr.Textbox(label="Thông tin kiểm chứng (bước 2)", lines=3)
                    table2 = gr.Dataframe(headers=["Chuỗi", "Mốc", "Giá trị", "Kiểm chứng"], label="Bảng số liệu")
                    text2 = gr.Textbox(label="Mô tả (bước 3)", lines=6)
                    spoken2 = gr.Textbox(label="Văn bản để đọc (bước 4)", lines=4)
                    raw2 = gr.Textbox(label="Output thô của VLM (bước 1)", lines=6)
                    run.click(run_live, [up, level], [table2, info2, text2, spoken2, raw2])
                    speak2 = gr.Button("Đọc mô tả ảnh này (trình duyệt)")
                    speak2.click(None, [spoken2], None, js=BROWSER_TTS)
        with gr.Row():
            voice = gr.Radio([("Giọng nữ", "nu"), ("Giọng nam", "nam")], value="nu", label="Giọng đọc")
            speak = gr.Button("Đọc (giọng Microsoft, cần Internet)", variant="primary")
            speak_b = gr.Button("Đọc bằng trình duyệt (không cần mạng)")
            stop = gr.Button("Dừng đọc")
        audio = gr.Audio(label="Âm thanh", autoplay=True)
        status = gr.Textbox(label="Trạng thái", lines=1)
        speak.click(tts, [spoken, voice], [audio, status])
        speak_b.click(None, [spoken], None, js=BROWSER_TTS)
        stop.click(None, None, None, js="() => window.speechSynthesis.cancel()")
        gr.Markdown("Ghi chú: các giá trị bị gắn ⚠ không được đọc ra để tránh đọc sai số. "
                    "Mô tả chỉ dùng số trong bảng đã kiểm chứng, không suy diễn nguyên nhân.")
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="bật tab tải ảnh mới (cần GPU)")
    ap.add_argument("--share", action="store_true")
    ap.add_argument("--port", type=int, default=7860)
    a = ap.parse_args()
    if not PIPE_CACHE:
        sys.exit(f"Chưa có {PIPE}. Chạy: python src/pipeline/run.py --source pred")
    extra = {"css": CSS} if GR6 else {}
    build(a.live).launch(share=a.share, server_port=a.port, allowed_paths=[str(IMAGES)], **extra)
