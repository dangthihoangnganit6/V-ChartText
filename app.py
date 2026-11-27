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

# Trạng thái nạp mô hình VLM thực tế (chỉ khả dụng khi có CUDA/GPU rời)
VLM_MODEL_LOADED = False

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
# 3. NẠP CƠ SỞ DỮ LIỆU ĐÃ KIỂM CHỨNG & LẬP CHỈ MỤC TẬP DỮ LIỆU
# ==============================================================================
DATABASE_RECORDS: Dict[str, Dict[str, Any]] = {}
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

# Nạp Benchmark ground truth
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
                DATABASE_RECORDS[img_n] = rec
                DATABASE_RECORDS[img_n.lower()] = rec
                if img_n.endswith(".png"):
                    DATABASE_RECORDS[img_n.replace(".png", ".jpg")] = rec
                elif img_n.endswith(".jpg"):
                    DATABASE_RECORDS[img_n.replace(".jpg", ".png")] = rec
        print(f"✓ Đã nạp {len(df_bm)} bản ghi đối chuẩn từ benchmark.xlsx.")
    except Exception as e:
        print(f"⚠️ Cảnh báo nạp benchmark.xlsx: {e}")

# Nạp Extracted Results
if os.path.exists(EXTRACTED_RESULTS_PATH):
    try:
        df_ext = pd.read_csv(EXTRACTED_RESULTS_PATH)
        for _, row in df_ext.iterrows():
            img_n = str(row.get("image_name", "")).strip()
            if img_n and img_n != "nan":
                if img_n not in DATABASE_RECORDS:
                    rec = {
                        "image_name": img_n,
                        "chart_title": str(row.get("chart_title", "")).strip() if pd.notna(row.get("chart_title")) else "Biểu đồ học tập SGK",
                        "chart_type": normalize_chart_type(row.get("chart_type", "column")),
                        "unit": str(row.get("unit", "")).strip() if pd.notna(row.get("unit")) else "",
                        "x_axis_label": str(row.get("x_axis_label", "")).strip() if pd.notna(row.get("x_axis_label")) else "Danh mục",
                        "categories": str(row.get("categories", "")).strip() if pd.notna(row.get("categories")) else "",
                        "series_name": str(row.get("series_name", "")).strip() if pd.notna(row.get("series_name")) else "Giá trị",
                        "values": str(row.get("values", "")).strip() if pd.notna(row.get("values")) else "",
                        "source": "extracted"
                    }
                    DATABASE_RECORDS[img_n] = rec
                    DATABASE_RECORDS[img_n.lower()] = rec
                else:
                    if pd.notna(row.get("validation_status")):
                        DATABASE_RECORDS[img_n]["validation_status"] = str(row.get("validation_status")).strip()
                    if pd.notna(row.get("validation_notes")):
                        DATABASE_RECORDS[img_n]["validation_notes"] = str(row.get("validation_notes")).strip()
        print(f"✓ Đã đồng bộ kết quả kiểm chứng từ {len(df_ext)} bản ghi extracted results.")
    except Exception as e:
        print(f"⚠️ Cảnh báo nạp extracted results: {e}")

# Lập chỉ mục toàn bộ ảnh trong thư mục dataset
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
# 4. BỘ TRA CỨU ẢNH THÔNG MINH (IMAGE RESOLVER)
# ==============================================================================
def resolve_image_match(input_image_path: str) -> Tuple[Optional[str], str]:
    """
    Khớp chính xác hình ảnh người dùng tải lên với tập dữ liệu SGK:
    1. Kiểm tra tên file trực tiếp (nếu giữ nguyên).
    2. Mã băm MD5 nguyên bản (100% byte-for-byte).
    3. Mã băm thị giác dHash khớp tuyệt đối.
    4. Mã băm thị giác dHash lân cận gần nhất (Hamming Distance <= 6, sai lệch tỉ lệ khung hình < 0.25).
    """
    if not input_image_path or not os.path.exists(input_image_path):
        return None, "File không tồn tại"

    base_name = os.path.basename(input_image_path).strip()

    # 1. Tên file trực tiếp
    if base_name in DATABASE_RECORDS:
        return DATABASE_RECORDS[base_name]["image_name"], f"Khớp trực tiếp tên file gốc: '{base_name}'"
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

    # Tra cứu chính xác ảnh qua bộ Resolver đa tầng
    matched_image_name, match_method = resolve_image_match(input_image_path)

    # --------------------------------------------------------------------------
    # TRƯỜNG HỢP 1: ẢNH NGOÀI TẬP MẪU (CHƯA CÓ TRONG CACHE)
    # --------------------------------------------------------------------------
    if not matched_image_name or matched_image_name not in DATABASE_RECORDS:
        if VLM_MODEL_LOADED:
            # Nếu có model VLM đang chạy trong bộ nhớ GPU, gọi suy luận trực tiếp ở đây
            pass
        else:
            # Môi trường local/cloud chưa nạp VLM: Tắt sạch hiệu ứng tải và báo cảnh báo trung thực
            empty_meta = pd.DataFrame([
                {"Thuộc tính": "Trạng thái tra cứu", "Nội dung": "Không tìm thấy trong 214 biểu đồ SGK đã kiểm chứng"},
                {"Thuộc tính": "Chi tiết đối sánh", "Nội dung": match_method},
                {"Thuộc tính": "Mô hình VLM cục bộ", "Nội dung": "Chưa nạp trọng số Qwen3-VL (yêu cầu GPU)"},
                {"Thuộc tính": "Khuyến nghị người dùng", "Nội dung": "Vui lòng chọn ảnh trong 'Tập mẫu đại diện' bên dưới hoặc tải ảnh thuộc dataset SGK"}
            ])
            empty_matrix = pd.DataFrame([
                {"Thông báo": "Không có ma trận số liệu trích xuất cho ảnh ngoài tập mẫu khi chưa nạp mô hình VLM."}
            ])
            notice_msg = "Ảnh chưa có trong tập dữ liệu đã trích xuất sẵn & môi trường local chưa nạp model VLM (Qwen3-VL). Vui lòng chọn một biểu đồ mẫu trong tập dữ liệu sách giáo khoa bên dưới để trải nghiệm đầy đủ pipeline 4 bước."
            empty_vichartfact = """
            <div style="background-color: #F8F9FC; border: 1px dashed #CBD5E1; border-radius: 8px; padding: 20px; text-align: center; color: #64748B; font-size: 13.5px; line-height: 1.5; margin-top: 10px;">
                🛡️ <b>Chưa thực hiện đo kiểm ViChartFact:</b> Do hình ảnh tải lên chưa có ma trận dữ liệu trích xuất để làm bảng chân lý đối chuẩn. Vui lòng chọn một biểu đồ trong <i>Tập mẫu đại diện</i> ở cột trái để quan sát quy trình đo kiểm ViChartFact chi tiết.
            </div>
            """
            warn_toast = make_toast_html("Ảnh Ngoài Tập Dữ Liệu", "Ảnh chưa có trong 214 biểu đồ SGK đã kiểm chứng & máy chưa nạp Qwen3-VL.", "warning")
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
                gr.update(value=warn_toast),
                []
            )
            return

    # --------------------------------------------------------------------------
    # TRƯỜNG HỢP 2: ẢNH KHỚP CHÍNH XÁC VỚI BẢN GHI TRONG DATASET
    # --------------------------------------------------------------------------
    raw_data = DATABASE_RECORDS[matched_image_name]
    step1_dict = {
        "chart_title": raw_data.get("chart_title", "Biểu đồ học tập SGK"),
        "chart_type": raw_data.get("chart_type", "column"),
        "unit": raw_data.get("unit", ""),
        "x_axis_label": raw_data.get("x_axis_label", "Danh mục"),
        "categories": raw_data.get("categories", ""),
        "series_name": raw_data.get("series_name", "Giá trị"),
        "values": raw_data.get("values", "")
    }

    # Bước 2: Kiểm chứng dữ liệu & Gắn cờ bất định (Bảo toàn 100% logic kiểm chứng)
    val_status, val_notes, parsed_matrix = validate_chart_data(step1_dict)
    flagged_matrix = apply_uncertainty_flagging(parsed_matrix, val_notes)

    # Bảng 1: Metadata chung (Hiển thị đầy đủ trạng thái kiểm chứng và ghi chú)
    meta_df = pd.DataFrame([
        {"Thuộc tính": "Tiêu đề biểu đồ", "Nội dung": step1_dict["chart_title"]},
        {"Thuộc tính": "Loại biểu đồ", "Nội dung": step1_dict["chart_type"]},
        {"Thuộc tính": "Đơn vị tính", "Nội dung": step1_dict["unit"] if step1_dict["unit"] else "Không ghi đơn vị"},
        {"Thuộc tính": "Trục hoành (Categories)", "Nội dung": " | ".join(flagged_matrix["categories"])},
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
    completeness_report = evaluate_description_completeness(
        desc_dict,
        step1_dict,
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
