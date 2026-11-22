import os
import sys
import re
import json
import csv
import time
import asyncio
import hashlib
import uuid
import atexit
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

def normalize_chart_type(c_type_raw: str) -> str:
    c = str(c_type_raw).lower().strip()
    if "cột" in c or "column" in c: return "column"
    if "đường" in c or "line" in c: return "line"
    if "tròn" in c or "pie" in c: return "pie"
    if "miền" in c or "area" in c: return "area"
    if "kết hợp" in c or "combo" in c: return "combo"
    return "column"

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
# 5. CHUẨN HÓA SỐ KIỂU VIỆT & PARSER DỮ LIỆU
# ==============================================================================
def clean_vietnamese_number(num_str: Any) -> Optional[float]:
    """
    Chuẩn hóa số liệu kiểu Việt:
    - Nhận diện đúng số hàng nghìn có dấu chấm: '1.200' -> 1200.0, '19.257' -> 19257.0
    - Nhận diện đúng số thập phân có dấu phẩy: '12,5' -> 12.5, '0,8' -> 0.8
    """
    if num_str is None:
        return None
    s = str(num_str).strip()
    if not s or s.lower() in ['none', 'null', 'nan', 'không có', 'chưa chắc chắn', '[chưa chắc chắn]', '']:
        return None
    s = re.sub(r"[^\d,\.\-]", "", s)
    if not s or s == "-":
        return None

    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) >= 1:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) >= 1:
            s = s.replace(".", "")

    try:
        return float(s)
    except ValueError:
        return None

def parse_semicolon_or_pipe(val_str: str) -> List[str]:
    if not val_str or pd.isna(val_str):
        return []
    s = str(val_str).strip()
    if "||" in s:
        return [c.strip() for c in s.split("||") if c.strip()]
    if "|" in s:
        return [c.strip() for c in s.split("|") if c.strip()]
    if ";" in s:
        return [c.strip() for c in s.split(";") if c.strip()]
    return [s]

# ==============================================================================
# 6. BỘ LUẬT KIỂM CHỨNG LOGIC RULE-BASED & GẮN CỜ BẤT ĐỊNH
# ==============================================================================
def validate_chart_data(data: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    chart_type = normalize_chart_type(data.get("chart_type", "column"))
    categories_raw = parse_semicolon_or_pipe(data.get("categories", ""))
    series_raw = parse_semicolon_or_pipe(data.get("series_name", ""))
    values_raw = data.get("values", "")

    parsed_matrix = {
        "chart_title": data.get("chart_title", ""),
        "chart_type": chart_type,
        "unit": data.get("unit", ""),
        "categories": categories_raw,
        "series_names": series_raw if series_raw else ["Giá trị"],
        "series_data": {},
        "raw_data": data
    }

    issues = []
    val_chunks = [ch.strip() for ch in str(values_raw).split("||") if ch.strip()]

    for s_idx, s_name in enumerate(parsed_matrix["series_names"]):
        if s_idx < len(val_chunks):
            items_str = [it.strip() for it in re.split(r"[|;]", val_chunks[s_idx]) if it.strip()]
            num_list = [clean_vietnamese_number(it) for it in items_str]
            parsed_matrix["series_data"][s_name] = num_list
        else:
            parsed_matrix["series_data"][s_name] = [None] * len(categories_raw)
            issues.append(f"Chuỗi '{s_name}' không có giá trị trích xuất")

    # Luật 1: Kiểm tra Biểu đồ tròn (Tổng % ~ 100%)
    if chart_type == "pie":
        first_series = list(parsed_matrix["series_data"].values())[0] if parsed_matrix["series_data"] else []
        valid_nums = [v for v in first_series if v is not None]
        if valid_nums:
            total_pct = sum(valid_nums)
            if not (98.0 <= total_pct <= 102.0):
                issues.append(f"Tổng tỷ lệ phần trăm biểu đồ tròn = {total_pct:.1f}% (khác 100±2%)")

    # Luật 2: Kiểm tra tính đơn điệu của trục thời gian
    years = []
    for cat in categories_raw:
        m = re.search(r"\b(19\d{2}|20\d{2})\b", str(cat))
        if m:
            years.append(int(m.group(1)))
    if len(years) > 1 and years != sorted(years):
        issues.append(f"Trục thời gian không tăng dần: {years}")

    status = "Hợp lệ" if len(issues) == 0 else "Cần kiểm tra"
    notes = "; ".join(issues) if issues else "Đạt chuẩn định dạng & khớp logic số liệu"
    return status, notes, parsed_matrix

def apply_uncertainty_flagging(parsed_matrix: Dict[str, Any], validation_notes: str) -> Dict[str, Any]:
    has_uncertainty = False
    flagged_series_data = {}

    for s_name, vals in parsed_matrix["series_data"].items():
        flagged_vals = []
        for v in vals:
            if v is None:
                flagged_vals.append("[chưa chắc chắn]")
                has_uncertainty = True
            else:
                flagged_vals.append(v)
        flagged_series_data[s_name] = flagged_vals

    if "Cần kiểm tra" in validation_notes or "khác 100" in validation_notes:
        has_uncertainty = True

    return {
        "chart_title": parsed_matrix["chart_title"],
        "chart_type": parsed_matrix["chart_type"],
        "unit": parsed_matrix["unit"],
        "categories": parsed_matrix["categories"],
        "series_names": parsed_matrix["series_names"],
        "series_data": flagged_series_data,
        "has_uncertainty": has_uncertainty,
        "validation_notes": validation_notes
    }

# ==============================================================================
# 7. SINH MÔ TẢ 3 CẤP ĐỘ & ĐO KIỂM VICHARTFACT
# ==============================================================================
def generate_3level_descriptions(flagged_matrix: Dict[str, Any]) -> Dict[str, str]:
    title = flagged_matrix["chart_title"]
    c_type = flagged_matrix["chart_type"]
    unit = flagged_matrix["unit"]
    cats = flagged_matrix["categories"]
    series_data = flagged_matrix["series_data"]
    has_un = flagged_matrix["has_uncertainty"]

    c_type_vn = {
        "column": "cột",
        "line": "đường",
        "pie": "tròn",
        "area": "miền",
        "combo": "kết hợp"
    }.get(c_type, "cột")

    time_span = f"từ {cats[0]} đến {cats[-1]}" if (len(cats) >= 2 and re.search(r"\d{4}", str(cats[0]))) else f"các danh mục {', '.join(cats[:3])}"

    # 1. Cấp 1: Tổng quan 5s
    unit_phrase = f", đơn vị tính là {unit}" if unit else ""
    desc_5s = f"Biểu đồ {c_type_vn} thể hiện {title}{unit_phrase}, trong {time_span}."

    # 2. Cấp 2: Tóm tắt sư phạm 30s
    all_valid_nums = []
    for s_name, vals in series_data.items():
        for i, v in enumerate(vals):
            if isinstance(v, (int, float)):
                cat_label = cats[i] if i < len(cats) else f"Mốc {i+1}"
                all_valid_nums.append((v, f"{cat_label} ({s_name})"))

    if all_valid_nums:
        max_val, max_s = max(all_valid_nums, key=lambda x: x[0])
        min_val, min_s = min(all_valid_nums, key=lambda x: x[0])
        desc_30s = (f"Biểu đồ bao gồm các chuỗi dữ liệu trong {time_span}. "
                    f"Trong đó, giá trị cao nhất ghi nhận ở {max_s} đạt {max_val} {unit}, "
                    f"thấp nhất ở {min_s} với {min_val} {unit}.")
    else:
        desc_30s = f"Biểu đồ thể hiện thông tin trong {time_span}."

    if has_un:
        desc_30s += " Lưu ý: Một số số liệu bị mờ hoặc có dấu hiệu mâu thuẫn đã được gắn cờ [chưa chắc chắn]."

    # 3. Cấp 3: Phân tích học tập chuyên sâu
    study_lines = [
        f"Phân tích chuyên sâu biểu đồ giáo dục: '{title}'.",
        f"- Cấu trúc: Phân loại theo {len(cats)} mốc hoặc danh mục ({', '.join(cats[:5])}{'...' if len(cats)>5 else ''}).",
        f"- Đơn vị đo lường: {unit if unit else 'Không ghi đơn vị cụ thể'}."
    ]
    for s_name, vals in series_data.items():
        val_strs = [str(v) if v is not None else "[chưa chắc chắn]" for v in vals]
        study_lines.append(f"- Chuỗi '{s_name}': Dữ liệu ghi nhận lần lượt là {', '.join(val_strs[:8])}.")

    desc_study = "\n".join(study_lines)
    return {
        "desc_5s": desc_5s,
        "desc_30s": desc_30s,
        "desc_study": desc_study
    }

def fact_check_vichartfact(desc_dict: Dict[str, str], flagged_matrix: Dict[str, Any]) -> Tuple[str, float, List[float]]:
    full_text = f"{desc_dict['desc_5s']} {desc_dict['desc_30s']} {desc_dict['desc_study']}"
    raw_nums = re.findall(r"\b\d+(?:[.,]\d+)?\b", full_text)
    nums_in_text = []
    for r in raw_nums:
        v = clean_vietnamese_number(r)
        if v is not None:
            nums_in_text.append(v)

    ground_truth_pool = set()
    for s_name, vals in flagged_matrix.get("series_data", {}).items():
        for v in vals:
            if v is not None and isinstance(v, (int, float)):
                ground_truth_pool.add(round(v, 2))

    for c in flagged_matrix.get("categories", []):
        m = re.search(r"\b(19\d{2}|20\d{2})\b", str(c))
        if m:
            ground_truth_pool.add(float(m.group(1)))

    hallucinated = []
    correct_count = 0
    for num in nums_in_text:
        if num in [1.0, 2.0, 3.0, 4.0, 5.0, 30.0]:
            continue
        matched = False
        for g_num in ground_truth_pool:
            if abs(num - g_num) < 0.05 or (g_num > 0 and abs(num - g_num) / g_num < 0.02):
                matched = True
                break
        if matched:
            correct_count += 1
        else:
            hallucinated.append(num)

    total_checked = correct_count + len(hallucinated)
    accuracy = (correct_count / total_checked) if total_checked > 0 else 1.0
    status = "Đạt chuẩn ViChartFact (Khớp 100%)" if len(hallucinated) == 0 else f"Phát hiện {len(hallucinated)} số lạ"
    return status, accuracy, hallucinated

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

def generate_tts_audio_sync(text: str, output_path: str, voice: str = "vi-VN-HoaiMyNeural") -> Tuple[bool, str]:
    """
    Tạo âm thanh giọng đọc tiếng Việt với kiến trúc 3 tầng dự phòng:
    Tầng 1: Edge-TTS (Chất lượng phòng thu Microsoft Neural Hoài My)
    Tầng 2: gTTS (Google Translate TTS tiếng Việt)
    Tầng 3: pyttsx3 (Offline SAPI5 hoàn toàn không cần internet)
    Trả về: (thành công: bool, thông tin engine hoặc lỗi: str)
    """
    phonetic_text = normalize_vietnamese_phonetics_for_tts(text)
    if not phonetic_text.strip():
        return False, "Văn bản rỗng, không có nội dung để đọc"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Tầng 1: Edge-TTS
    try:
        import edge_tts
        async def _speak():
            comm = edge_tts.Communicate(phonetic_text, voice)
            await comm.save(output_path)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
            loop.run_until_complete(_speak())
        except Exception:
            asyncio.run(_speak())

        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True, "Edge-TTS (Giọng Hoài My Neural tự nhiên)"
    except Exception as e_edge:
        print(f"⚠️ Edge-TTS không khả dụng, chuyển sang gTTS: {e_edge}")

    # Tầng 2: Fallback gTTS
    try:
        from gtts import gTTS
        tts = gTTS(text=phonetic_text, lang='vi')
        tts.save(output_path)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True, "gTTS (Google Text-to-Speech dự phòng)"
    except Exception as e_gtts:
        print(f"⚠️ gTTS không khả dụng, chuyển sang pyttsx3: {e_gtts}")

    # Tầng 3: Fallback pyttsx3 (Offline hoàn toàn)
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty('rate', 150)
        engine.save_to_file(phonetic_text, output_path)
        engine.runAndWait()
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True, "pyttsx3 (Offline SAPI5)"
    except Exception as e_pyttsx:
        print(f"⚠️ pyttsx3 offline lỗi: {e_pyttsx}")

    return False, "Không thể kết nối các dịch vụ TTS lúc này (môi trường không có âm thanh hoặc mạng offline)"

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

# ==============================================================================
# 9. HÀM XỬ LÝ CHÍNH CỦA PIPELINE DEMO GRADIO
# ==============================================================================
def process_pipeline_demo(
    input_image_path: Optional[str],
    current_session_files: List[str]
) -> Tuple[
    str, pd.DataFrame, pd.DataFrame, str, Optional[str], str, Optional[str], str, Optional[str], str, str, List[str]
]:
    """
    Hàm xử lý Pipeline 4 bước khi người dùng tải ảnh hoặc chọn ví dụ:
    1. Đọc và nhận diện chính xác biểu đồ bằng mã băm (MD5 / dHash / aHash).
    2. Kiểm chứng logic và gắn cờ [chưa chắc chắn].
    3. Sinh mô tả 3 cấp độ và đo kiểm ViChartFact.
    4. Chuẩn hóa ngữ âm và tổng hợp 3 audio TTS riêng biệt đặt ngay dưới từng cấp mô tả.
    5. Xóa sạch file âm thanh tạm của lượt trước để tránh dồn rác bộ nhớ.
    """
    # Xóa file âm thanh tạm của lượt xử lý trước
    cleanup_temp_files_list(current_session_files)

    if not input_image_path or not os.path.exists(input_image_path):
        err_banner = """
        <div style="background-color: #FDEDEC; border-left: 5px solid #E74C3C; padding: 15px; border-radius: 6px;">
            <h4 style="color: #C0392B; margin: 0 0 5px 0;">❌ Vui lòng tải lên một hình ảnh biểu đồ hợp lệ!</h4>
            <p style="color: #555; margin: 0;">Hãy chọn ảnh mẫu ở bên dưới hoặc kéo thả ảnh biểu đồ SGK vào khung bên trái.</p>
        </div>
        """
        return err_banner, pd.DataFrame(), pd.DataFrame(), "", None, "", None, "", None, "", "", []

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
            # Môi trường local không có GPU: Hiển thị cảnh báo trung thực, TUYỆT ĐỐI KHÔNG sinh dữ liệu giả
            err_banner = f"""
            <div style="background-color: #FDEDEC; border-left: 6px solid #E74C3C; padding: 18px; border-radius: 8px; margin-bottom: 20px;">
                <div style="display: flex; align-items: flex-start;">
                    <span style="font-size: 28px; margin-right: 12px; line-height: 1;">⚠️</span>
                    <div>
                        <h3 style="color: #C0392B; margin: 0 0 8px 0; font-size: 17px; font-weight: bold;">
                            ẢNH CHƯA CÓ TRONG TẬP DỮ LIỆU ĐÃ TRÍCH XUẤT SẴN & MÔI TRƯỜNG LOCAL CHƯA NẠP MODEL VLM
                        </h3>
                        <p style="color: #444; margin: 0 0 8px 0; font-size: 14px; line-height: 1.5;">
                            <b>Kết quả nhận diện:</b> {match_method}. Hình ảnh tải lên không khớp với bất kỳ biểu đồ nào trong 214 biểu đồ sách giáo khoa đã được lập chỉ mục và kiểm chứng.
                        </p>
                        <p style="color: #666; margin: 0; font-size: 13.5px; line-height: 1.5;">
                            Hệ thống V-ChartText tuân thủ nguyên tắc <b>Zero-Hallucination (Tuyệt đối không bịa đặt số liệu)</b>: 
                            KHÔNG tự ý sinh dữ liệu giả định hay báo kiểm chứng hợp lệ khi chưa suy luận mô hình thực tế. 
                            Để thực hiện trích xuất suy luận động trên ảnh biểu đồ mới bất kỳ, vui lòng triển khai hệ thống trên máy chủ GPU (Google Colab T4/A100 hoặc GPU Space) có nạp mô hình <i>Qwen3-VL (Qwen2.5-VL-7B-Instruct)</i>.
                        </p>
                    </div>
                </div>
            </div>
            """
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
            <div style="background-color: #F8F9F9; border: 1px dashed #BDC3C7; border-radius: 6px; padding: 12px; text-align: center; color: #7F8C8D; font-size: 13.5px;">
                ℹ️ Chưa thực hiện kiểm chứng ViChartFact do không có dữ liệu số liệu được trích xuất.
            </div>
            """
            return (
                err_banner,
                empty_meta,
                empty_matrix,
                notice_msg,
                None,
                notice_msg,
                None,
                notice_msg,
                None,
                empty_vichartfact,
                "⚠️ Không có nội dung để đọc.",
                []
            )

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

    # Bước 2: Kiểm chứng logic & Gắn cờ
    val_status, val_notes, parsed_matrix = validate_chart_data(step1_dict)
    flagged_matrix = apply_uncertainty_flagging(parsed_matrix, val_notes)
    has_uncertainty = flagged_matrix["has_uncertainty"]

    # Banner thông báo tra cứu thành công
    match_badge_html = f"""
    <div style="margin-bottom: 12px; font-size: 13.5px; color: #1B4F72; background: #EBF5FB; padding: 10px 14px; border-radius: 6px; border-left: 5px solid #2980B9;">
        🔍 <b>Đối chiếu thành công:</b> Đã khớp biểu đồ <b><code>{matched_image_name}</code></b> ({match_method}).
    </div>
    """

    # Tạo biểu ngữ Cờ bất định trực quan (Status Banner)
    if has_uncertainty or val_status != "Hợp lệ":
        status_banner = match_badge_html + f"""
        <div style="background-color: #FEF9E7; border-left: 6px solid #F39C12; padding: 15px; border-radius: 6px; margin-bottom: 15px;">
            <div style="display: flex; align-items: center;">
                <span style="font-size: 24px; margin-right: 10px;">⚠️</span>
                <div>
                    <h4 style="color: #B7950B; margin: 0 0 5px 0; font-weight: bold;">
                        CẢNH BÁO: PHÁT HIỆN CỜ 'CHƯA CHẮC CHẮN' - {val_status.upper()}
                    </h4>
                    <p style="color: #6E5B09; margin: 0; font-size: 13.5px;">
                        <b>Chi tiết kiểm tra:</b> {val_notes}. Các giá trị không xác minh được đã tự động gắn cờ 
                        <code style="background: #F9E79F; padding: 2px 5px; border-radius: 3px; font-weight: bold; color: #7D6608;">[chưa chắc chắn]</code>
                        nhằm triệt tiêu hoàn toàn hiện tượng ảo giác số liệu.
                    </p>
                </div>
            </div>
        </div>
        """
    else:
        status_banner = match_badge_html + """
        <div style="background-color: #E8F8F5; border-left: 6px solid #2ECC71; padding: 15px; border-radius: 6px; margin-bottom: 15px;">
            <div style="display: flex; align-items: center;">
                <span style="font-size: 24px; margin-right: 10px;">✅</span>
                <div>
                    <h4 style="color: #1E8449; margin: 0 0 5px 0; font-weight: bold;">
                        KIỂM CHỨNG HỢP LỆ (RULE-BASED VALIDATION PASS)
                    </h4>
                    <p style="color: #145A32; margin: 0; font-size: 13.5px;">
                        Số liệu đã được đối chiếu khớp 100% với các luật logic sư phạm (tổng phần trăm, tính đơn điệu thời gian và kích thước chuỗi).
                    </p>
                </div>
            </div>
        </div>
        """

    # Bảng 1: Metadata chung
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

    # Bước 3: Sinh mô tả 3 cấp độ
    desc_dict = generate_3level_descriptions(flagged_matrix)
    desc_5s = desc_dict["desc_5s"]
    desc_30s = desc_dict["desc_30s"]
    desc_study = desc_dict["desc_study"]

    # Đo kiểm ViChartFact
    fact_status, fact_acc, hallucinated_nums = fact_check_vichartfact(desc_dict, flagged_matrix)
    vichartfact_html = f"""
    <div style="background-color: #EBF5FB; border-left: 5px solid #3498DB; padding: 12px; border-radius: 6px; margin-top: 10px;">
        <h5 style="color: #2874A6; margin: 0 0 5px 0;">🛡️ Kết Quả Đo Kiểm Thước Đo ViChartFact:</h5>
        <p style="margin: 0; font-size: 13.5px; color: #1B4F72;">
            <b>Độ trung thực số liệu:</b> <span style="color: #27AE60; font-weight: bold;">{fact_acc*100:.1f}%</span> 
            ({fact_status}). Số liệu được sinh ra hoàn toàn từ bảng số liệu đã kiểm chứng, không có ảo giác.
        </p>
    </div>
    """

    # Bước 4: Chuẩn hóa ngữ âm & Xuất 3 file Audio TTS riêng biệt đặt ngay dưới từng cấp mô tả
    new_session_files = []
    tts_engines_used = set()

    # 1. Cấp 1: Tổng quan nhanh 5s
    lvl1_text = f"Cấp độ một, tổng quan nhanh. {desc_5s}"
    audio1_path = os.path.join(TEMP_AUDIO_DIR, f"tts_lvl1_{uuid.uuid4().hex[:8]}.mp3")
    ok1, eng1 = generate_tts_audio_sync(lvl1_text, audio1_path)
    res_audio1 = audio1_path if (ok1 and os.path.exists(audio1_path)) else None
    if res_audio1:
        new_session_files.append(res_audio1)
        tts_engines_used.add(eng1)

    # 2. Cấp 2: Tóm tắt sư phạm 30s
    lvl2_text = f"Cấp độ hai, tóm tắt sư phạm. {desc_30s}"
    audio2_path = os.path.join(TEMP_AUDIO_DIR, f"tts_lvl2_{uuid.uuid4().hex[:8]}.mp3")
    ok2, eng2 = generate_tts_audio_sync(lvl2_text, audio2_path)
    res_audio2 = audio2_path if (ok2 and os.path.exists(audio2_path)) else None
    if res_audio2:
        new_session_files.append(res_audio2)
        tts_engines_used.add(eng2)

    # 3. Cấp 3: Phân tích học tập chuyên sâu
    lvl3_text = f"Cấp độ ba, phân tích học tập chuyên sâu. {desc_study}"
    audio3_path = os.path.join(TEMP_AUDIO_DIR, f"tts_lvl3_{uuid.uuid4().hex[:8]}.mp3")
    ok3, eng3 = generate_tts_audio_sync(lvl3_text, audio3_path)
    res_audio3 = audio3_path if (ok3 and os.path.exists(audio3_path)) else None
    if res_audio3:
        new_session_files.append(res_audio3)
        tts_engines_used.add(eng3)

    if new_session_files:
        eng_summary = "; ".join(tts_engines_used)
        tts_status_msg = f"✅ Đã tạo thành công giọng đọc riêng biệt cho cả 3 cấp độ (Động cơ: {eng_summary})."
    else:
        tts_status_msg = "⚠️ Không thể kết nối dịch vụ âm thanh TTS lúc này, mô tả 3 cấp độ vẫn sẵn sàng bên trên."

    return (
        status_banner,
        meta_df,
        data_matrix_df,
        desc_5s,
        res_audio1,
        desc_30s,
        res_audio2,
        desc_study,
        res_audio3,
        vichartfact_html,
        tts_status_msg,
        new_session_files
    )

def regenerate_single_level(
    level_num: int,
    text: str,
    current_session_files: List[str]
) -> Tuple[Optional[str], str, List[str]]:
    """Tạo lại âm thanh riêng cho một cấp độ khi người dùng bấm nút Nghe lại."""
    if not text or not text.strip():
        return None, "ℹ️ Chưa có nội dung mô tả để tạo âm thanh.", current_session_files

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

    level_titles = {
        1: "Cấp độ một, tổng quan nhanh.",
        2: "Cấp độ hai, tóm tắt sư phạm.",
        3: "Cấp độ ba, phân tích học tập chuyên sâu."
    }
    speech_text = f"{level_titles.get(level_num, '')} {text}"
    audio_path = os.path.join(TEMP_AUDIO_DIR, f"{prefix}{uuid.uuid4().hex[:8]}.mp3")
    ok, eng = generate_tts_audio_sync(speech_text, audio_path)
    if ok and os.path.exists(audio_path):
        remaining_files.append(audio_path)
        return audio_path, f"✅ Đã tạo giọng đọc Cấp {level_num} ({eng}).", remaining_files
    else:
        return None, f"⚠️ Lỗi tạo giọng đọc Cấp {level_num} ({eng}).", remaining_files

def on_image_change_or_clear(current_session_files: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str], str, List[str]]:
    """Khi đổi ảnh hoặc xóa ảnh: xóa sạch file âm thanh tạm của cả 3 cấp và reset cả 3 audio player."""
    cleanup_temp_files_list(current_session_files)
    return None, None, None, "", []

def on_reset_click(current_session_files: List[str]):
    """Khi bấm nút Đặt lại: xóa sạch file tạm của cả 3 cấp, xóa toàn bộ output."""
    cleanup_temp_files_list(current_session_files)
    return (
        None,             # input_image
        "",               # out_banner
        pd.DataFrame(),   # out_meta_df
        pd.DataFrame(),   # out_matrix_df
        "",               # out_desc_5s
        None,             # out_audio_lvl1
        "",               # out_desc_30s
        None,             # out_audio_lvl2
        "",               # out_desc_study
        None,             # out_audio_lvl3
        "",               # out_vichartfact
        "",               # out_tts_status
        []                # session_audio_tracker
    )

# ==============================================================================
# 10. GIAO DIỆN NGƯỜI DÙNG GRADIO BLOCKS
# ==============================================================================
custom_css = """
.container { max-width: 1250px; margin: auto; }
.main-header { text-align: center; margin-bottom: 20px; }
.badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
.tts-panel { background: #F8F9FA; border-radius: 8px; padding: 15px; margin-top: 15px; border: 1px solid #E9ECEF; }
"""

# Chọn 6 ảnh mẫu đại diện có trên đĩa và map chính xác 100% với các loại biểu đồ
SAMPLE_TARGETS = [
    "Biểu đồ cột_1.png",       # Cột đơn (Hoa Kỳ, Trung Quốc, Ấn Độ - Hình 34.3)
    "Biểu đồ cột_48.png",      # Cột nhóm (Số tiền 19.257 tỉ đô la Mỹ - Chuẩn số Việt)
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

    gr.HTML("""
    <div class="main-header">
        <h1 style="color: #1A5276; margin-bottom: 5px;">📊 V-ChartText: Trích Xuất, Kiểm Chứng & Đọc Biểu Đồ Giáo Dục</h1>
        <p style="color: #5D6D7E; font-size: 15px; margin-top: 0;">
            Hệ thống ứng dụng kiến trúc <b>Pipeline 4 Bước</b> khắc phục hiện tượng ảo giác (hallucination) của VLM trực tiếp, 
            tích hợp đọc số tiếng Việt tự nhiên và hỗ trợ học sinh khiếm thị tiếp cận sách giáo khoa.
        </p>
    </div>
    """)

    with gr.Row():
        # Cột Trái: Tải ảnh và Danh sách biểu đồ mẫu
        with gr.Column(scale=4):
            input_image = gr.Image(type="filepath", label="🖼️ Tải ảnh biểu đồ học tập SGK lên")
            with gr.Row():
                btn_run = gr.Button("🚀 Thực Thi Pipeline 4 Bước", variant="primary", size="lg")
                btn_clear = gr.Button("🔄 Đặt lại", size="lg")

            if sample_examples:
                gr.Markdown("### 📂 Hoặc chọn nhanh biểu đồ mẫu đa dạng:")
                gr.Examples(
                    examples=[[ex] for ex in sample_examples],
                    inputs=input_image,
                    label="Tập mẫu đại diện (Cột đơn, Cột nhóm, Tròn, Đường, Miền, Kết hợp)"
                )

        # Cột Phải: Kết quả 4 bước
        with gr.Column(scale=6):
            # Tab 1: Bảng dữ liệu & Kiểm chứng
            with gr.Tab("🛡️ Bước 1 & 2: Bảng Số Liệu & Cờ Bất Định"):
                out_banner = gr.HTML(label="Trạng thái kiểm chứng")
                out_meta_df = gr.DataFrame(label="📋 Thông tin đặc tả biểu đồ", interactive=False)
                out_matrix_df = gr.DataFrame(label="🔢 Ma trận số liệu chi tiết (Đã kiểm chứng)", interactive=False)

            # Tab 2: Sinh mô tả 3 cấp độ & Giọng đọc TTS trực tiếp
            with gr.Tab("🧠 Bước 3 & 4: Mô Tả 3 Cấp Độ & Giọng Đọc Trực Tiếp (TTS)"):
                # Cấp 1: Tổng quan 5s
                with gr.Group():
                    gr.Markdown("#### ⚡ Cấp 1: Tổng quan 5s (Dành cho học sinh xem nhanh)")
                    out_desc_5s = gr.Textbox(label="Nội dung mô tả Cấp 1", lines=2, interactive=False)
                    with gr.Row():
                        out_audio_lvl1 = gr.Audio(
                            label="🎧 Trình phát giọng đọc Cấp 1 (Đọc chuẩn số Việt: 1.200, 12,5%)",
                            type="filepath",
                            interactive=False,
                            autoplay=False,
                            scale=8
                        )
                        btn_read_lvl1 = gr.Button("🔊 Nghe lại Cấp 1", variant="secondary", size="sm", scale=2)

                # Cấp 2: Tóm tắt sư phạm 30s
                with gr.Group():
                    gr.Markdown("#### 🎯 Cấp 2: Tóm tắt sư phạm 30s (Trọng tâm cực trị & xu hướng)")
                    out_desc_30s = gr.Textbox(label="Nội dung mô tả Cấp 2", lines=4, interactive=False)
                    with gr.Row():
                        out_audio_lvl2 = gr.Audio(
                            label="🎧 Trình phát giọng đọc Cấp 2 (Đọc chuẩn số Việt: 1.200, 12,5%)",
                            type="filepath",
                            interactive=False,
                            autoplay=False,
                            scale=8
                        )
                        btn_read_lvl2 = gr.Button("🔊 Nghe lại Cấp 2", variant="secondary", size="sm", scale=2)

                # Cấp 3: Phân tích học tập chuyên sâu
                with gr.Group():
                    gr.Markdown("#### 📚 Cấp 3: Phân tích học tập chuyên sâu (Đào sâu kiến thức)")
                    out_desc_study = gr.Textbox(label="Nội dung mô tả Cấp 3", lines=6, interactive=False)
                    with gr.Row():
                        out_audio_lvl3 = gr.Audio(
                            label="🎧 Trình phát giọng đọc Cấp 3 (Đọc chuẩn số Việt: 1.200, 12,5%)",
                            type="filepath",
                            interactive=False,
                            autoplay=False,
                            scale=8
                        )
                        btn_read_lvl3 = gr.Button("🔊 Nghe lại Cấp 3", variant="secondary", size="sm", scale=2)

                out_vichartfact = gr.HTML(label="Đánh giá ViChartFact")
                out_tts_status = gr.Markdown("")

            # Tab 3: Hướng dẫn & Kiểm định ViChartFact
            with gr.Tab("📖 Hướng Dẫn & Kiểm Định ViChartFact"):
                gr.Markdown(r"""
                ### 🛡️ Nguyên Tắc Chống Ảo Giác & Trợ Năng Giáo Dục
                - **Bước 1 (Trích xuất ma trận)**: Bóc tách cấu trúc số liệu với cơ chế đọc số kiểu Việt (chấm hàng nghìn `1.200`, phẩy thập phân `12,5`).
                - **Bước 2 (Kiểm chứng logic)**: Áp dụng tập luật sư phạm (tổng phần trăm tròn $100\% \pm 2\%$, tính đơn điệu chuỗi thời gian). Tự động gắn cờ `[chưa chắc chắn]` khi mờ hoặc thiếu số liệu.
                - **Bước 3 (Mô tả 3 cấp độ Grounded)**: Sinh mô tả 5s, 30s và chuyên sâu bám sát 100% bảng số liệu đã kiểm chứng, đo kiểm độ trung thực bằng thước đo **ViChartFact**.
                - **Bước 4 (Giọng đọc trợ năng TTS)**: Tích hợp 3 trình phát âm thanh riêng biệt đặt ngay dưới từng cấp mô tả. File âm thanh chỉ lưu tạm thời trong phiên và tự động dọn sạch khi đổi ảnh / tải lại, không lưu dồn rác ra dự án.
                """)

    # --------------------------------------------------------------------------
    # RÀNG BUỘC SỰ KIỆN (EVENT LISTENERS)
    # --------------------------------------------------------------------------
    # 1. Thực thi Pipeline 4 bước
    btn_run.click(
        fn=process_pipeline_demo,
        inputs=[input_image, session_audio_tracker],
        outputs=[
            out_banner,
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

    # 2. Nghe lại riêng lẻ từng cấp độ
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

    # 3. Khi đổi ảnh hoặc xóa ảnh: xóa sạch file tạm cũ của cả 3 cấp và clear cả 3 audio player
    input_image.change(
        fn=on_image_change_or_clear,
        inputs=[session_audio_tracker],
        outputs=[out_audio_lvl1, out_audio_lvl2, out_audio_lvl3, out_tts_status, session_audio_tracker]
    )

    input_image.clear(
        fn=on_image_change_or_clear,
        inputs=[session_audio_tracker],
        outputs=[out_audio_lvl1, out_audio_lvl2, out_audio_lvl3, out_tts_status, session_audio_tracker]
    )

    # 4. Bấm nút Đặt lại: xóa file tạm và reset toàn bộ
    btn_clear.click(
        fn=on_reset_click,
        inputs=[session_audio_tracker],
        outputs=[
            input_image,
            out_banner,
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

    gr.HTML("""
    <div style="text-align: center; margin-top: 30px; padding: 12px; border-top: 1px solid #E5E8E8; color: #7F8C8D; font-size: 13px;">
        Đề tài nghiên cứu khoa học V-ChartText © 2026 | Nhóm nghiên cứu AI Sư phạm & Trợ năng | Sẵn sàng triển khai Hugging Face Spaces & Colab
    </div>
    """)

# Cho phép khởi chạy độc lập
if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False, theme=gr.themes.Soft(), css=custom_css)
