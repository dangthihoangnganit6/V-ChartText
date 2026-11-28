import os
import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import re
import json
import csv
import time
import asyncio
import hashlib
import uuid
import atexit
import html
from typing import Dict, List, Any, Tuple, Optional
from PIL import Image
import pandas as pd
import gradio as gr

# ==============================================================================
# 1. CẤU HÌNH ĐƯỜNG DẪN & QUẢN LÝ BỘ NHỚ ĐỆM TẠM THỜI (SESSION AUDIO CACHE)
# ==============================================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = APP_DIR

DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
DATASET_DIR = os.path.join(DATA_DIR, "dataset")
if not os.path.exists(DATASET_DIR):
    DATASET_DIR = os.path.join(WORKSPACE_DIR, "dataset")

DOCS_DIR = os.path.join(WORKSPACE_DIR, "docs")
BENCHMARK_PATH = os.path.join(DOCS_DIR, "benchmark.xlsx")
if not os.path.exists(BENCHMARK_PATH):
    BENCHMARK_PATH = os.path.join(DOCS_DIR, "Benchmark.xlsx")
if not os.path.exists(BENCHMARK_PATH):
    BENCHMARK_PATH = os.path.join(WORKSPACE_DIR, "benchmark.xlsx")

EXTRACTED_RESULTS_PATH = os.path.join(DATA_DIR, "vcharttext_extracted_results.csv")
if not os.path.exists(EXTRACTED_RESULTS_PATH):
    EXTRACTED_RESULTS_PATH = os.path.join(WORKSPACE_DIR, "vcharttext_extracted_results.csv")

# Thư mục cache âm thanh tạm thời cho phiên làm việc hiện tại (KHÔNG lưu dồn rác ra repo)
TEMP_AUDIO_DIR = os.path.join(WORKSPACE_DIR, "temp_session_audio")
os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)

def cleanup_all_temp_audio():
    """Dọn sạch toàn bộ file âm thanh tạm thời trong thư mục temp_session_audio."""
    if os.path.exists(TEMP_AUDIO_DIR):
        for f in os.listdir(TEMP_AUDIO_DIR):
            f_path = os.path.join(TEMP_AUDIO_DIR, f)
            try:
                if os.path.isfile(f_path):
                    os.remove(f_path)
            except Exception:
                pass

def cleanup_temp_files_list(file_paths: Optional[List[str]]):
    """Xóa danh sách các file âm thanh tạm thời của phiên trước đó."""
    if not file_paths:
        return
    for p in file_paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

# Tự động dọn sạch rác âm thanh cũ khi khởi động ứng dụng và khi đóng tiến trình
cleanup_all_temp_audio()
atexit.register(cleanup_all_temp_audio)

# Cấu hình & nạp mô hình Qwen3-VL (tách biệt khỏi vòng lặp xử lý từng ảnh)
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

QWEN3_VL_UTILS_SRC = os.path.join(WORKSPACE_DIR, "Qwen3-VL", "qwen-vl-utils", "src")
if os.path.isdir(QWEN3_VL_UTILS_SRC) and QWEN3_VL_UTILS_SRC not in sys.path:
    sys.path.insert(0, QWEN3_VL_UTILS_SRC)

QWEN3_VL_MODEL_ID = os.environ.get("QWEN3_VL_MODEL_ID", "Qwen/Qwen3-VL-2B-Instruct")
QWEN3_VL_REMOTE_URL = os.environ.get("QWEN3_VL_REMOTE_URL", "").strip()
QWEN3_VL_AUTOLOAD = os.environ.get("QWEN3_VL_AUTOLOAD", "0") == "1"
QWEN3_VL_ALLOW_CPU = os.environ.get("QWEN3_VL_ALLOW_CPU", "0") == "1"
QWEN3_VL_TIMEOUT = float(os.environ.get("QWEN3_VL_TIMEOUT", "180"))
QWEN3_VL_MAX_IMAGE_SIDE = int(os.environ.get("QWEN3_VL_MAX_IMAGE_SIDE", "1280"))
QWEN3_VL_MAX_NEW_TOKENS = int(os.environ.get("QWEN3_VL_MAX_NEW_TOKENS", "512"))
QWEN3_VL_REPETITION_PENALTY = float(os.environ.get("QWEN3_VL_REPETITION_PENALTY", "1.05"))
QWEN3_VL_MIN_PIXELS = int(os.environ.get("QWEN3_VL_MIN_PIXELS", str(256 * 28 * 28)))
QWEN3_VL_MAX_PIXELS = int(os.environ.get("QWEN3_VL_MAX_PIXELS", str(1280 * 28 * 28)))

QWEN3_VL_PROMPT_JSON = """Bạn là chuyên gia trích xuất dữ liệu biểu đồ giáo dục tiếng Việt (SGK Địa lí, Lịch sử, tài liệu ôn thi THPT Quốc gia).
Đọc hình ảnh biểu đồ và trích xuất thành DUY NHẤT một chuỗi JSON hợp lệ gồm 7 trường:
{
  "chart_title": "Tên đầy đủ của biểu đồ (nguyên văn tiếng Việt có dấu, nếu không có ghi 'Không có tên')",
  "chart_type": "Chỉ chọn 1 trong: column | cột ghép | cột chồng | đường | miền | tròn | kết hợp",
  "unit": "Đơn vị đo lường (ví dụ: %, nghìn ha, triệu tấn, USD/người...)",
  "x_axis_label": "Nhãn trục hoành (ví dụ: Năm, Vùng kinh tế, Quốc gia...)",
  "categories": "Các mốc/danh mục trục hoành phân tách bằng ' | '",
  "series_name": "Tên các chuỗi dữ liệu phân tách bằng ' || '",
  "values": "Giá trị số tương ứng; cùng chuỗi phân tách bằng ' | ', giữa các chuỗi phân tách bằng ' || '"
}
Giữ nguyên định dạng số tiếng Việt (dấu ',' thập phân, dấu '.' hàng nghìn). Chỉ trả về JSON, không giải thích thêm."""

_QWEN3_VL_LOCK = threading.Lock()
_QWEN3_VL_INFER_LOCK = threading.Lock()
_QWEN3_VL_STATE: Dict[str, Any] = {
    "model": None,
    "processor": None,
    "model_id": QWEN3_VL_MODEL_ID,
    "device": "cpu",
    "loaded": False,
    "error": None,
}


def init_qwen3_vl_model(model_id: Optional[str] = None) -> Tuple[bool, str]:
    """
    Nạp mô hình Qwen3-VL một lần duy nhất (singleton).
    Không tự động tải model nặng nếu thiếu GPU CUDA và chưa bật QWEN3_VL_ALLOW_CPU=1.
    """
    target_id = (model_id or QWEN3_VL_MODEL_ID).strip()
    if _QWEN3_VL_STATE["loaded"] and _QWEN3_VL_STATE["model"] is not None and _QWEN3_VL_STATE["model_id"] == target_id:
        return True, f"Qwen3-VL ({target_id}) đã sẵn sàng trên {_QWEN3_VL_STATE['device']}."

    with _QWEN3_VL_LOCK:
        if _QWEN3_VL_STATE["loaded"] and _QWEN3_VL_STATE["model"] is not None and _QWEN3_VL_STATE["model_id"] == target_id:
            return True, f"Qwen3-VL ({target_id}) đã sẵn sàng trên {_QWEN3_VL_STATE['device']}."

        _QWEN3_VL_STATE["model_id"] = target_id
        try:
            import torch
            from transformers import AutoProcessor, AutoModelForImageTextToText

            has_cuda = torch.cuda.is_available()
            if not has_cuda and not QWEN3_VL_ALLOW_CPU:
                msg = "Thiếu GPU CUDA và chưa bật cờ QWEN3_VL_ALLOW_CPU=1; bỏ qua nạp Qwen3-VL để tránh tải model nặng."
                _QWEN3_VL_STATE["error"] = msg
                return False, msg

            device = "cuda" if has_cuda else "cpu"
            _QWEN3_VL_STATE["device"] = device
            try:
                processor = AutoProcessor.from_pretrained(
                    target_id,
                    min_pixels=QWEN3_VL_MIN_PIXELS,
                    max_pixels=QWEN3_VL_MAX_PIXELS,
                )
            except TypeError:
                processor = AutoProcessor.from_pretrained(target_id)
            model = AutoModelForImageTextToText.from_pretrained(
                target_id,
                dtype="auto",
                device_map="auto" if has_cuda else "cpu",
            )
            model.eval()
            _QWEN3_VL_STATE["processor"] = processor
            _QWEN3_VL_STATE["model"] = model
            _QWEN3_VL_STATE["loaded"] = True
            _QWEN3_VL_STATE["error"] = None
            return True, f"Đã nạp thành công {target_id} trên {device.upper()}."
        except Exception as e:
            msg = f"Không thể nạp Qwen3-VL ({target_id}): {e}"
            _QWEN3_VL_STATE["loaded"] = False
            _QWEN3_VL_STATE["model"] = None
            _QWEN3_VL_STATE["processor"] = None
            _QWEN3_VL_STATE["error"] = msg
            return False, msg


if QWEN3_VL_AUTOLOAD:
    _ok_q3, _msg_q3 = init_qwen3_vl_model()
    print(f"{'✓' if _ok_q3 else '⚠️'} {_msg_q3}")

# ==============================================================================
# 2. CÁC HÀM BĂM ẢNH & THỊ GIÁC (HASHING & PERCEPTUAL MATCHING)
# ==============================================================================
def compute_file_md5(file_path: str) -> Optional[str]:
    """Tính mã băm MD5 của file nguyên bản (khớp 100% byte-for-byte)."""
    try:
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return None

def compute_dhash(img: Image.Image, hash_size: int = 8) -> int:
    """Tính mã băm chênh lệch thị giác (dHash) chống ảnh hưởng nén/lưu tạm."""
    try:
        resized = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
        pixels = list(resized.getdata())
        diff = []
        for r in range(hash_size):
            for c in range(hash_size):
                diff.append(pixels[r * (hash_size + 1) + c] > pixels[r * (hash_size + 1) + c + 1])
        return sum(v << i for i, v in enumerate(diff))
    except Exception:
        return 0

def compute_ahash(img: Image.Image, hash_size: int = 8) -> int:
    """Tính mã băm trung bình thị giác (aHash)."""
    try:
        resized = img.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS)
        pixels = list(resized.getdata())
        avg = sum(pixels) / max(len(pixels), 1)
        diff = [p > avg for p in pixels]
        return sum(v << i for i, v in enumerate(diff))
    except Exception:
        return 0

def hamming_distance(h1: int, h2: int) -> int:
    """Tính khoảng cách Hamming giữa hai mã băm thị giác 64-bit."""
    return bin(h1 ^ h2).count("1")

# ==============================================================================
# 3. NẠP TẬP ĐỐI CHUẨN BENCHMARK (CHỈ PHỤC VỤ ĐÁNH GIÁ / ĐỐI CHIẾU BƯỚC 3)
# ==============================================================================
BENCHMARK_RECORDS: Dict[str, Dict[str, Any]] = {}
MD5_INDEX: Dict[str, str] = {}
DHASH_INDEX: Dict[int, Tuple[str, float]] = {}
FILENAME_INDEX: Dict[str, str] = {}
DATASET_FILEPATHS: Dict[str, str] = {}

from vichartfact_metrics import (
    normalize_chart_type,
    clean_vietnamese_number,
    parse_semicolon_or_pipe,
    validate_chart_data,
    apply_uncertainty_flagging,
    fmt_vn,
    clean_chart_title_for_speech,
    generate_3level_descriptions,
    fact_check_vichartfact,
    evaluate_description_completeness,
    render_vichartfact_html,
)

# Nạp Benchmark ground truth (chỉ dùng cho đánh giá/đối chiếu, KHÔNG dùng điền sẵn Bước 1)
if os.path.exists(BENCHMARK_PATH):
    try:
        df_bm = pd.read_excel(BENCHMARK_PATH, header=2)
        for _, row in df_bm.iterrows():
            img_n = str(row.get("image_name", "")).strip()
            if img_n and img_n != "nan":
                rec = {
                    "image_name": img_n,
                    "chart_title": str(row.get("chart_title", "")).strip() if pd.notna(row.get("chart_title")) else "Biểu đồ học tập SGK",
                    "chart_type": normalize_chart_type(row.get("chart_type", "column")),
                    "unit": str(row.get("unit", "")).strip() if pd.notna(row.get("unit")) else "",
                    "x_axis_label": str(row.get("x_axis_label", "")).strip() if pd.notna(row.get("x_axis_label")) else "Danh mục",
                    "categories": str(row.get("categories", "")).strip() if pd.notna(row.get("categories")) else "",
                    "series_name": str(row.get("series_name", "")).strip() if pd.notna(row.get("series_name")) else "Giá trị",
                    "values": str(row.get("values", "")).strip() if pd.notna(row.get("values")) else "",
                    "source": "benchmark"
                }
                BENCHMARK_RECORDS[img_n] = rec
                BENCHMARK_RECORDS[img_n.lower()] = rec
                if img_n.endswith(".png"):
                    BENCHMARK_RECORDS[img_n.replace(".png", ".jpg")] = rec
                elif img_n.endswith(".jpg"):
                    BENCHMARK_RECORDS[img_n.replace(".jpg", ".png")] = rec
        print(f"✓ Đã nạp {len(df_bm)} bản ghi đối chuẩn từ benchmark.xlsx (chỉ dùng để đánh giá).")
    except Exception as e:
        print(f"⚠️ Cảnh báo nạp benchmark.xlsx: {e}")

# Lập chỉ mục ảnh trong thư mục dataset để phục vụ đối chiếu đánh giá & tập mẫu giao diện
if os.path.exists(DATASET_DIR):
    for root, _, files in os.walk(DATASET_DIR):
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                f_clean = f.strip()
                full_path = os.path.join(root, f)
                DATASET_FILEPATHS[f_clean] = full_path
                FILENAME_INDEX[f_clean.lower()] = f_clean
                
                # MD5
                m = compute_file_md5(full_path)
                if m:
                    MD5_INDEX[m] = f_clean

                # dHash & Aspect Ratio
                try:
                    with Image.open(full_path) as im:
                        dh = compute_dhash(im)
                        w, h = im.size
                        ar = round(w / max(h, 1), 2)
                        DHASH_INDEX[dh] = (f_clean, ar)
                except Exception:
                    pass

print(f"✓ Lập chỉ mục thành công: {len(DATASET_FILEPATHS)} ảnh SGK ({len(MD5_INDEX)} mã MD5, {len(DHASH_INDEX)} mã dHash).")

# ==============================================================================
# 4. BỘ TRA CỨU ĐỐI CHUẨN BENCHMARK (CHỈ DÙNG CHO ĐÁNH GIÁ METRIC)
# ==============================================================================
def resolve_image_match(input_image_path: str) -> Tuple[Optional[str], str]:
    """
    Đối chiếu ảnh đầu vào với tập chuẩn benchmark.xlsx để lấy Ground Truth phục vụ đánh giá ở Bước 3:
    1. Kiểm tra tên file trực tiếp.
    2. Mã băm MD5 nguyên bản.
    3. Mã băm thị giác dHash khớp tuyệt đối.
    4. Mã băm thị giác dHash lân cận gần nhất (Hamming Distance <= 6).
    """
    if not input_image_path or not os.path.exists(input_image_path):
        return None, "File không tồn tại"

    base_name = os.path.basename(input_image_path).strip()

    # 1. Tên file trực tiếp
    if base_name in BENCHMARK_RECORDS:
        return BENCHMARK_RECORDS[base_name]["image_name"], f"Khớp trực tiếp tên file gốc: '{base_name}'"
    if base_name.lower() in FILENAME_INDEX:
        real_n = FILENAME_INDEX[base_name.lower()]
        return real_n, f"Khớp theo danh mục chuẩn: '{real_n}'"

    # 2. Mã băm MD5
    m = compute_file_md5(input_image_path)
    if m and m in MD5_INDEX:
        matched_n = MD5_INDEX[m]
        return matched_n, f"Khớp tuyệt đối 100% qua mã băm MD5: '{matched_n}'"

    # 3. Mã băm thị giác dHash
    try:
        with Image.open(input_image_path) as im:
            dh = compute_dhash(im)
            w, h = im.size
            ar = round(w / max(h, 1), 2)
    except Exception as e:
        return None, f"Lỗi đọc định dạng ảnh: {e}"

    if dh in DHASH_INDEX:
        matched_n = DHASH_INDEX[dh][0]
        return matched_n, f"Khớp chính xác qua mã băm thị giác dHash: '{matched_n}'"

    # 4. Khoảng cách Hamming dHash
    best_candidate = None
    min_dist = 999
    for ref_dh, (fn, ref_ar) in DHASH_INDEX.items():
        dist = hamming_distance(dh, ref_dh)
        if abs(ar - ref_ar) > 0.25:
            dist += 4
        if dist < min_dist:
            min_dist = dist
            best_candidate = fn

    if min_dist <= 6 and best_candidate:
        return best_candidate, f"Khớp thị giác tương đồng dHash (Khoảng cách Hamming = {min_dist}): '{best_candidate}'"

    return None, f"Không tìm thấy trong tập 214 biểu đồ mẫu (khoảng cách băm nhỏ nhất = {min_dist})"


# ==============================================================================
# 8. CHUẨN HÓA NGỮ ÂM ĐỌC SỐ TIẾNG VIỆT & DUAL-ENGINE TTS (FALLBACK AN TOÀN)
# ==============================================================================
VI_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]

def read_integer_to_vietnamese(n: int) -> str:
    if n == 0: return "không"
    if n < 0: return "âm " + read_integer_to_vietnamese(-n)
    
    units = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ"]
    chunks = []
    temp = n
    while temp > 0:
        chunks.append(temp % 1000)
        temp //= 1000

    def read_block_3(num: int, is_highest: bool) -> str:
        h = num // 100
        t = (num % 100) // 10
        u = num % 10
        res = []
        if h > 0 or not is_highest:
            res.append(f"{VI_DIGITS[h]} trăm")
        if t == 0:
            if u > 0 and (h > 0 or not is_highest):
                res.append(f"lẻ {VI_DIGITS[u]}")
            elif u > 0:
                res.append(VI_DIGITS[u])
        elif t == 1:
            res.append("mười")
            if u == 1: res.append("một")
            elif u == 5: res.append("lăm")
            elif u > 0: res.append(VI_DIGITS[u])
        else:
            res.append(f"{VI_DIGITS[t]} mươi")
            if u == 1: res.append("mốt")
            elif u == 4: res.append("tư")
            elif u == 5: res.append("lăm")
            elif u > 0: res.append(VI_DIGITS[u])
        return " ".join(res)

    res_chunks = []
    for i in range(len(chunks) - 1, -1, -1):
        c_val = chunks[i]
        if c_val > 0:
            is_high = (i == len(chunks) - 1)
            c_text = read_block_3(c_val, is_high)
            res_chunks.append(f"{c_text} {units[i]}".strip())
    return " ".join(res_chunks).strip()

def normalize_vietnamese_phonetics_for_tts(text: str) -> str:
    """
    Chuẩn hóa ngữ âm tiếng Việt phục vụ đọc số tự nhiên và ngắt câu dễ nghe:
    - Đọc số hàng nghìn có dấu chấm: '1.200' -> 'một nghìn hai trăm', '19.257' -> 'mười chín nghìn hai trăm năm mươi bảy'
    - Đọc số thập phân có dấu phẩy: '12,5%' -> 'mười hai phẩy năm phần trăm'
    - Đọc khoảng năm: '1995 - 2016' -> 'từ năm một nghìn chín trăm chín mươi lăm đến năm hai nghìn không trăm mười sáu'
    - Đọc năm tránh lặp: 'Năm 2005' -> 'năm hai nghìn không trăm lẻ năm'
    - Tách câu ngắn, biến đầu dòng bullet thành dấu chấm ngắt nhịp tự nhiên cho giọng đọc.
    """
    if not text: return ""
    cleaned = text
    cleaned = re.sub(r"\[chưa chắc chắn\]", "giá trị chưa thể xác định chắc chắn do biểu đồ mờ", cleaned)
    
    # Chia câu ngắn dễ nghe, ngắt dòng thành dấu chấm
    cleaned = re.sub(r"[\r\n]+", ". ", cleaned)
    cleaned = re.sub(r"^\s*[-*•]\s*", "", cleaned)
    cleaned = re.sub(r"\s*[-*•]\s*", ". ", cleaned)

    for ch in ['{', '}', '[', ']', '"', "'", '#', '`']:
        cleaned = cleaned.replace(ch, '')
    cleaned = cleaned.replace("||", ", ").replace("|", ", ")
    cleaned = re.sub(r"\(\s*đơn vị\s*:\s*%\s*\)", ", đơn vị tính là phần trăm, ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\(\s*đơn vị\s*:\s*([^\)]+)\)", r", đơn vị tính là \1, ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\((.*?)\)", r", \1, ", cleaned)
    cleaned = re.sub(r"\s*:\s*", ". ", cleaned)

    # 1. Khoảng năm (tránh lặp từ "từ từ năm")
    def repl_year_range(m):
        y1 = int(m.group(1))
        y2 = int(m.group(2))
        return f"từ năm {read_integer_to_vietnamese(y1)} đến năm {read_integer_to_vietnamese(y2)}"
    cleaned = re.sub(r"(?:(?:từ\s+)?(?:năm\s+)?)(\d{4})\s*[-–—]\s*(?:(?:đến\s+)?(?:năm\s+)?)(\d{4})", repl_year_range, cleaned, flags=re.IGNORECASE)

    # 2. Xử lý 'Năm YYYY' chống lặp từ 'Năm năm...'
    def repl_year_single(m):
        word_nam = m.group(1)
        val = int(m.group(2))
        return f"{word_nam} {read_integer_to_vietnamese(val)}"
    cleaned = re.sub(r"\b([Nn]ăm)\s+(\d{4})\b", repl_year_single, cleaned)

    # 3. Ký hiệu phần trăm
    def repl_pct(m):
        num_str = m.group(1)
        flt = clean_vietnamese_number(num_str)
        if flt is not None:
            if flt.is_integer():
                return f"{read_integer_to_vietnamese(int(flt))} phần trăm"
            else:
                int_p = int(flt)
                dec_str = str(flt).split(".")[1]
                dec_words = " ".join([VI_DIGITS[int(d)] for d in dec_str])
                return f"{read_integer_to_vietnamese(int_p)} phẩy {dec_words} phần trăm"
        return m.group(0)
    cleaned = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", repl_pct, cleaned)

    # 4. Số thập phân / hàng nghìn
    def repl_dec(m):
        matched = m.group(0)
        flt = clean_vietnamese_number(matched)
        if flt is not None:
            if flt.is_integer():
                return read_integer_to_vietnamese(int(flt))
            else:
                int_p = int(flt)
                dec_str = str(flt).split(".")[1]
                dec_words = " ".join([VI_DIGITS[int(d)] for d in dec_str])
                return f"{read_integer_to_vietnamese(int_p)} phẩy {dec_words}"
        return matched
    cleaned = re.sub(r"\b\d+[,.]\d+\b", repl_dec, cleaned)

    # 5. Các số nguyên lẻ
    def repl_int(m):
        val = int(m.group(0))
        if 1950 <= val <= 2050:
            return f"năm {read_integer_to_vietnamese(val)}"
        return read_integer_to_vietnamese(val)
    cleaned = re.sub(r"\b\d{1,9}\b", repl_int, cleaned)

    # 6. Sửa lỗi OCR đơn vị & thuật ngữ biểu đồ
    unit_replacements = [
        (r"\bngính ha\b|\bnginh ha\b", "nghìn héc-ta"),
        (r"\bnghìn ha\b|\bnghin ha\b", "nghìn héc-ta"),
        (r"\bha\b", "héc-ta"),
        (r"\bkm2\b|\bkm²\b", "ki-lô-mét vuông"),
        (r"\bm2\b|\bm²\b", "mét vuông"),
        (r"\bUSD/người\b", "đô la Mỹ trên người"),
        (r"\bUSD\b", "đô la Mỹ"),
        (r"\bcolumn\b", "cột"),
        (r"\bline\b", "đường"),
        (r"\bpie\b", "tròn"),
        (r"\barea\b", "miền"),
        (r"\bcombined\b", "kết hợp"),
        (r"\btỉ\b", "tỷ")
    ]
    for pattern, rep in unit_replacements:
        cleaned = re.sub(pattern, rep, cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    cleaned = re.sub(r"\s*\.\s*", ". ", cleaned)
    cleaned = re.sub(r",\s*,+", ", ", cleaned)
    cleaned = re.sub(r"\.\s*\.+", ". ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()

# ==============================================================================
# 8. CẤU HÌNH GIỌNG ĐỌC TIẾNG VIỆT HOÀI MY & BỘ TỔNG HỢP TTS
# ==============================================================================
HOAI_MY_VOICE_ID = "vi-VN-HoaiMyNeural"
HOAI_MY_VOICE_LABEL = "Hoài My (Nữ - Truyền cảm, tự nhiên)"

def generate_tts_audio_sync(text: str, output_path: str, voice_id: str = HOAI_MY_VOICE_ID) -> Tuple[bool, str]:
    """
    Tạo âm thanh giọng đọc tiếng Việt duy nhất: Hoài My (Nữ - Truyền cảm, tự nhiên):
    - Ưu tiên gọi Microsoft Edge-TTS qua subprocess CLI độc lập (ổn định, không xung đột event loop của Gradio).
    - Dự phòng 1: Gọi thư viện edge_tts với loop an toàn (nest_asyncio).
    - Dự phòng 2: Fallback tự động sang gTTS tiếng Việt nếu mất kết nối mạng Microsoft.
    Trả về: (thành công: bool, thông tin engine/giọng: str)
    """
    phonetic_text = normalize_vietnamese_phonetics_for_tts(text)
    if not phonetic_text.strip():
        return False, "Văn bản rỗng, không có nội dung để đọc"

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # 1. Thử gọi Edge-TTS (Hoài My) qua subprocess CLI để chạy độc lập tiến trình
    import subprocess
    cmd = [sys.executable, "-m", "edge_tts", "--voice", voice_id, "--text", phonetic_text, "--write-media", output_path]
    for attempt in range(2):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=14)
            if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return True, f"Edge-TTS ({HOAI_MY_VOICE_LABEL})"
        except Exception:
            pass
        if os.path.exists(output_path) and os.path.getsize(output_path) < 1000:
            try:
                os.remove(output_path)
            except Exception:
                pass
        time.sleep(0.5)

    # 2. Thử qua thư viện edge_tts in-process (an toàn với uvicorn/uvloop trên server cloud)
    try:
        import edge_tts

        async def _speak():
            comm = edge_tts.Communicate(phonetic_text, voice_id)
            await comm.save(output_path)

        try:
            asyncio.run(_speak())
        except RuntimeError:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(asyncio.run, _speak()).result(timeout=15)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True, f"Edge-TTS ({HOAI_MY_VOICE_LABEL})"
    except Exception as e_edge:
        print(f"Edge-TTS thư viện không phản hồi: {e_edge}")

    # 3. Fallback dự phòng sang gTTS (chỉ khi hoàn toàn không kết nối được Edge-TTS)
    try:
        from gtts import gTTS
        tts = gTTS(text=phonetic_text, lang='vi')
        tts.save(output_path)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True, "gTTS (Dự phòng)"
    except Exception as e_gtts:
        print(f"gTTS fallback error: {e_gtts}")

    return False, "Không thể kết nối dịch vụ TTS lúc này"

def build_tts_content_by_level(level_choice: str, desc_5s: str, desc_30s: str, desc_study: str) -> str:
    """Xây dựng nội dung lời đọc tiếng Việt theo cấp độ lựa chọn."""
    if level_choice == "Cấp 1: Tổng quan 5s":
        return f"Cấp độ một, tổng quan nhanh. {desc_5s}"
    elif level_choice == "Cấp 2: Tóm tắt sư phạm 30s":
        return f"Cấp độ hai, tóm tắt sư phạm. {desc_30s}"
    elif level_choice == "Cấp 3: Phân tích học tập chuyên sâu":
        return f"Cấp độ ba, phân tích học tập chuyên sâu. {desc_study}"
    else:
        # Mặc định: Cả 3 cấp độ
        return (
            f"Cấp độ một, tổng quan nhanh. {desc_5s}. "
            f"Cấp độ hai, tóm tắt sư phạm. {desc_30s}. "
            f"Cấp độ ba, phân tích học tập chuyên sâu. {desc_study}"
        )

def make_toast_html(title: str, message: str, toast_type: str = "success") -> str:
    """Tạo thông báo nổi (toast) ở góc dưới bên phải màn hình, tự động biến mất sau 10 giây."""
    if not title and not message:
        return ""
    
    type_configs = {
        "success": {
            "icon": "✅",
            "border_color": "#1A40C2",
            "title_color": "#1A40C2"
        },
        "info": {
            "icon": "🔊",
            "border_color": "#0F766E",
            "title_color": "#0F766E"
        },
        "warning": {
            "icon": "⚠️",
            "border_color": "#B06000",
            "title_color": "#8A4B00"
        },
        "error": {
            "icon": "❌",
            "border_color": "#C5221F",
            "title_color": "#C5221F"
        }
    }
    cfg = type_configs.get(toast_type, type_configs["success"])
    toast_id = f"toast_{uuid.uuid4().hex[:6]}"

    return f"""
    <div id="{toast_id}" class="v-toast-wrapper">
        <div class="v-toast-card" style="border-left: 5px solid {cfg['border_color']};">
            <div style="font-size: 20px; line-height: 1; flex-shrink: 0; padding-top: 2px;">{cfg['icon']}</div>
            <div style="flex: 1; min-width: 0;">
                <div style="font-weight: 700; color: {cfg['title_color']}; font-size: 13.5px; margin-bottom: 2px;">
                    {html.escape(title)}
                </div>
                <div style="font-size: 12.5px; color: #4B5563; line-height: 1.45;">
                    {message}
                </div>
            </div>
            <button onclick="document.getElementById('{toast_id}').style.display='none'" 
                    style="background: transparent; border: none; font-size: 18px; color: #9CA3AF; cursor: pointer; padding: 0 4px; line-height: 1; margin-left: 4px;"
                    title="Đóng thông báo">&times;</button>
        </div>
    </div>
    """

# ==============================================================================
# 9. HÀM XỬ LÝ CHÍNH CỦA PIPELINE DEMO GRADIO
# ==============================================================================
def render_loading_vichartfact_html(status_text: str) -> str:
    """Render hiệu ứng spinner + shimmer tự viết cho Mục 3 ViChartFact khi đang xử lý."""
    return f"""
    <div style="background-color: #FFFFFF; border: 1px solid #E2E6F0; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; flex-direction: column; gap: 14px;">
        <div style="display: flex; align-items: center; gap: 12px;">
            <span class="v-spinner"></span>
            <div>
                <div style="font-size: 16px; font-weight: 800; color: #1E293B;">3. Kiểm Định ViChartFact</div>
                <div style="font-size: 13px; color: #1A40C2; font-weight: 600;">{html.escape(status_text)}</div>
            </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;">
            <div class="v-shimmer-bar" style="height: 82px;"></div>
            <div class="v-shimmer-bar" style="height: 82px;"></div>
            <div class="v-shimmer-bar" style="height: 82px;"></div>
        </div>
        <div class="v-shimmer-bar" style="height: 48px;"></div>
    </div>
    """

def _normalize_qwen3_vl_output(raw_or_dict: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse JSON (nếu là chuỗi) và chuẩn hóa đầu ra Qwen3-VL về 7 trường chuẩn trước khi qua Bước 2."""
    if isinstance(raw_or_dict, dict):
        parsed = raw_or_dict
    else:
        raw_text = str(raw_or_dict) if raw_or_dict is not None else ""
        if not raw_text.strip():
            return None, "Output rỗng từ Qwen3-VL."

        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw_text)
        m_brace = re.search(r"(\{[\s\S]*\})", raw_text)
        json_str = m.group(1).strip() if m else (m_brace.group(1).strip() if m_brace else "")
        if not json_str:
            print(f"[Qwen3-VL][_normalize_qwen3_vl_output] Không tìm thấy JSON. raw_text=\n{raw_text}")
            return None, f"Không tìm thấy JSON hợp lệ trong đầu ra Qwen3-VL: {raw_text[:120]}"

        json_str = re.sub(r",\s*\}", "}", re.sub(r",\s*\]", "]", json_str))
        try:
            parsed = json.loads(json_str)
        except Exception as e:
            try:
                parsed = json.loads(json_str.replace("'", '"'))
            except Exception:
                print(f"[Qwen3-VL][_normalize_qwen3_vl_output] Lỗi cú pháp JSON ({e}). raw_text=\n{raw_text}")
                return None, f"Lỗi cú pháp JSON từ Qwen3-VL: {e}"

        if not isinstance(parsed, dict):
            print(f"[Qwen3-VL][_normalize_qwen3_vl_output] JSON không phải dict. raw_text=\n{raw_text}")
            return None, "Đầu ra JSON của Qwen3-VL không phải dạng dict."

    def _norm_sep(v: Any, sep: str, default: str = "") -> str:
        if v is None:
            return default
        if isinstance(v, list):
            if sep == " || " and v and isinstance(v[0], list):
                return " || ".join(" | ".join(str(x).strip() for x in sub if str(x).strip()) for sub in v)
            return sep.join(str(x).strip() for x in v if str(x).strip()) or default
        s = str(v).strip()
        if not s or s.lower() in {"none", "null", "nan"}:
            return default
        if ";" in s and "|" not in s:
            return sep.join(p.strip() for p in s.split(";") if p.strip()) or default
        return s

    title = str(parsed.get("chart_title") or "").strip()
    if not title or title.lower() in {"none", "null", "nan", "không có tên"}:
        title = "Biểu đồ học tập SGK"
    unit = str(parsed.get("unit") or "").strip()
    if unit.lower() in {"none", "null", "nan", "không có"}:
        unit = ""
    x_label = str(parsed.get("x_axis_label") or "").strip()
    if not x_label or x_label.lower() in {"none", "null", "nan", "không có"}:
        x_label = "Danh mục"

    categories = _norm_sep(parsed.get("categories"), " | ", "")
    series_name = _norm_sep(parsed.get("series_name"), " || ", "Giá trị")
    values = _norm_sep(parsed.get("values"), " | ", "")
    if isinstance(parsed.get("values"), list) and parsed["values"] and isinstance(parsed["values"][0], list):
        values = _norm_sep(parsed.get("values"), " || ", "")

    if not categories and not values:
        print(f"[Qwen3-VL][_normalize_qwen3_vl_output] Thiếu categories và values. raw_or_dict=\n{raw_or_dict}")
        return None, "Qwen3-VL trả về thiếu cả danh mục (categories) và giá trị (values)."

    return {
        "chart_title": title,
        "chart_type": normalize_chart_type(parsed.get("chart_type", "column")),
        "unit": unit,
        "x_axis_label": x_label,
        "categories": categories,
        "series_name": series_name,
        "values": values,
    }, None


def _prepare_qwen3_vl_image(
    image_path: str,
    max_side: int = QWEN3_VL_MAX_IMAGE_SIDE,
) -> Tuple[str, Tuple[int, int], Tuple[int, int], bool]:
    """Thu nhỏ ảnh giữ nguyên tỷ lệ nếu cạnh dài vượt quá max_side để giảm visual tokens và tăng tốc suy luận."""
    import tempfile

    with Image.open(image_path) as im:
        orig_size = im.size
        w, h = orig_size
        if max_side > 0 and max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            resized = im.convert("RGB").resize(new_size, resample)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
                resized.save(tmp_path, format="PNG")
            return tmp_path, orig_size, new_size, True
    return image_path, orig_size, orig_size, False


def extract_chart_data_vlm(image_path: str, timeout_sec: float = QWEN3_VL_TIMEOUT) -> Dict[str, Any]:
    """Bước 1: Chạy Qwen3-VL trực tiếp trên ảnh (qua remote Colab endpoint hoặc model cục bộ)."""
    t0 = time.perf_counter()
    if not image_path or not os.path.exists(image_path):
        return {"ok": False, "data": None, "error": "Ảnh không tồn tại.", "error_type": "invalid_image",
                "model_id": _QWEN3_VL_STATE["model_id"], "device": _QWEN3_VL_STATE["device"], "elapsed_sec": 0.0}

    try:
        with Image.open(image_path) as im:
            im.verify()
    except Exception as e:
        return {"ok": False, "data": None, "error": f"Ảnh không hợp lệ: {e}", "error_type": "invalid_image",
                "model_id": _QWEN3_VL_STATE["model_id"], "device": _QWEN3_VL_STATE["device"], "elapsed_sec": round(time.perf_counter() - t0, 2)}

    prepared_path, orig_size, new_size, is_temp_img = _prepare_qwen3_vl_image(image_path)
    try:
        remote_url = os.environ.get("QWEN3_VL_REMOTE_URL", "").strip() or QWEN3_VL_REMOTE_URL
        if remote_url:
            import requests

            t_http = time.perf_counter()
            try:
                with open(prepared_path, "rb") as img_f:
                    resp = requests.post(
                        remote_url,
                        files={"file": (os.path.basename(prepared_path), img_f, "application/octet-stream")},
                        timeout=timeout_sec,
                    )
            except requests.exceptions.Timeout:
                elapsed = round(time.perf_counter() - t0, 2)
                print(f"[Qwen3-VL][Remote] Timeout sau {elapsed}s (ngưỡng {timeout_sec:.0f}s), size={orig_size}->{new_size}")
                return {"ok": False, "data": None, "error": f"Gọi endpoint từ xa vượt quá {timeout_sec:.0f}s.", "error_type": "timeout",
                        "model_id": "Qwen3-VL-Remote", "device": "remote-colab", "elapsed_sec": elapsed}
            except requests.exceptions.RequestException as e:
                elapsed = round(time.perf_counter() - t0, 2)
                print(f"[Qwen3-VL][Remote] RequestException sau {elapsed}s: {e}")
                return {"ok": False, "data": None, "error": f"Lỗi kết nối endpoint từ xa ({remote_url}): {e}", "error_type": "remote_error",
                        "model_id": "Qwen3-VL-Remote", "device": "remote-colab", "elapsed_sec": elapsed}

            http_sec = round(time.perf_counter() - t_http, 2)
            if resp.status_code >= 400:
                err_detail = resp.text[:500]
                err_type = "remote_error"
                model_id_err = "Qwen3-VL-Remote"
                try:
                    err_payload = resp.json()
                    if isinstance(err_payload, dict):
                        err_msg = err_payload.get("error") or err_detail
                        err_trace = err_payload.get("trace") or ""
                        err_type = err_payload.get("error_type") or "remote_error"
                        model_id_err = err_payload.get("model_id") or model_id_err
                        print(f"[Qwen3-VL][Remote] HTTP {resp.status_code} ({http_sec}s): {err_msg}\n{err_trace}")
                        err_detail = f"{err_msg}" + (f" | trace: {err_trace[-300:]}" if err_trace else "")
                except ValueError:
                    print(f"[Qwen3-VL][Remote] HTTP {resp.status_code} ({http_sec}s), non-JSON body: {err_detail}")
                return {"ok": False, "data": None, "error": f"Endpoint từ xa trả về HTTP {resp.status_code}: {err_detail}", "error_type": err_type,
                        "model_id": model_id_err, "device": "remote-colab", "elapsed_sec": round(time.perf_counter() - t0, 2)}

            try:
                payload = resp.json()
            except ValueError as e:
                return {"ok": False, "data": None, "error": f"Endpoint từ xa trả về không phải JSON hợp lệ: {e}", "error_type": "invalid_output",
                        "model_id": "Qwen3-VL-Remote", "device": "remote-colab", "elapsed_sec": round(time.perf_counter() - t0, 2)}

            if not isinstance(payload, dict) or not payload.get("ok"):
                err_msg = payload.get("error") if isinstance(payload, dict) else "Phản hồi từ endpoint từ xa không hợp lệ."
                err_type = (payload.get("error_type") if isinstance(payload, dict) else None) or "remote_error"
                print(f"[Qwen3-VL][Remote] ok=False ({http_sec}s): {err_type} - {err_msg}")
                return {"ok": False, "data": None, "error": err_msg or "Endpoint từ xa trả về lỗi.", "error_type": err_type,
                        "model_id": (payload.get("model_id") if isinstance(payload, dict) else None) or "Qwen3-VL-Remote",
                        "device": "remote-colab", "elapsed_sec": round(time.perf_counter() - t0, 2)}

            t_norm = time.perf_counter()
            data, norm_err = _normalize_qwen3_vl_output(payload.get("data"))
            norm_sec = round(time.perf_counter() - t_norm, 3)
            elapsed = round(time.perf_counter() - t0, 2)
            print(f"[Qwen3-VL][Remote] orig={orig_size} sent={new_size} http={http_sec}s norm={norm_sec}s total={elapsed}s")
            if norm_err or data is None:
                return {"ok": False, "data": None, "error": norm_err, "error_type": "invalid_output",
                        "model_id": payload.get("model_id", "Qwen3-VL-Remote"), "device": "remote-colab", "elapsed_sec": elapsed}

            return {"ok": True, "data": data, "error": None, "error_type": None,
                    "model_id": payload.get("model_id", "Qwen3-VL-Remote"), "device": "remote-colab", "elapsed_sec": elapsed}

        ok_load, load_msg = init_qwen3_vl_model()
        if not ok_load:
            return {"ok": False, "data": None, "error": load_msg, "error_type": "model_not_ready",
                    "model_id": _QWEN3_VL_STATE["model_id"], "device": _QWEN3_VL_STATE["device"], "elapsed_sec": round(time.perf_counter() - t0, 2)}

        def _infer() -> str:
            import torch
            from qwen_vl_utils import process_vision_info

            acquired = _QWEN3_VL_INFER_LOCK.acquire(timeout=timeout_sec)
            if not acquired:
                raise TimeoutError(f"GPU đang bận xử lý lượt suy luận trước quá {timeout_sec:.0f}s.")
            try:
                processor = _QWEN3_VL_STATE["processor"]
                model = _QWEN3_VL_STATE["model"]

                t_prep = time.perf_counter()
                messages = [{"role": "user", "content": [{"type": "image", "image": prepared_path}, {"type": "text", "text": QWEN3_VL_PROMPT_JSON}]}]
                text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                image_inputs, video_inputs = process_vision_info(messages)
                inputs = processor(text=[text], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt").to(model.device)
                prep_sec = time.perf_counter() - t_prep
                input_tokens = int(inputs.input_ids.shape[1])

                t_gen = time.perf_counter()
                with torch.no_grad():
                    gen_ids = model.generate(
                        **inputs,
                        max_new_tokens=QWEN3_VL_MAX_NEW_TOKENS,
                        do_sample=False,
                        repetition_penalty=QWEN3_VL_REPETITION_PENALTY,
                    )
                gen_sec = time.perf_counter() - t_gen
                trimmed = [out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, gen_ids)]
                output_tokens = int(trimmed[0].shape[0]) if trimmed else 0
                raw_out = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
                print(
                    f"[Qwen3-VL][Local] orig={orig_size} resized={new_size} "
                    f"prep={prep_sec:.2f}s gen={gen_sec:.2f}s "
                    f"in_tok={input_tokens} out_tok={output_tokens} max_new={QWEN3_VL_MAX_NEW_TOKENS}"
                )
                return raw_out
            finally:
                _QWEN3_VL_INFER_LOCK.release()

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_infer)
        try:
            raw_text = future.result(timeout=timeout_sec)
        except FuturesTimeoutError:
            elapsed = round(time.perf_counter() - t0, 2)
            print(f"[Qwen3-VL][Local] FuturesTimeoutError sau {elapsed}s (ngưỡng {timeout_sec:.0f}s)")
            return {"ok": False, "data": None, "error": f"Suy luận Qwen3-VL vượt quá {timeout_sec:.0f}s.", "error_type": "timeout",
                    "model_id": _QWEN3_VL_STATE["model_id"], "device": _QWEN3_VL_STATE["device"], "elapsed_sec": elapsed}
        except Exception as e:
            elapsed = round(time.perf_counter() - t0, 2)
            print(f"[Qwen3-VL][Local] Runtime error sau {elapsed}s: {e}")
            return {"ok": False, "data": None, "error": f"Lỗi suy luận Qwen3-VL: {e}", "error_type": "runtime_error",
                    "model_id": _QWEN3_VL_STATE["model_id"], "device": _QWEN3_VL_STATE["device"], "elapsed_sec": elapsed}
        finally:
            executor.shutdown(wait=False)

        t_norm = time.perf_counter()
        data, norm_err = _normalize_qwen3_vl_output(raw_text)
        norm_sec = round(time.perf_counter() - t_norm, 3)
        elapsed = round(time.perf_counter() - t0, 2)
        print(f"[Qwen3-VL][Local] norm={norm_sec}s total={elapsed}s ok={norm_err is None and data is not None}")
        if norm_err or data is None:
            return {"ok": False, "data": None, "error": norm_err, "error_type": "invalid_output",
                    "model_id": _QWEN3_VL_STATE["model_id"], "device": _QWEN3_VL_STATE["device"], "elapsed_sec": elapsed}

        return {"ok": True, "data": data, "error": None, "error_type": None,
                "model_id": _QWEN3_VL_STATE["model_id"], "device": _QWEN3_VL_STATE["device"], "elapsed_sec": elapsed}
    finally:
        if is_temp_img and prepared_path and os.path.exists(prepared_path):
            try:
                os.remove(prepared_path)
            except OSError:
                pass


def process_pipeline_demo(
    input_image_path: Optional[str],
    current_session_files: List[str]
):
    """
    Hàm xử lý Pipeline 4 bước dạng generator (progressive/streaming output qua `yield` & `gr.update`):
    - Mục nào chưa xong ở từng nhịp `yield` sẽ hiển thị hiệu ứng đang tải (CSS shimmer/spinner) + trạng thái chờ/xử lý.
    - Mục nào đã xong thì tắt hiệu ứng tải, hiện kết quả thật và giữ nguyên ở các nhịp tiếp theo.
    - Các nhánh dừng sớm tắt sạch toàn bộ hiệu ứng tải.
    """
    # Xóa file âm thanh tạm của lượt xử lý trước
    cleanup_temp_files_list(current_session_files)

    if not input_image_path or not os.path.exists(input_image_path):
        err_toast = make_toast_html("Lỗi Tải Ảnh", "Vui lòng chọn hoặc tải lên một hình ảnh biểu đồ SGK hợp lệ.", "error")
        yield (
            gr.update(value=pd.DataFrame()),
            gr.update(value=pd.DataFrame()),
            gr.update(value="", placeholder="Nội dung mô tả Cấp 1 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
            gr.update(value=None, label="🎧 Trình phát Cấp 1 (Hoài My)", elem_classes=[]),
            gr.update(value="", placeholder="Nội dung mô tả Cấp 2 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
            gr.update(value=None, label="🎧 Trình phát Cấp 2 (Hoài My)", elem_classes=[]),
            gr.update(value="", placeholder="Nội dung mô tả Cấp 3 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
            gr.update(value=None, label="🎧 Trình phát Cấp 3 (Hoài My)", elem_classes=[]),
            gr.update(value=""),
            gr.update(value=err_toast),
            []
        )
        return

    # --------------------------------------------------------------------------
    # BƯỚC 1: SUY LUẬN VLM TRỰC TIẾP TỪ ẢNH ĐẦU VÀO (KHÔNG TRA CỨU CACHE/BENCHMARK)
    # --------------------------------------------------------------------------
    t_pipe = time.perf_counter()
    yield (
        gr.update(value=pd.DataFrame([{"Thuộc tính": "Trạng thái Bước 1 (VLM)", "Nội dung": "⏳ Đang trích xuất dữ liệu biểu đồ bằng Qwen3-VL..."}])),
        gr.update(value=pd.DataFrame()),
        gr.update(value="", placeholder="⏳ Đang chờ Bước 1 (Qwen3-VL)...", elem_classes=["v-desc-box", "v-loading-box"]),
        gr.update(value=None, label="⏳ Đang chờ tạo giọng đọc Cấp 1 (Hoài My)...", elem_classes=["v-loading-audio"]),
        gr.update(value="", placeholder="⏳ Đang chờ Bước 1 (Qwen3-VL)...", elem_classes=["v-desc-box", "v-loading-box"]),
        gr.update(value=None, label="⏳ Đang chờ tạo giọng đọc Cấp 2 (Hoài My)...", elem_classes=["v-loading-audio"]),
        gr.update(value="", placeholder="⏳ Đang chờ Bước 1 (Qwen3-VL)...", elem_classes=["v-desc-box", "v-loading-box"]),
        gr.update(value=None, label="⏳ Đang chờ tạo giọng đọc Cấp 3 (Hoài My)...", elem_classes=["v-loading-audio"]),
        gr.update(value=render_loading_vichartfact_html("Đang trích xuất dữ liệu biểu đồ bằng Qwen3-VL (Bước 1)...")),
        gr.update(value=""),
        []
    )
    vlm_res = extract_chart_data_vlm(input_image_path)
    print(f"[Pipeline] Bước 1 hoàn tất sau {time.perf_counter() - t_pipe:.2f}s (ok={vlm_res.get('ok')})")

    if not vlm_res.get("ok") or not vlm_res.get("data"):
        err_detail = vlm_res.get("error") or "Không thể trích xuất dữ liệu từ ảnh."
        err_type = vlm_res.get("error_type") or "runtime_error"
        model_name = vlm_res.get("model_id", QWEN3_VL_MODEL_ID)
        elapsed = vlm_res.get("elapsed_sec", 0.0)

        empty_meta = pd.DataFrame([
            {"Thuộc tính": "Trạng thái Bước 1 (VLM)", "Nội dung": f"Lỗi ({err_type})"},
            {"Thuộc tính": "Mô hình VLM", "Nội dung": f"{model_name} ({vlm_res.get('device', 'cpu')})"},
            {"Thuộc tính": "Thời gian xử lý", "Nội dung": f"{elapsed}s"},
            {"Thuộc tính": "Chi tiết lỗi", "Nội dung": err_detail},
        ])
        empty_matrix = pd.DataFrame([
            {"Thông báo": f"Không trích xuất được ma trận số liệu từ VLM: {err_detail}"}
        ])
        notice_msg = f"Bước 1 (VLM trực tiếp) gặp lỗi ({err_type}): {err_detail}"
        empty_vichartfact = f"""
        <div style="background-color: #FEF2F2; border: 1px dashed #FCA5A5; border-radius: 8px; padding: 20px; text-align: center; color: #991B1B; font-size: 13.5px; line-height: 1.5; margin-top: 10px;">
            ⚠️ <b>Chưa thực hiện Bước 3 & ViChartFact:</b> Bước 1 (suy luận VLM trực tiếp) không thành công — {html.escape(err_detail)}
        </div>
        """
        err_toast = make_toast_html("Lỗi Trích Xuất VLM (Bước 1)", err_detail, "error")
        yield (
            gr.update(value=empty_meta),
            gr.update(value=empty_matrix),
            gr.update(value=notice_msg, placeholder="", elem_classes=["v-desc-box"]),
            gr.update(value=None, label="🎧 Trình phát Cấp 1 (Hoài My)", elem_classes=[]),
            gr.update(value=notice_msg, placeholder="", elem_classes=["v-desc-box"]),
            gr.update(value=None, label="🎧 Trình phát Cấp 2 (Hoài My)", elem_classes=[]),
            gr.update(value=notice_msg, placeholder="", elem_classes=["v-desc-box"]),
            gr.update(value=None, label="🎧 Trình phát Cấp 3 (Hoài My)", elem_classes=[]),
            gr.update(value=empty_vichartfact),
            gr.update(value=err_toast),
            []
        )
        return

    step1_dict = vlm_res["data"]

    # Bước 2: Kiểm chứng dữ liệu & Gắn cờ bất định (Bảo toàn 100% logic kiểm chứng)
    val_status, val_notes, parsed_matrix = validate_chart_data(step1_dict)
    flagged_matrix = apply_uncertainty_flagging(parsed_matrix, val_notes)

    # Bảng 1: Metadata chung (Hiển thị đầy đủ trạng thái kiểm chứng và ghi chú)
    meta_df = pd.DataFrame([
        {"Thuộc tính": "Tiêu đề biểu đồ", "Nội dung": step1_dict["chart_title"]},
        {"Thuộc tính": "Loại biểu đồ", "Nội dung": step1_dict["chart_type"]},
        {"Thuộc tính": "Đơn vị tính", "Nội dung": step1_dict["unit"] if step1_dict["unit"] else "Không ghi đơn vị"},
        {"Thuộc tính": "Trục hoành (Categories)", "Nội dung": " | ".join(flagged_matrix["categories"])},
        {"Thuộc tính": "Nguồn trích xuất (Bước 1)", "Nội dung": f"VLM trực tiếp ({vlm_res['model_id']}, {vlm_res['elapsed_sec']}s)"},
        {"Thuộc tính": "Trạng thái kiểm chứng", "Nội dung": val_status},
        {"Thuộc tính": "Ghi chú kiểm tra", "Nội dung": val_notes}
    ])

    # Bảng 2: Ma trận số liệu chi tiết
    matrix_rows = []
    for s_name, vals in flagged_matrix["series_data"].items():
        row_dict = {"Chuỗi dữ liệu (Series)": s_name}
        for c_idx, c_name in enumerate(flagged_matrix["categories"]):
            v = vals[c_idx] if c_idx < len(vals) else "[chưa chắc chắn]"
            row_dict[c_name] = v
        matrix_rows.append(row_dict)
    data_matrix_df = pd.DataFrame(matrix_rows)

    # YIELD 1: Xong Bước 1 & 2 -> Hiện ngay Bảng đặc tả & Ma trận; bật hiệu ứng loading cho Mô tả 3 cấp, Audio & ViChartFact
    yield (
        gr.update(value=meta_df),
        gr.update(value=data_matrix_df),
        gr.update(value="", placeholder="⏳ Đang sinh mô tả Cấp 1 (Tổng quan 5s)...", elem_classes=["v-desc-box", "v-loading-box"]),
        gr.update(value=None, label="⏳ Đang chờ tạo giọng đọc Cấp 1 (Hoài My)...", elem_classes=["v-loading-audio"]),
        gr.update(value="", placeholder="⏳ Đang sinh mô tả Cấp 2 (Tóm tắt 30s)...", elem_classes=["v-desc-box", "v-loading-box"]),
        gr.update(value=None, label="⏳ Đang chờ tạo giọng đọc Cấp 2 (Hoài My)...", elem_classes=["v-loading-audio"]),
        gr.update(value="", placeholder="⏳ Đang sinh mô tả Cấp 3 (Phân tích chi tiết)...", elem_classes=["v-desc-box", "v-loading-box"]),
        gr.update(value=None, label="⏳ Đang chờ tạo giọng đọc Cấp 3 (Hoài My)...", elem_classes=["v-loading-audio"]),
        gr.update(value=render_loading_vichartfact_html("Đang tổng hợp mô tả 3 cấp & đo kiểm độ trung thực ViChartFact...")),
        gr.update(value=""),
        []
    )

    # Bước 3: Sinh mô tả 3 cấp độ & Đo kiểm ViChartFact
    desc_dict = generate_3level_descriptions(flagged_matrix)
    desc_5s = desc_dict["desc_5s"]
    desc_30s = desc_dict["desc_30s"]
    desc_study = desc_dict["desc_study"]

    fact_report = fact_check_vichartfact(desc_dict, flagged_matrix)

    # Đối chiếu tập chuẩn benchmark.xlsx (nếu ảnh khớp) chỉ để phục vụ đánh giá/metric
    matched_bm_name, _ = resolve_image_match(input_image_path)
    eval_gt_record = (
        BENCHMARK_RECORDS[matched_bm_name]
        if matched_bm_name and matched_bm_name in BENCHMARK_RECORDS
        else step1_dict
    )
    completeness_report = evaluate_description_completeness(
        desc_dict,
        eval_gt_record,
        has_uncertainty=flagged_matrix.get("has_uncertainty", False),
    )
    vichartfact_html = render_vichartfact_html(fact_report, completeness_res=completeness_report)

    # YIELD 2: Xong Bước 3 & ViChartFact -> Tắt loading cho 3 cấp mô tả & ViChartFact; chuyển Audio Cấp 1 sang đang tổng hợp
    yield (
        gr.update(),
        gr.update(),
        gr.update(value=desc_5s, placeholder="", elem_classes=["v-desc-box"]),
        gr.update(label="⏳ Đang tổng hợp giọng đọc Cấp 1 (Hoài My)...", elem_classes=["v-loading-audio"]),
        gr.update(value=desc_30s, placeholder="", elem_classes=["v-desc-box"]),
        gr.update(),
        gr.update(value=desc_study, placeholder="", elem_classes=["v-desc-box"]),
        gr.update(),
        gr.update(value=vichartfact_html),
        gr.update(),
        []
    )

    # Bước 4: Chuẩn hóa ngữ âm & Xuất tuần tự 3 file Audio TTS riêng biệt với giọng đọc Hoài My
    new_session_files = []
    tts_engines_used = set()

    # 4.1. Cấp 1: Tổng quan nhanh 5s
    audio1_path = os.path.join(TEMP_AUDIO_DIR, f"tts_lvl1_{uuid.uuid4().hex[:8]}.mp3")
    ok1, eng1 = generate_tts_audio_sync(desc_5s, audio1_path, voice_id=HOAI_MY_VOICE_ID)
    res_audio1 = audio1_path if (ok1 and os.path.exists(audio1_path)) else None
    if res_audio1:
        new_session_files.append(res_audio1)
        tts_engines_used.add(eng1)

    # YIELD 3: Xong Audio Cấp 1 -> Tắt loading Audio Cấp 1 & hiện trình phát; chuyển Audio Cấp 2 sang đang tổng hợp
    yield (
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(value=res_audio1, label="🎧 Trình phát Cấp 1 (Hoài My)", elem_classes=[]),
        gr.update(),
        gr.update(label="⏳ Đang tổng hợp giọng đọc Cấp 2 (Hoài My)...", elem_classes=["v-loading-audio"]),
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
        list(new_session_files)
    )

    # 4.2. Cấp 2: Tóm tắt sư phạm 30s
    audio2_path = os.path.join(TEMP_AUDIO_DIR, f"tts_lvl2_{uuid.uuid4().hex[:8]}.mp3")
    ok2, eng2 = generate_tts_audio_sync(desc_30s, audio2_path, voice_id=HOAI_MY_VOICE_ID)
    res_audio2 = audio2_path if (ok2 and os.path.exists(audio2_path)) else None
    if res_audio2:
        new_session_files.append(res_audio2)
        tts_engines_used.add(eng2)

    # YIELD 4: Xong Audio Cấp 2 -> Tắt loading Audio Cấp 2 & hiện trình phát; chuyển Audio Cấp 3 sang đang tổng hợp
    yield (
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(value=res_audio2, label="🎧 Trình phát Cấp 2 (Hoài My)", elem_classes=[]),
        gr.update(),
        gr.update(label="⏳ Đang tổng hợp giọng đọc Cấp 3 (Hoài My)...", elem_classes=["v-loading-audio"]),
        gr.update(),
        gr.update(),
        list(new_session_files)
    )

    # 4.3. Cấp 3: Phân tích học tập chuyên sâu
    audio3_path = os.path.join(TEMP_AUDIO_DIR, f"tts_lvl3_{uuid.uuid4().hex[:8]}.mp3")
    ok3, eng3 = generate_tts_audio_sync(desc_study, audio3_path, voice_id=HOAI_MY_VOICE_ID)
    res_audio3 = audio3_path if (ok3 and os.path.exists(audio3_path)) else None
    if res_audio3:
        new_session_files.append(res_audio3)
        tts_engines_used.add(eng3)

    if new_session_files:
        eng_summary = "; ".join(tts_engines_used)
        tts_status_msg = make_toast_html(
            title="Đã Hoàn Thành Pipeline 4 Bước",
            message=f"Đã trích xuất ma trận, kiểm chứng logic và tạo giọng đọc Hoài My ({html.escape(eng_summary)}) cho cả 3 cấp độ thành công.",
            toast_type="success"
        )
    else:
        tts_status_msg = make_toast_html(
            title="Hoàn Thành Pipeline (Cảnh Báo TTS)",
            message="Đã sinh mô tả 3 cấp độ và đối kiểm ViChartFact, nhưng không thể kết nối dịch vụ âm thanh TTS lúc này.",
            toast_type="warning"
        )

    # YIELD 5 (Cuối cùng): Tắt loading Audio Cấp 3 & hiện trình phát + thông báo Toast hoàn tất
    yield (
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(value=res_audio3, label="🎧 Trình phát Cấp 3 (Hoài My)", elem_classes=[]),
        gr.update(),
        gr.update(value=tts_status_msg),
        list(new_session_files)
    )

def regenerate_single_level(
    level_num: int,
    text: str,
    current_session_files: List[str]
) -> Tuple[Optional[str], str, List[str]]:
    """Tạo lại âm thanh riêng cho một cấp độ khi người dùng bấm nút Nghe lại với giọng Hoài My."""
    if not text or not text.strip():
        info_toast = make_toast_html(f"Cấp {level_num}", "Chưa có nội dung mô tả để tạo âm thanh.", "warning")
        return None, info_toast, current_session_files

    prefix_map = {1: "tts_lvl1_", 2: "tts_lvl2_", 3: "tts_lvl3_"}
    prefix = prefix_map.get(level_num, "tts_")

    # Xóa file tạm cũ của cấp độ này nếu có trong session
    remaining_files = []
    for f in current_session_files:
        if prefix in os.path.basename(f):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        else:
            remaining_files.append(f)

    speech_text = text.strip()
    audio_path = os.path.join(TEMP_AUDIO_DIR, f"{prefix}{uuid.uuid4().hex[:8]}.mp3")
    ok, eng = generate_tts_audio_sync(speech_text, audio_path, voice_id=HOAI_MY_VOICE_ID)
    if ok and os.path.exists(audio_path):
        remaining_files.append(audio_path)
        msg_toast = make_toast_html(
            title=f"Đã Tạo Lại Giọng Đọc Cấp {level_num}",
            message=f"Đã tổng hợp âm thanh giọng đọc Hoài My ({html.escape(eng)}) thành công.",
            toast_type="info"
        )
        return audio_path, msg_toast, remaining_files
    else:
        err_toast = make_toast_html(
            title=f"Lỗi Tạo Giọng Đọc Cấp {level_num}",
            message=f"Không thể tạo âm thanh cho Cấp {level_num}: {html.escape(eng)}.",
            toast_type="error"
        )
        return None, err_toast, remaining_files

def select_sample_chart(sample_filename: str, current_session_files: List[str]):
    """Khi bấm chọn một trong 6 ảnh mẫu đại diện: xóa sạch dữ liệu cũ và nạp ảnh mới."""
    cleanup_temp_files_list(current_session_files)
    sample_path = DATASET_FILEPATHS.get(sample_filename)
    if not sample_path or not os.path.exists(sample_path):
        sample_path = os.path.join(DATASET_DIR, sample_filename)
    return (
        sample_path,      # input_image
        pd.DataFrame(),   # out_meta_df
        pd.DataFrame(),   # out_matrix_df
        gr.update(value="", placeholder="Nội dung mô tả Cấp 1 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
        gr.update(value=None, label="🎧 Trình phát Cấp 1 (Hoài My)", elem_classes=[]),
        gr.update(value="", placeholder="Nội dung mô tả Cấp 2 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
        gr.update(value=None, label="🎧 Trình phát Cấp 2 (Hoài My)", elem_classes=[]),
        gr.update(value="", placeholder="Nội dung mô tả Cấp 3 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
        gr.update(value=None, label="🎧 Trình phát Cấp 3 (Hoài My)", elem_classes=[]),
        "",               # out_vichartfact
        "",               # out_tts_status
        []                # session_audio_tracker
    )

def on_image_uploaded(current_session_files: List[str]):
    """Khi người dùng tải ảnh mới từ máy tính lên: xóa sạch output cũ ngay lập tức."""
    cleanup_temp_files_list(current_session_files)
    return (
        pd.DataFrame(),   # out_meta_df
        pd.DataFrame(),   # out_matrix_df
        gr.update(value="", placeholder="Nội dung mô tả Cấp 1 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
        gr.update(value=None, label="🎧 Trình phát Cấp 1 (Hoài My)", elem_classes=[]),
        gr.update(value="", placeholder="Nội dung mô tả Cấp 2 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
        gr.update(value=None, label="🎧 Trình phát Cấp 2 (Hoài My)", elem_classes=[]),
        gr.update(value="", placeholder="Nội dung mô tả Cấp 3 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
        gr.update(value=None, label="🎧 Trình phát Cấp 3 (Hoài My)", elem_classes=[]),
        "",               # out_vichartfact
        "",               # out_tts_status
        []                # session_audio_tracker
    )

def on_reset_click(current_session_files: List[str]):
    """Khi bấm nút Đặt lại: xóa sạch file tạm của cả 3 cấp và xóa toàn bộ dữ liệu trên giao diện."""
    cleanup_temp_files_list(current_session_files)
    return (
        None,             # input_image
        pd.DataFrame(),   # out_meta_df
        pd.DataFrame(),   # out_matrix_df
        gr.update(value="", placeholder="Nội dung mô tả Cấp 1 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
        gr.update(value=None, label="🎧 Trình phát Cấp 1 (Hoài My)", elem_classes=[]),
        gr.update(value="", placeholder="Nội dung mô tả Cấp 2 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
        gr.update(value=None, label="🎧 Trình phát Cấp 2 (Hoài My)", elem_classes=[]),
        gr.update(value="", placeholder="Nội dung mô tả Cấp 3 sẽ xuất hiện tại đây sau khi chạy pipeline...", elem_classes=["v-desc-box"]),
        gr.update(value=None, label="🎧 Trình phát Cấp 3 (Hoài My)", elem_classes=[]),
        "",               # out_vichartfact
        "",               # out_tts_status
        []                # session_audio_tracker
    )

# ==============================================================================
# 10. GIAO DIỆN NGƯỜI DÙNG GRADIO BLOCKS (REDESIGNED THEO BẢN THIẾT KẾ CODE.HTML)
# ==============================================================================
custom_css = """
@import url('https://fonts.googleapis.com/css2?family=Mulish:ital,wght@0,300..900;1,300..900&family=Recursive:wght@400..700&family=Source+Code+Pro:wght@400;600;700&display=swap');

:root {
    --primary-color: #1A40C2;
    --primary-hover: #133299;
    --bg-surface: #F7F8FC;
    --card-bg: #FFFFFF;
    --border-color: #E2E6F0;
    --text-primary: #1F2937;
    --text-secondary: #4B5563;
}

body, .gradio-container {
    font-family: 'Mulish', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    background-color: #F7F8FC !important;
    color: #1F2937 !important;
}

.gradio-container {
    max-width: 1400px !important;
    margin: 0 auto !important;
    padding: 16px 20px !important;
}

/* Tab Bar: 3 Tab gọn gàng trên 1 hàng duy nhất, tuyệt đối không bị tràn hay nhảy menu ... trên màn hình desktop */
.tab-nav {
    display: flex !important;
    flex-wrap: nowrap !important;
    border-bottom: 2px solid #E2E6F0 !important;
    gap: 6px !important;
    margin-bottom: 16px !important;
    overflow-x: auto !important;
}

.tab-nav button {
    font-family: 'Mulish', sans-serif !important;
    font-size: 13.5px !important;
    font-weight: 700 !important;
    padding: 9px 16px !important;
    border-radius: 8px 8px 0 0 !important;
    border: none !important;
    background: transparent !important;
    color: #4B5563 !important;
    transition: all 0.2s ease !important;
    white-space: nowrap !important;
    flex-shrink: 0 !important;
}

.tab-nav button.selected {
    color: #1A40C2 !important;
    border-bottom: 3px solid #1A40C2 !important;
    background: #FFFFFF !important;
}

/* Toast Notification - Nổi góc dưới bên phải màn hình, tự động biến mất sau 10 giây */
.v-toast-wrapper {
    position: fixed !important;
    bottom: 24px !important;
    right: 24px !important;
    z-index: 999999 !important;
    max-width: 400px !important;
    width: calc(100vw - 48px) !important;
    pointer-events: none !important;
    animation: toastFadeInOut 10s cubic-bezier(0.16, 1, 0.3, 1) forwards !important;
}

.v-toast-card {
    pointer-events: auto !important;
    background: #FFFFFF !important;
    border: 1px solid #E2E6F0 !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.12), 0 8px 10px -6px rgba(0, 0, 0, 0.08) !important;
    display: flex !important;
    align-items: flex-start !important;
    gap: 12px !important;
}

@keyframes toastFadeInOut {
    0% {
        opacity: 0;
        transform: translateY(24px) scale(0.96);
    }
    4% {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
    88% {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
    100% {
        opacity: 0;
        transform: translateY(-8px) scale(0.96);
        visibility: hidden;
    }
}

/* Thẻ khung hiển thị & Card phong cách code.html */
.v-card {
    background: #FFFFFF !important;
    border: 1px solid #E2E6F0 !important;
    border-radius: 12px !important;
    padding: 16px !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04) !important;
    margin-bottom: 14px !important;
}

/* Nút chọn biểu đồ mẫu trong grid */
.sample-card-btn {
    background: #FFFFFF !important;
    border: 1px solid #E2E6F0 !important;
    border-radius: 8px !important;
    padding: 8px 10px !important;
    text-align: left !important;
    font-weight: 600 !important;
    font-size: 12px !important;
    color: #1F2937 !important;
    transition: all 0.15s ease !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02) !important;
}

.sample-card-btn:hover {
    border-color: #1A40C2 !important;
    background: #F0F4FF !important;
    transform: translateY(-1px) !important;
}

/* Nút Thực thi chính & Nút Đặt lại */
.btn-primary-action {
    background: #1A40C2 !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    font-size: 14.5px !important;
    border-radius: 8px !important;
    box-shadow: 0 2px 6px rgba(26, 64, 194, 0.25) !important;
}

.btn-primary-action:hover {
    background: #133299 !important;
}

.btn-secondary-action {
    background: #FFFFFF !important;
    border: 1px solid #C9CDDC !important;
    color: #374151 !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
}

.btn-secondary-action:hover {
    background: #F9FAFB !important;
    border-color: #9CA3AF !important;
}

/* Bật tự động xuống dòng cho bảng DataFrame để không bị cắt cụt chữ */
.gradio-dataframe table td,
.gradio-dataframe table th,
div[data-testid="dataframe"] table td,
div[data-testid="dataframe"] table th {
    white-space: normal !important;
    word-break: break-word !important;
    overflow-wrap: break-word !important;
    line-height: 1.55 !important;
}

textarea {
    font-family: 'Mulish', sans-serif !important;
    font-size: 14px !important;
    line-height: 1.65 !important;
}

/* Khung mô tả 3 cấp độ: Tự giãn chiều cao theo nội dung thực tế, không cắt nửa dòng */
.v-desc-box,
.v-desc-box > label,
.v-desc-box .wrap,
.v-desc-box .input-container {
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
}

.v-desc-box textarea {
    font-family: 'Mulish', sans-serif !important;
    font-size: 14px !important;
    line-height: 1.65 !important;
    height: auto !important;
    min-height: 54px !important;
    max-height: none !important;
    overflow: visible !important;
    overflow-y: visible !important;
    resize: none !important;
    field-sizing: content !important;
    padding: 10px 12px 12px 12px !important;
}

/* Hiệu ứng đang tải tự viết (CSS Shimmer & Spinner thuần, không dùng link ngoài) */
@keyframes vShimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

@keyframes vSpin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}

.v-spinner {
    width: 22px;
    height: 22px;
    border: 3px solid #E2E8F0;
    border-top-color: #1A40C2;
    border-radius: 50%;
    animation: vSpin 0.8s linear infinite;
    display: inline-block;
    flex-shrink: 0;
}

.v-shimmer-bar {
    background: linear-gradient(90deg, #F1F5F9 25%, #E2E8F0 50%, #F1F5F9 75%);
    background-size: 200% 100%;
    animation: vShimmer 1.4s ease-in-out infinite;
    border-radius: 6px;
}

.v-desc-box.v-loading-box textarea {
    background: linear-gradient(90deg, #F8FAFC 25%, #EEF2FF 50%, #F8FAFC 75%) !important;
    background-size: 200% 100% !important;
    animation: vShimmer 1.4s ease-in-out infinite !important;
    border-left: 4px solid #1A40C2 !important;
    color: #475569 !important;
}

.v-loading-audio {
    position: relative !important;
    background: linear-gradient(90deg, #F8FAFC 25%, #EEF2FF 50%, #F8FAFC 75%) !important;
    background-size: 200% 100% !important;
    animation: vShimmer 1.4s ease-in-out infinite !important;
    border: 1px dashed #93C5FD !important;
    border-radius: 8px !important;
}

.v-loading-audio label::after {
    content: "";
    display: inline-block;
    width: 12px;
    height: 12px;
    margin-left: 8px;
    border: 2px solid #CBD5E1;
    border-top-color: #1A40C2;
    border-radius: 50%;
    animation: vSpin 0.8s linear infinite;
    vertical-align: middle;
}

/* Mục 3 ViChartFact Collapsible Details */
details.v-fact-details {
    border: 1px solid #E2E6F0 !important;
    border-radius: 8px !important;
    background: #FFFFFF !important;
    overflow: hidden !important;
}

details.v-fact-details summary {
    padding: 12px 16px !important;
    background-color: #F8F9FC !important;
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    cursor: pointer !important;
    user-select: none !important;
    font-weight: 700 !important;
    font-size: 13.5px !important;
    color: #1E293B !important;
    list-style: none !important;
    transition: background 0.15s ease !important;
}

details.v-fact-details summary:hover {
    background-color: #F1F5F9 !important;
}

details.v-fact-details summary::-webkit-details-marker {
    display: none !important;
}

details.v-fact-details summary .v-expand-icon {
    transition: transform 0.2s ease !important;
    display: inline-block !important;
    color: #64748B !important;
    font-size: 12px !important;
}

details.v-fact-details[open] summary .v-expand-icon {
    transform: rotate(180deg) !important;
}

details.v-fact-details[open] summary {
    border-bottom: 1px solid #E2E6F0 !important;
}
"""

# 6 ảnh mẫu đại diện có trên đĩa và map chính xác 100% với các dạng biểu đồ SGK
SAMPLE_TARGETS = [
    "Biểu đồ cột_1.png",       # Cột đơn (Hoa Kỳ, Trung Quốc, Ấn Độ - Hình 34.3)
    "Biểu đồ cột_38.jpg",      # Cột ghép (Tuổi thọ trung bình Nam - Nữ)
    "Biểu đồ tròn_1.jpeg",     # Tròn cơ cấu (Nguồn điện 0.8%, tổng 99.8% ~ 100%)
    "Biểu đồ đường_1.png",     # Đường xu hướng (Thu nhập bình quân đầu người)
    "Biểu đồ miền_1.webp",     # Miền chuyển dịch (Cơ cấu GDP 3 ngành kinh tế)
    "Biểu đồ kết hợp_1.png"    # Kết hợp cột & đường (Sản lượng & giá trị thủy sản)
]

sample_examples = []
for target_name in SAMPLE_TARGETS:
    if target_name in DATASET_FILEPATHS and os.path.exists(DATASET_FILEPATHS[target_name]):
        sample_examples.append(DATASET_FILEPATHS[target_name])

with gr.Blocks(title="V-ChartText Web Demo") as demo:
    # State theo dõi danh sách file audio tạm của phiên để dọn rác tự động
    session_audio_tracker = gr.State(value=[])

    # Header chuẩn theo phong cách code.html
    gr.HTML("""
    <div style="background: #FFFFFF; border-bottom: 1px solid #E2E6F0; border-radius: 12px; padding: 18px 24px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 14px;">
                <div style="width: 44px; height: 44px; border-radius: 10px; background: #1A40C2; color: #FFFFFF; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 22px; box-shadow: 0 2px 6px rgba(26,64,194,0.3);">
                    V
                </div>
                <div>
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <h1 style="margin: 0; font-size: 21px; font-weight: 800; color: #1F2937; letter-spacing: -0.4px;">
                            V-ChartText
                        </h1>
                        <span style="background: #EEF2FF; color: #1A40C2; font-weight: 700; font-size: 11.5px; padding: 3px 10px; border-radius: 9999px; border: 1px solid #C4D4FF;">
                            Sư phạm &amp; Trợ năng SGK
                        </span>
                    </div>
                    <p style="margin: 3px 0 0 0; font-size: 13.5px; color: #4B5563;">
                        Hệ thống trích xuất, kiểm chứng logic &amp; thuyết minh biểu đồ Địa lí qua Pipeline 4 Bước
                    </p>
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <span style="display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 9999px; font-size: 12px; font-weight: 600; background: #E6F4EA; color: #137333; border: 1px solid #CEEAD6;">
                    <span style="width: 7px; height: 7px; border-radius: 50%; background: #137333;"></span>
                    Pipeline 4 Bước Active
                </span>
                <span style="font-size: 12px; color: #6B7280; border-left: 1px solid #E2E6F0; padding-left: 10px;">
                    Giọng đọc Hoài My (Nữ - Truyền cảm)
                </span>
            </div>
        </div>
    </div>
    """)

    with gr.Row():
        # ----------------------------------------------------------------------
        # CỘT TRÁI (SCALE 5): TẢI ẢNH, ĐIỀU KHIỂN & BỘ CHỌN MẪU SGK
        # ----------------------------------------------------------------------
        with gr.Column(scale=5):
            with gr.Group(elem_classes=["v-card"]):
                gr.HTML("""
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <div style="display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 13px; color: #1F2937; text-transform: uppercase;">
                        <span>🖼️</span> ẢNH BIỂU ĐỒ ĐẦU VÀO
                    </div>
                    <span style="font-size: 11px; color: #6B7280;">Hỗ trợ PNG, JPG, WEBP</span>
                </div>
                """)
                input_image = gr.Image(type="filepath", show_label=False)

                with gr.Row():
                    btn_run = gr.Button("🚀 Thực Thi Pipeline 4 Bước", variant="primary", scale=7, elem_classes=["btn-primary-action"])
                    btn_clear = gr.Button("🔄 Đặt lại", scale=3, elem_classes=["btn-secondary-action"])

            # Khối chọn nhanh 6 dạng biểu đồ SGK theo phong cách grid cards của code.html
            with gr.Group(elem_classes=["v-card"]):
                gr.HTML("""
                <div style="margin-bottom: 10px;">
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <span style="font-weight: 700; font-size: 13px; color: #1F2937; text-transform: uppercase; letter-spacing: 0.3px;">
                            TẬP MẪU ĐẠI DIỆN SGK (6 DẠNG CHUẨN)
                        </span>
                        <span style="font-size: 11px; background: #EEF2FF; color: #1A40C2; font-weight: 700; padding: 2px 8px; border-radius: 9999px;">
                            6 mẫu chuẩn
                        </span>
                    </div>
                    <p style="margin: 4px 0 0 0; font-size: 12px; color: #6B7280;">
                        Bấm chọn nhanh để thử nghiệm các dạng biểu đồ trong chương trình Địa lí
                    </p>
                </div>
                """)
                with gr.Row():
                    btn_sample_1 = gr.Button("📊 Cột đơn\nHoa Kỳ, TQ, Ấn Độ", size="sm", elem_classes=["sample-card-btn"])
                    btn_sample_2 = gr.Button("📶 Cột ghép\nTuổi thọ Nam - Nữ", size="sm", elem_classes=["sample-card-btn"])
                    btn_sample_3 = gr.Button("🥧 Tròn\nCơ cấu nguồn điện", size="sm", elem_classes=["sample-card-btn"])
                with gr.Row():
                    btn_sample_4 = gr.Button("📈 Đường\nThu nhập bình quân", size="sm", elem_classes=["sample-card-btn"])
                    btn_sample_5 = gr.Button("🏔️ Miền\nCơ cấu GDP 3 ngành", size="sm", elem_classes=["sample-card-btn"])
                    btn_sample_6 = gr.Button("📉 Kết hợp\nSản lượng & giá trị", size="sm", elem_classes=["sample-card-btn"])

                if sample_examples:
                    gr.HTML("<div style='margin-top: 12px; font-size: 12px; color: #6B7280; font-weight: 600;'>Hoặc duyệt dạng danh sách ảnh:</div>")
                    gr.Examples(
                        examples=[[ex] for ex in sample_examples],
                        inputs=input_image,
                        label=None
                    )

        # ----------------------------------------------------------------------
        # CỘT PHẢI (SCALE 7): 2 TAB DUY NHẤT (BẢNG & KIỂM CHỨNG | MÔ TẢ 3 CẤP & TTS)
        # ----------------------------------------------------------------------
        with gr.Column(scale=7):
            # Tab 1: Bảng dữ liệu & Kiểm chứng
            with gr.Tab("📊 1. Bảng & Kiểm Chứng"):
                with gr.Group(elem_classes=["v-card"]):
                    gr.HTML("<div style='font-weight: 700; color: #1F2937; margin-bottom: 8px; font-size: 13.5px;'>📋 ĐẶC TẢ THUỘC TÍNH BIỂU ĐỒ</div>")
                    out_meta_df = gr.DataFrame(headers=["Thuộc tính", "Nội dung"], datatype=["str", "str"], wrap=True, interactive=False)
                with gr.Group(elem_classes=["v-card"]):
                    gr.HTML("<div style='font-weight: 700; color: #1F2937; margin-bottom: 8px; font-size: 13.5px;'>🔢 MA TRẬN SỐ LIỆU ĐÃ KIỂM CHỨNG &amp; GẮN CỜ BẤT ĐỊNH</div>")
                    out_matrix_df = gr.DataFrame(wrap=True, interactive=False)

            # Tab 2: Sinh mô tả 3 cấp độ & Giọng đọc TTS trực tiếp
            with gr.Tab("🎧 2. Mô Tả 3 Cấp & Giọng Đọc"):
                # Cấp 1: Tổng quan 5s
                with gr.Group(elem_classes=["v-card"]):
                    gr.HTML("""
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="background: #1A40C2; color: #FFFFFF; width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 800;">1</span>
                            <span style="font-weight: 800; color: #1A40C2; font-size: 14px;">CẤP 1 • TỔNG QUAN 5 GIÂY</span>
                        </div>
                        <span style="font-size: 11px; background: #EEF2FF; color: #1A40C2; font-weight: 700; padding: 2px 8px; border-radius: 9999px;">NHẬN THỨC NHANH</span>
                    </div>
                    """)
                    out_desc_5s = gr.Textbox(lines=2, max_lines=50, show_label=False, interactive=False, autoscroll=False, elem_classes=["v-desc-box"], placeholder="Nội dung mô tả Cấp 1 sẽ xuất hiện tại đây sau khi chạy pipeline...")
                    with gr.Row():
                        out_audio_lvl1 = gr.Audio(
                            label="🎧 Trình phát Cấp 1 (Hoài My)",
                            type="filepath",
                            interactive=False,
                            autoplay=False,
                            scale=8
                        )
                        btn_read_lvl1 = gr.Button("🔊 Nghe lại", variant="secondary", size="sm", scale=2, elem_classes=["btn-secondary-action"])

                # Cấp 2: Tóm tắt sư phạm 30s
                with gr.Group(elem_classes=["v-card"]):
                    gr.HTML("""
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="background: #0F766E; color: #FFFFFF; width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 800;">2</span>
                            <span style="font-weight: 800; color: #0F766E; font-size: 14px;">CẤP 2 • TÓM TẮT SƯ PHẠM 30 GIÂY</span>
                        </div>
                        <span style="font-size: 11px; background: #E6FFFA; color: #0F766E; font-weight: 700; padding: 2px 8px; border-radius: 9999px;">TRỌNG TÂM &amp; CỰC TRỊ</span>
                    </div>
                    """)
                    out_desc_30s = gr.Textbox(lines=3, max_lines=80, show_label=False, interactive=False, autoscroll=False, elem_classes=["v-desc-box"], placeholder="Nội dung mô tả Cấp 2 sẽ xuất hiện tại đây sau khi chạy pipeline...")
                    with gr.Row():
                        out_audio_lvl2 = gr.Audio(
                            label="🎧 Trình phát Cấp 2 (Hoài My)",
                            type="filepath",
                            interactive=False,
                            autoplay=False,
                            scale=8
                        )
                        btn_read_lvl2 = gr.Button("🔊 Nghe lại", variant="secondary", size="sm", scale=2, elem_classes=["btn-secondary-action"])

                # Cấp 3: Phân tích học tập chuyên sâu
                with gr.Group(elem_classes=["v-card"]):
                    gr.HTML("""
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="background: #6D28D9; color: #FFFFFF; width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 800;">3</span>
                            <span style="font-weight: 800; color: #6D28D9; font-size: 14px;">CẤP 3 • PHÂN TÍCH HỌC TẬP CHUYÊN SÂU</span>
                        </div>
                        <span style="font-size: 11px; background: #F3E8FF; color: #6D28D9; font-weight: 700; padding: 2px 8px; border-radius: 9999px;">TOÀN DIỆN SỐ LIỆU</span>
                    </div>
                    """)
                    out_desc_study = gr.Textbox(lines=5, max_lines=150, show_label=False, interactive=False, autoscroll=False, elem_classes=["v-desc-box"], placeholder="Nội dung mô tả Cấp 3 sẽ xuất hiện tại đây sau khi chạy pipeline...")
                    with gr.Row():
                        out_audio_lvl3 = gr.Audio(
                            label="🎧 Trình phát Cấp 3 (Hoài My)",
                            type="filepath",
                            interactive=False,
                            autoplay=False,
                            scale=8
                        )
                        btn_read_lvl3 = gr.Button("🔊 Nghe lại", variant="secondary", size="sm", scale=2, elem_classes=["btn-secondary-action"])

            # Tab 3: Đo kiểm ViChartFact độc lập (Mục 3 theo thiết kế stitch_v_charttext_ui_redesign_3)
            with gr.Tab("🛡️ 3. ViChartFact"):
                out_vichartfact = gr.HTML(value="")

        # Khung thông báo nổi Toast (Bottom-Right, fixed, tự động biến mất sau 10 giây)
        out_tts_status = gr.HTML(value="")

    # --------------------------------------------------------------------------
    # RÀNG BUỘC SỰ KIỆN (EVENT LISTENERS ĐỒNG BỘ 100%)
    # --------------------------------------------------------------------------
    # 1. Nút Thực thi Pipeline 4 bước
    btn_run.click(
        fn=process_pipeline_demo,
        inputs=[input_image, session_audio_tracker],
        outputs=[
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    # 2. 6 Nút chọn nhanh biểu đồ mẫu: Tự động tải ảnh & xóa trắng output cũ
    btn_sample_1.click(
        fn=lambda s: select_sample_chart("Biểu đồ cột_1.png", s),
        inputs=[session_audio_tracker],
        outputs=[
            input_image,
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    btn_sample_2.click(
        fn=lambda s: select_sample_chart("Biểu đồ cột_38.jpg", s),
        inputs=[session_audio_tracker],
        outputs=[
            input_image,
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    btn_sample_3.click(
        fn=lambda s: select_sample_chart("Biểu đồ tròn_1.jpeg", s),
        inputs=[session_audio_tracker],
        outputs=[
            input_image,
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    btn_sample_4.click(
        fn=lambda s: select_sample_chart("Biểu đồ đường_1.png", s),
        inputs=[session_audio_tracker],
        outputs=[
            input_image,
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    btn_sample_5.click(
        fn=lambda s: select_sample_chart("Biểu đồ miền_1.webp", s),
        inputs=[session_audio_tracker],
        outputs=[
            input_image,
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    btn_sample_6.click(
        fn=lambda s: select_sample_chart("Biểu đồ kết hợp_1.png", s),
        inputs=[session_audio_tracker],
        outputs=[
            input_image,
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    # 3. Khi tải ảnh mới lên: xóa trắng kết quả cũ ngay lập tức
    input_image.upload(
        fn=on_image_uploaded,
        inputs=[session_audio_tracker],
        outputs=[
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    # 4. Khi bấm xóa ảnh trên khung tải: reset toàn bộ giao diện
    input_image.clear(
        fn=on_reset_click,
        inputs=[session_audio_tracker],
        outputs=[
            input_image,
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    # 5. Nút Đặt lại: reset ảnh & toàn bộ kết quả về trạng thái ban đầu
    btn_clear.click(
        fn=on_reset_click,
        inputs=[session_audio_tracker],
        outputs=[
            input_image,
            out_meta_df,
            out_matrix_df,
            out_desc_5s,
            out_audio_lvl1,
            out_desc_30s,
            out_audio_lvl2,
            out_desc_study,
            out_audio_lvl3,
            out_vichartfact,
            out_tts_status,
            session_audio_tracker
        ]
    )

    # 6. Nghe lại riêng lẻ từng cấp độ với giọng Hoài My
    btn_read_lvl1.click(
        fn=lambda desc, s: regenerate_single_level(1, desc, s),
        inputs=[out_desc_5s, session_audio_tracker],
        outputs=[out_audio_lvl1, out_tts_status, session_audio_tracker]
    )

    btn_read_lvl2.click(
        fn=lambda desc, s: regenerate_single_level(2, desc, s),
        inputs=[out_desc_30s, session_audio_tracker],
        outputs=[out_audio_lvl2, out_tts_status, session_audio_tracker]
    )

    btn_read_lvl3.click(
        fn=lambda desc, s: regenerate_single_level(3, desc, s),
        inputs=[out_desc_study, session_audio_tracker],
        outputs=[out_audio_lvl3, out_tts_status, session_audio_tracker]
    )

    # Footer theo chuẩn code.html
    gr.HTML("""
    <div style="text-align: center; margin-top: 32px; padding: 16px; border-top: 1px solid #E2E6F0; color: #6B7280; font-size: 13px;">
        V-ChartText © 2026 | Phát triển bởi Nhóm 7 – Vấn đề hiện đại của CNTT | Bản Web Demo
    </div>
    """)

# Cho phép khởi chạy độc lập & triển khai Render Web Service
if __name__ == "__main__":
    demo.queue()
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
        share=False,
        theme=gr.themes.Soft(),
        css=custom_css
    )
