"""Demo web V-ChartText: tải ảnh biểu đồ -> đọc số (VLM) -> kiểm chứng -> mô tả 3 cấp -> giọng đọc.

Cài (một lần, trong .venv):
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
  pip install -r demo/requirements.txt
Chạy:
  python demo/app.py                    # mở http://127.0.0.1:7860, nạp Qwen3-VL-2B (4-bit nếu GPU < 7 GB)
  python demo/app.py --no-model         # chỉ thư viện 200 biểu đồ tính sẵn, không cần GPU
  python demo/app.py --quant 8bit       # hoặc none (bf16 đầy đủ, cần >= 6 GB VRAM)
  python demo/app.py --share            # link công khai 72 giờ. KHÔNG dùng khi mở thư viện ảnh SGK có bản quyền.

Giọng đọc: edge-tts (giọng Microsoft tiếng Việt, cần Internet); không có mạng thì dùng nút "Đọc bằng trình duyệt".
Dùng được hoàn toàn bằng bàn phím (Tab / Enter); vùng trạng thái có aria-live để trình đọc màn hình thông báo tiến độ.
"""
import argparse
import html
import json
import sys
import tempfile
import time
from pathlib import Path

import gradio as gr

GR6 = int(gr.__version__.split(".")[0]) >= 6

ROOT = Path(__file__).resolve().parents[1]
for p in ("src/pipeline", "src", "eval", "demo"):
    sys.path.insert(0, str(ROOT / p))

from describe import describe  # noqa: E402
from speech import speech_text, synthesize  # noqa: E402
from verify import from_pred, verify  # noqa: E402
from vn import fmt  # noqa: E402

PIPE = ROOT / "outputs/pipeline/pipeline__Qwen3-VL-2B-Instruct__omit.jsonl"
DIRECT = ROOT / "outputs/Qwen3-VL-2B-Instruct__describe__v1.jsonl"
LABELS, IMAGES = ROOT / "data/labels", ROOT / "data/images"
LEVELS = {"Nghe nhanh · 5 giây": "nghe_5s", "Nghe chi tiết · 30 giây": "nghe_30s", "Diễn giải học tập": "dien_giai"}
LEVEL_ICON = {"nghe_5s": "⚡", "nghe_30s": "🎧", "dien_giai": "📘"}
TYPE_VI = {"bar": "Biểu đồ cột", "line": "Biểu đồ đường", "pie": "Biểu đồ tròn", "combo": "Biểu đồ kết hợp",
           "area": "Biểu đồ miền", "other": "Loại khác"}
STEPS = [("Đọc ảnh", "VLM trích xuất bảng số liệu"), ("Kiểm chứng", "8 luật, gắn cờ số chưa chắc"),
         ("Mô tả", "3 mức, chỉ dùng số đã kiểm"), ("Giọng đọc", "số đổi thành chữ, TTS")]
EXTRACTOR = None


# ====================================================================== dữ liệu tính sẵn (thư viện)
def load_cache():
    pipe, direct, meta = {}, {}, {}
    if PIPE.exists():
        for line in open(PIPE, encoding="utf-8"):
            o = json.loads(line)
            pipe[o["id"]] = o
    if DIRECT.exists():
        for line in open(DIRECT, encoding="utf-8"):
            o = json.loads(line)
            direct[o["id"]] = o["output"]
    for p in sorted(LABELS.glob("*.json")):
        if p.name.startswith("example_"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        img = IMAGES / Path(r["image"]).name
        if r["id"] in pipe and img.exists():
            meta[r["id"]] = {"image": str(img), "title": r.get("title") or "(ảnh không có tiêu đề)", "type": r["chart_type"]}
    return pipe, direct, meta


PIPE_CACHE, DIRECT_CACHE, META = load_cache()
CHOICES = [f"{i} · {TYPE_VI.get(m['type'], m['type'])} · {m['title'][:70]}" for i, m in META.items()]
EXAMPLES = [str(IMAGES / f) for f in ("bar_001.png", "line_052.png", "pie_008.png", "combo_009.png")
            if (IMAGES / f).exists()]

E = html.escape


# ====================================================================== khối HTML
def steps_html(state, msg="", times=None):
    """state: list 4 phần tử 'wait' | 'run' | 'done' | 'err'."""
    times = times or {}
    items = []
    for i, ((name, sub), st) in enumerate(zip(STEPS, state)):
        mark = {"wait": str(i + 1), "run": "", "done": "✓", "err": "!"}[st]
        t = f"<span class='vc-time'>{times[i]:.1f}s</span>" if i in times else ""
        items.append(f"<li class='vc-step vc-{st}'><span class='vc-dot'>{mark}</span>"
                     f"<span class='vc-sname'>{E(name)}{t}</span><span class='vc-ssub'>{E(sub)}</span></li>")
    note = f"<div class='vc-msg'>{E(msg)}</div>" if msg else ""
    return f"<div role='status' aria-live='polite'><ol class='vc-steps'>{''.join(items)}</ol>{note}</div>"


def summary_html(t):
    n, unc = len(t["points"]), t["n_uncertain"]
    unit = t["unit"] or "không rõ"
    if t.get("unit2"):
        unit += f" · {t['unit2']}"
    ok_pct = round(100 * (n - unc) / n) if n else 0
    cards = [("Loại", TYPE_VI.get(t["chart_type"], t["chart_type"])), ("Đơn vị", unit),
             ("Số điểm", str(n)), ("Đã kiểm chứng", f"{ok_pct}%")]
    title = t.get("title") or "(ảnh không có tiêu đề)"
    flags = "".join(f"<span class='vc-chip vc-chip-warn'>⚠ {E(f)}</span>" for f in t["flags"])
    flags = flags or "<span class='vc-chip vc-chip-ok'>✓ Không có cảnh báo mức biểu đồ</span>"
    if t.get("rechecked"):
        flags = f"<span class='vc-chip vc-chip-acc'>🔁 Đã hỏi lại ảnh: {E(', '.join(t['rechecked']))}</span>" + flags
    grid = "".join(f"<div class='vc-kpi'><div class='vc-kpi-l'>{E(a)}</div><div class='vc-kpi-v'>{E(b)}</div></div>"
                   for a, b in cards)
    return (f"<div class='vc-card'><div class='vc-title'>{E(title)}</div><div class='vc-kpis'>{grid}</div>"
            f"<div class='vc-bar' aria-hidden='true'><span style='width:{ok_pct}%'></span></div>"
            f"<div class='vc-chips'>{flags}</div></div>")


def levels_html(levels, chosen, polished=None):
    """polished: {key: (văn bản viết lại hoặc None, lý do giữ bản gốc)}."""
    polished = polished or {}
    out = []
    for label, key in LEVELS.items():
        on = " vc-on" if key == chosen else ""
        badge = "<span class='vc-chip vc-chip-acc'>đang đọc</span>" if key == chosen else ""
        text, extra = levels[key], ""
        if key in polished:
            new, why = polished[key]
            if new:
                badge += " <span class='vc-chip vc-chip-ok'>✍ đã viết lại, số được giữ nguyên</span>"
                extra = f"<details><summary>Bản mẫu câu gốc</summary><p>{E(text)}</p></details>"
                text = new
            else:
                badge += f" <span class='vc-chip vc-chip-warn'>giữ bản mẫu câu: {E(why)}</span>"
        out.append(f"<section class='vc-level{on}' aria-label='{E(label)}'><h3>{LEVEL_ICON[key]} {E(label)} {badge}</h3>"
                   f"<p>{E(text)}</p>{extra}</section>")
    return "<div class='vc-levels'>" + "".join(out) + "</div>"


def table_html(t):
    pts = t["points"]
    if not pts:
        return "<div class='vc-card vc-empty'>Không đọc được điểm số liệu nào.</div>"
    series = list(dict.fromkeys(p["series"] for p in pts))
    xs = list(dict.fromkeys(str(p["x"]) for p in pts))
    cell = {(p["series"], str(p["x"])): p for p in pts}

    def td(p):
        if p is None:
            return "<td class='vc-na'>—</td>"
        if p["flags"]:
            tip = E("; ".join(p["flags"]))
            return f"<td class='vc-warn' title='{tip}'>{E(fmt(p['y']))} <span aria-label='chưa chắc chắn: {tip}'>⚠</span></td>"
        return f"<td>{E(fmt(p['y']))}</td>"
    head = "<th scope='col'>Chuỗi \\ Mốc</th>" + "".join(f"<th scope='col'>{E(x)}</th>" for x in xs)
    body = "".join(f"<tr><th scope='row'>{E(str(s))}</th>" + "".join(td(cell.get((s, x))) for x in xs) + "</tr>"
                   for s in series)
    unc = [p for p in pts if p["flags"]]
    legend = ("<p class='vc-note'>⚠ = số chưa xác minh được, <b>không được đọc ra</b> trong mô tả (di chuột để xem lý do).</p>"
              if unc else "<p class='vc-note'>✓ Mọi số đều qua kiểm chứng.</p>")
    return (f"<div class='vc-card'><div class='vc-tablewrap'><table class='vc-table'><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>{legend}</div>")


def direct_html(text):
    return (f"<div class='vc-card vc-direct'><h3>🤖 VLM tự mô tả trực tiếp (không qua pipeline)</h3>"
            f"<p>{E(text)}</p><p class='vc-note'>Bản này hay đọc sai hoặc bịa số; so với mô tả bên trên "
            f"(chỉ dùng số đã kiểm chứng).</p></div>")


EMPTY_STEPS = steps_html(["wait"] * 4, "Tải ảnh biểu đồ lên rồi bấm “Phân tích & đọc”.")
EMPTY = "<div class='vc-card vc-empty'>Chưa có kết quả.</div>"


# ====================================================================== giọng đọc
def make_audio(text, voice):
    if not text:
        return None, ""
    out = Path(tempfile.gettempdir()) / f"vchart_{abs(hash((text, voice)))}.mp3"
    try:
        if not out.exists():
            synthesize(text, out, engine="edge", voice=voice)
        return str(out), "Đã tạo giọng đọc."
    except RuntimeError:
        return None, "Không tạo được giọng Microsoft (cần Internet) – bấm “Đọc bằng trình duyệt”."


def finish(result, level, voice, speak, do_polish=False):
    """Hiển thị + đọc mức đang chọn. do_polish: viết lại văn phong mức đó bằng mô hình (lưu cache trong result)."""
    key = LEVELS[level]
    text = result["levels"][key]
    pol = result.setdefault("polished", {})
    if do_polish and EXTRACTOR is not None and EXTRACTOR.model is not None and key not in pol:
        from refine import polish
        try:
            new, ok, why = polish(EXTRACTOR, text)
            pol[key] = (new if ok else None, why)
        except Exception as e:  # noqa: BLE001
            pol[key] = (None, f"lỗi khi viết lại ({type(e).__name__})")
    if pol.get(key, (None,))[0]:
        text = pol[key][0]
    spoken = speech_text(text)
    audio, note = make_audio(text, voice) if speak else (None, "")
    return levels_html(result["levels"], key, pol), spoken, audio, note


# ====================================================================== phân tích ảnh tải lên
def analyze(image, level, mode, prompt_v, voice, speak, do_polish=True, do_recheck=True):
    """Generator: cập nhật tiến độ từng bước. Outputs: steps, summary, levels, table, spoken, audio, raw, state."""
    if image is None:
        yield steps_html(["wait"] * 4, "Chưa có ảnh. Hãy tải ảnh hoặc dán ảnh (Ctrl+V)."), EMPTY, EMPTY, EMPTY, "", None, "", None
        return
    if EXTRACTOR is None:
        yield steps_html(["err", "wait", "wait", "wait"], "Demo đang chạy với --no-model: chỉ dùng được tab Thư viện."), \
            EMPTY, EMPTY, EMPTY, "", None, "", None
        return
    from prompts import PROMPTS_BY_VERSION
    from score_extract import read_pred
    st, times = ["run", "wait", "wait", "wait"], {}
    t0 = time.time()
    if EXTRACTOR.model is None:
        yield steps_html(st, EXTRACTOR.status() + " (lần đầu mất khoảng 1 phút)"), EMPTY, EMPTY, EMPTY, "", None, "", None
    raw = ""
    try:
        last = 0
        for raw, n in EXTRACTOR.stream(image, PROMPTS_BY_VERSION[prompt_v]["extract"]):
            if time.time() - last > 0.4:
                last = time.time()
                yield (steps_html(st, f"Mô hình đang đọc ảnh… {n} token · {time.time() - t0:.0f}s"),
                       EMPTY, EMPTY, EMPTY, "", None, raw, None)
    except Exception as e:  # noqa: BLE001
        st[0] = "err"
        yield steps_html(st, f"Lỗi ở bước 1: {type(e).__name__}: {e}"), EMPTY, EMPTY, EMPTY, "", None, raw, None
        return
    times[0] = time.time() - t0
    pred, status = read_pred(raw)
    if pred is None:
        st[0] = "err"
        yield (steps_html(st, "Mô hình không trả về JSON đọc được. Xem output thô ở mục Kỹ thuật, thử lại ảnh rõ hơn.",
                          times), EMPTY, EMPTY, EMPTY, "", None, raw, None)
        return
    st[:2] = ["done", "run"]
    t1 = time.time()
    t = verify(from_pred(pred))
    from refine import RECHECK_PROMPT, apply_recheck, apply_rows, need_rows, row_prompt, suspects
    if do_recheck and need_rows(t):
        yield (steps_html(st, "Nghi gán nhầm số giữa các chuỗi: đang đọc lại ảnh theo từng mốc…", times),
               summary_html(t), EMPTY, table_html(t), "", None, raw, None)
        try:
            ans = EXTRACTOR.generate(row_prompt(t), image=image, max_new_tokens=1024)
            raw += "\n\n--- đọc lại theo từng mốc ---\n" + ans
            pred_r = apply_rows(pred, t, ans)
            if pred_r is not None:
                t_r = verify(from_pred(pred_r))
                if t_r["n_uncertain"] < t["n_uncertain"] and not need_rows(t_r):
                    pred, t = pred_r, t_r
                    t["rechecked"] = ["số liệu (đọc lại theo từng mốc)"]
                else:
                    raw += "\n(bản đọc lại không tốt hơn, giữ bản đầu và giữ cờ ⚠)"
            else:
                raw += "\n(bản đọc lại thiếu mốc hoặc thiếu giá trị, giữ bản đầu và giữ cờ ⚠)"
        except Exception as e:  # noqa: BLE001
            raw += f"\n\n--- đọc lại theo mốc lỗi: {type(e).__name__}: {e}"
    want = suspects(t) if do_recheck else []
    if want:
        yield (steps_html(st, f"Bước 1 còn thiếu {', '.join(want)}: đang hỏi lại ảnh…", times), summary_html(t),
               EMPTY, table_html(t), "", None, raw, None)
        try:
            ans = EXTRACTOR.generate(RECHECK_PROMPT, image=image, max_new_tokens=384)
            pred2, fixed = apply_recheck(pred, t, ans)
            raw += "\n\n--- hỏi lại ảnh ---\n" + ans
            if fixed:
                prev = t.get("rechecked", [])
                t = verify(from_pred(pred2))
                t["rechecked"] = prev + fixed
        except Exception as e:  # noqa: BLE001
            raw += f"\n\n--- hỏi lại ảnh lỗi: {type(e).__name__}: {e}"
    times[1] = time.time() - t1
    st[1:3] = ["done", "run"]
    yield (steps_html(st, "Đã kiểm chứng bảng số liệu, đang viết mô tả" + (" và biên tập văn phong…" if do_polish else "…"),
                      times), summary_html(t), EMPTY, table_html(t), "", None, raw, None)
    t2 = time.time()
    lv = describe(t, mode)
    result = {"table": t, "levels": {k: lv[k] for k in LEVELS.values()}}
    lv_html, spoken, _, _ = finish(result, level, voice, False, do_polish)
    times[2] = time.time() - t2
    st[2:4] = ["done", "run" if speak else "wait"]
    yield steps_html(st, "Đang tạo giọng đọc…" if speak else "Xong.", times), summary_html(t), lv_html, table_html(t), \
        spoken, None, raw, result
    t3 = time.time()
    _, _, audio, note = finish(result, level, voice, speak, do_polish)
    if speak:
        times[3] = time.time() - t3
        st[3] = "done" if audio else "err"
    msg = f"Xong sau {time.time() - t0:.0f}s. {note} " + ("(JSON được cứu từ output bị cắt)" if status == "salvaged" else "")
    yield steps_html(st, msg, times), summary_html(t), lv_html, table_html(t), spoken, audio, raw, result


def relevel(result, level, voice, speak, do_polish):
    if not result:
        return EMPTY, "", None
    lv_html, spoken, audio, _ = finish(result, level, voice, speak, do_polish)
    return lv_html, spoken, audio


# ====================================================================== thư viện 200 biểu đồ
def pick(choice, level, voice, speak):
    if not choice:
        return None, EMPTY, EMPTY, EMPTY, "", None, ""
    cid = choice.split(" · ")[0]
    r = PIPE_CACHE[cid]
    res = {"table": r["table"], "levels": r["levels"]}
    lv_html, spoken, audio, _ = finish(res, level, voice, speak)
    return (META[cid]["image"], summary_html(r["table"]), lv_html, table_html(r["table"]), spoken, audio,
            direct_html(DIRECT_CACHE.get(cid, "(không có)")))


# ====================================================================== giao diện
BROWSER_TTS = """(text) => {
  if (!text) return;
  if (!('speechSynthesis' in window)) { alert('Trình duyệt không hỗ trợ đọc.'); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text); u.lang = 'vi-VN'; u.rate = 0.95;
  const v = window.speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith('vi'));
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
}"""
STOP_TTS = "() => { window.speechSynthesis.cancel(); document.querySelectorAll('audio').forEach(a => a.pause()); }"

CSS = """
.gradio-container {max-width: 1280px !important; font-size: 17px}
.vc-hero {border-radius: 20px; padding: 28px 32px; color: #fff; margin-bottom: 6px;
  background: radial-gradient(1200px 300px at 0% 0%, #7c3aed 0%, transparent 60%),
              linear-gradient(120deg, #4338ca 0%, #6d28d9 45%, #0f766e 100%);
  box-shadow: 0 12px 40px -18px rgba(67,56,202,.7)}
.vc-hero h1 {margin: 0 0 6px; font-size: 34px; letter-spacing: -.5px; color: #fff}
.vc-hero p {margin: 0; opacity: .92; font-size: 17px; color: #fff}
.vc-hero .vc-pills {display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px}
.vc-hero .vc-pill {background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28);
  padding: 5px 12px; border-radius: 999px; font-size: 14px; backdrop-filter: blur(4px)}
.vc-steps {list-style: none; display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; padding: 0; margin: 0}
.vc-step {display: grid; grid-template-columns: 34px 1fr; grid-template-rows: auto auto; column-gap: 10px;
  padding: 12px; border-radius: 14px; border: 1px solid var(--border-color-primary);
  background: var(--block-background-fill); transition: all .3s}
.vc-dot {grid-row: span 2; width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center;
  font-weight: 700; background: var(--background-fill-secondary); color: var(--body-text-color-subdued)}
.vc-sname {font-weight: 700; color: var(--body-text-color)}
.vc-ssub {font-size: 13px; color: var(--body-text-color-subdued)}
.vc-time {font-weight: 500; font-size: 12px; margin-left: 6px; color: var(--body-text-color-subdued)}
.vc-run {border-color: #6d28d9; box-shadow: 0 0 0 3px rgba(109,40,217,.18)}
.vc-run .vc-dot {background: conic-gradient(#6d28d9 0 25%, rgba(109,40,217,.15) 0); animation: vcspin 1s linear infinite}
.vc-done .vc-dot {background: #059669; color: #fff}
.vc-err .vc-dot {background: #dc2626; color: #fff}
.vc-err {border-color: #dc2626}
@keyframes vcspin {to {transform: rotate(360deg)}}
@media (prefers-reduced-motion: reduce) {.vc-run .vc-dot {animation: none}}
.vc-msg {margin-top: 10px; font-size: 15px; color: var(--body-text-color-subdued)}
.vc-card {border-radius: 16px; padding: 18px 20px; border: 1px solid var(--border-color-primary);
  background: var(--block-background-fill)}
.vc-empty {color: var(--body-text-color-subdued); text-align: center; padding: 28px}
.vc-title {font-size: 19px; font-weight: 700; margin-bottom: 12px; color: var(--body-text-color)}
.vc-kpis {display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px}
.vc-kpi {border-radius: 12px; padding: 10px 12px; background: var(--background-fill-secondary)}
.vc-kpi-l {font-size: 12px; text-transform: uppercase; letter-spacing: .6px; color: var(--body-text-color-subdued)}
.vc-kpi-v {font-size: 18px; font-weight: 700; color: var(--body-text-color); word-break: break-word}
.vc-bar {height: 6px; border-radius: 6px; background: var(--background-fill-secondary); margin: 14px 0 10px; overflow: hidden}
.vc-bar span {display: block; height: 100%; background: linear-gradient(90deg, #059669, #10b981)}
.vc-chips {display: flex; flex-wrap: wrap; gap: 6px}
.vc-chip {font-size: 13px; padding: 4px 10px; border-radius: 999px; font-weight: 600}
.vc-chip-ok {background: rgba(5,150,105,.14); color: #047857}
.vc-chip-warn {background: rgba(217,119,6,.16); color: #b45309}
.vc-chip-acc {background: rgba(109,40,217,.15); color: #6d28d9; font-size: 12px; vertical-align: middle}
.dark .vc-chip-ok {color: #6ee7b7} .dark .vc-chip-warn {color: #fcd34d} .dark .vc-chip-acc {color: #c4b5fd}
.vc-levels {display: grid; gap: 12px}
.vc-level {border-radius: 16px; padding: 14px 18px; border: 1px solid var(--border-color-primary);
  background: var(--block-background-fill)}
.vc-level h3 {margin: 0 0 6px; font-size: 16px; color: var(--body-text-color)}
.vc-level p {margin: 0; line-height: 1.7; font-size: 17px; color: var(--body-text-color)}
.vc-on {border: 2px solid #6d28d9; box-shadow: 0 8px 24px -16px rgba(109,40,217,.8)}
.vc-tablewrap {overflow-x: auto}
.vc-table {border-collapse: collapse; width: 100%; font-size: 15px}
.vc-table th, .vc-table td {padding: 8px 10px; border-bottom: 1px solid var(--border-color-primary); text-align: right;
  color: var(--body-text-color)}
.vc-table th[scope=row], .vc-table thead th:first-child {text-align: left}
.vc-table thead th {background: var(--background-fill-secondary); font-weight: 700}
.vc-warn {background: rgba(217,119,6,.13)}
.vc-na {color: var(--body-text-color-subdued)}
.vc-note {font-size: 14px; color: var(--body-text-color-subdued); margin: 10px 0 0}
.vc-direct h3 {margin: 0 0 8px; font-size: 16px}
.vc-direct p {line-height: 1.7}
.vc-go {font-size: 18px !important; min-height: 54px !important}
:focus-visible {outline: 3px solid #f59e0b !important; outline-offset: 2px}
@media (max-width: 900px) {.vc-steps, .vc-kpis {grid-template-columns: repeat(2, 1fr)}}
"""

HERO = """<div class='vc-hero'><h1>📊 V-ChartText</h1>
<p>Biến biểu đồ trong sách giáo khoa thành lời nói tiếng Việt cho học sinh khiếm thị, chỉ đọc những con số đã được kiểm chứng.</p>
<div class='vc-pills'><span class='vc-pill'>① Đọc ảnh bằng Qwen3-VL</span><span class='vc-pill'>② Kiểm chứng số liệu</span>
<span class='vc-pill'>③ Mô tả 3 mức</span><span class='vc-pill'>④ Giọng đọc tiếng Việt</span></div></div>"""


def theme():
    return gr.themes.Soft(primary_hue=gr.themes.colors.violet, secondary_hue=gr.themes.colors.teal,
                          neutral_hue=gr.themes.colors.slate, radius_size=gr.themes.sizes.radius_lg,
                          font=[gr.themes.GoogleFont("Be Vietnam Pro"), "system-ui", "sans-serif"])


def result_panel(prefix):
    """Khung kết quả dùng chung cho 2 tab."""
    summary = gr.HTML(EMPTY, label="Tóm tắt")
    with gr.Tabs():
        with gr.Tab("🗣 Mô tả"):
            levels = gr.HTML(EMPTY)
            spoken = gr.Textbox(label="Văn bản giọng đọc (số đã đổi thành chữ)", lines=3, elem_id=f"{prefix}-spoken")
            audio = gr.Audio(label="Giọng đọc", autoplay=True, interactive=False)
            with gr.Row():
                b_read = gr.Button("🔊 Đọc bằng trình duyệt (không cần mạng)")
                b_stop = gr.Button("⏹ Dừng đọc")
            b_read.click(None, [spoken], None, js=BROWSER_TTS)
            b_stop.click(None, None, None, js=STOP_TTS)
        with gr.Tab("📋 Bảng số liệu"):
            table = gr.HTML(EMPTY)
        extra = gr.Tab("⚙ Kỹ thuật" if prefix == "up" else "🤖 So sánh mô tả trực tiếp")
        with extra:
            other = (gr.Textbox(label="Output thô của VLM (bước 1)", lines=12, max_lines=30)
                     if prefix == "up" else gr.HTML(EMPTY))
    return summary, levels, table, spoken, audio, other


def build(model_status):
    kw = {} if GR6 else {"css": CSS, "theme": theme()}
    with gr.Blocks(title="V-ChartText · đọc biểu đồ thành lời", **kw) as app:
        gr.HTML(HERO)
        with gr.Row(equal_height=False):
            level = gr.Radio(list(LEVELS), value="Nghe chi tiết · 30 giây", label="Mức mô tả để đọc", scale=3)
            voice = gr.Radio([("Giọng nữ", "nu"), ("Giọng nam", "nam")], value="nu", label="Giọng", scale=1)
            speak = gr.Checkbox(value=True, label="Tự động đọc khi xong", scale=1)
        with gr.Tabs():
            # ---------------------------------------------------------------- tab 1
            with gr.Tab("📤 Tải ảnh lên"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=5, min_width=320):
                        up = gr.Image(label="Ảnh biểu đồ (kéo thả, chọn file hoặc dán Ctrl+V)", type="pil",
                                      sources=["upload", "clipboard"], height=340)
                        go = gr.Button("✨ Phân tích & đọc", variant="primary", elem_classes="vc-go")
                        with gr.Accordion("Tuỳ chọn", open=False):
                            mode = gr.Radio([("Bỏ số chưa chắc (an toàn)", "omit"), ("Đọc kèm “khoảng”", "hedge")],
                                            value="omit", label="Số chưa xác minh được")
                            prompt_v = gr.Radio([("v1 (đã chấm điểm)", "v1"), ("v2 (giữ tiền tố đơn vị)", "v2")],
                                                value="v1", label="Phiên bản prompt bước 1")
                            recheck = gr.Checkbox(value=True, label="🔁 Hỏi lại ảnh khi thiếu tiêu đề / đơn vị / "
                                                  "nhãn trục (thêm ~5–15 giây)")
                            polish = gr.Checkbox(value=True, label="✍ Viết lại văn phong tự nhiên bằng AI, "
                                                 "tự kiểm tra giữ nguyên số (thêm ~10–20 giây)")
                        if EXAMPLES:
                            gr.Examples(EXAMPLES, inputs=up, label="Ảnh mẫu")
                        gr.Markdown(f"<span class='vc-note'>🖥 {E(model_status)}</span>")
                    with gr.Column(scale=7, min_width=420):
                        steps = gr.HTML(EMPTY_STEPS)
                        summary, levels, table, spoken, audio, raw = result_panel("up")
                state = gr.State(None)
                outs = [steps, summary, levels, table, spoken, audio, raw, state]
                go.click(analyze, [up, level, mode, prompt_v, voice, speak, polish, recheck], outs)
                level.change(relevel, [state, level, voice, speak, polish], [levels, spoken, audio])
            # ---------------------------------------------------------------- tab 2
            with gr.Tab(f"🗂 Thư viện {len(META)} biểu đồ (tính sẵn)"):
                choice = gr.Dropdown(CHOICES, label="Chọn biểu đồ (gõ để tìm theo mã hoặc tiêu đề)", filterable=True)
                with gr.Row(equal_height=False):
                    with gr.Column(scale=5, min_width=320):
                        img2 = gr.Image(label="Ảnh biểu đồ", type="filepath", interactive=False, height=380)
                    with gr.Column(scale=7, min_width=420):
                        s2, l2, t2, sp2, a2, d2 = result_panel("lib")
                ins2 = [choice, level, voice, speak]
                outs2 = [img2, s2, l2, t2, sp2, a2, d2]
                choice.change(pick, ins2, outs2)
                level.change(pick, ins2, outs2)
        gr.Markdown("<span class='vc-note'>Ô có ⚠ là số chưa xác minh được: mô tả không đọc ra để tránh đọc sai. "
                    "Mô tả chỉ dùng số trong bảng đã kiểm chứng, không suy diễn nguyên nhân. "
                    "Ảnh trong thư viện là ảnh SGK có bản quyền, chỉ dùng nội bộ.</span>")
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-model", action="store_true", help="không nạp VLM, chỉ dùng thư viện tính sẵn")
    ap.add_argument("--quant", default="auto", choices=["auto", "4bit", "8bit", "none"])
    ap.add_argument("--max_side", type=int, default=1024, help="cạnh dài tối đa của ảnh đưa vào VLM (px)")
    ap.add_argument("--share", action="store_true")
    ap.add_argument("--port", type=int, default=7860)
    a = ap.parse_args()
    status = "Chế độ --no-model: chỉ dùng thư viện tính sẵn."
    if not a.no_model:
        from model import Extractor
        EXTRACTOR = Extractor(quant=a.quant, max_side=a.max_side)
        EXTRACTOR.load_async()            # nạp nền để giao diện mở ngay
        status = f"Mô hình: Qwen3-VL-2B-Instruct, lượng tử '{EXTRACTOR.resolved_quant()}', ảnh tối đa {a.max_side}px."
    extra = {"css": CSS, "theme": theme()} if GR6 else {}
    build(status).queue().launch(share=a.share, server_port=a.port, allowed_paths=[str(IMAGES)], **extra)
