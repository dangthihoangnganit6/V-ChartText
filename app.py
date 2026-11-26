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
def fmt_vn(val: Any) -> str:
    """Định dạng số kiểu Việt Nam dùng dấu phẩy thập phân, tránh lỗi làm tròn float lẻ."""
    if val is None:
        return "[chưa chắc chắn]"
    if isinstance(val, (int, float)):
        f = round(float(val), 2)
        if f.is_integer():
            return str(int(f))
        s = f"{f:.2f}".rstrip('0').rstrip('.')
        return s.replace(".", ",")
    return str(val)

def clean_chart_title_for_speech(title: str, unit: str = "", series_names: Optional[List[str]] = None) -> str:
    """Làm sạch tiêu đề hoặc tự động tổng hợp chủ đề tự nhiên nếu biểu đồ không có tên rõ ràng."""
    t = str(title).strip()
    t = re.sub(r'^(?:Hình|Biểu đồ|Bảng)\s+[\d\.]+\s*[:\-–]?\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^(?:Biểu đồ|Bảng)\s+(?:thể hiện|về)?\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^(?:thể hiện|về)\s+', '', t, flags=re.IGNORECASE)
    meaningless = ["", "thiếu tên biểu đồ", "không có tên", "biểu đồ không có tên", "chưa rõ", "none", "nan", "không có tiêu đề"]
    if t.lower() in meaningless:
        s_list = [s.strip() for s in (series_names or []) if s and s.strip().lower() not in ["giá trị", "số liệu", "tỷ trọng"]]
        u_clean = unit.strip()
        if u_clean and s_list:
            if u_clean in ["%", "phần trăm"]:
                return f"cơ cấu {', '.join(s_list)}"
            elif len(s_list) == 2:
                return f"diễn biến {u_clean.lower()} của {s_list[0]} và {s_list[1]}"
            elif len(s_list) > 2:
                return f"diễn biến {u_clean.lower()} giữa các nhóm {', '.join(s_list)}"
            else:
                return f"{u_clean.lower()} ({s_list[0]})"
        elif s_list:
            if len(s_list) == 2:
                return f"số liệu giữa {s_list[0]} và {s_list[1]}"
            return f"giá trị của {', '.join(s_list)}"
        elif u_clean:
            return f"các số liệu đo lường theo {u_clean.lower()}"
        return "các chỉ số khảo sát"
    return t.strip()

def generate_3level_descriptions(flagged_matrix: Dict[str, Any]) -> Dict[str, str]:
    """
    Sinh mô tả 3 cấp độ văn phong tự nhiên, mạch lạc, bám sát dữ liệu đã kiểm chứng:
    - Cấp 1 (Tổng quan 5s): Ngắn gọn, nêu loại biểu đồ, chủ đề/đơn vị, phạm vi và xu hướng chính.
    - Cấp 2 (Tóm tắt xu hướng 30s): Đoạn văn xuôi mạch lạc nêu xu hướng nổi bật, cực trị và biến động đầu–cuối.
    - Cấp 3 (Phân tích chi tiết): Trình bày đầy đủ số liệu từng chuỗi/danh mục và nhận xét biến động/so sánh sát số liệu.
    """
    raw_title = flagged_matrix["chart_title"]
    c_type = flagged_matrix["chart_type"]
    unit = flagged_matrix["unit"].strip()
    cats = flagged_matrix["categories"]
    series_data = flagged_matrix["series_data"]
    series_names = list(series_data.keys())
    has_un = flagged_matrix["has_uncertainty"]

    clean_title = clean_chart_title_for_speech(raw_title, unit=unit, series_names=series_names)

    if c_type == "column":
        if len(series_data) >= 2:
            c_type_label = "Biểu đồ cột ghép"
        else:
            c_type_label = "Biểu đồ cột"
    else:
        c_type_label = {
            "line": "Biểu đồ đường",
            "pie": "Biểu đồ tròn",
            "area": "Biểu đồ miền",
            "combo": "Biểu đồ kết hợp"
        }.get(c_type, "Biểu đồ")

    is_time_series = len(cats) >= 2 and all(re.search(r"\b(19\d{2}|20\d{2})\b", str(c)) for c in cats)

    is_long_metric_unit = (len(unit.split()) >= 3 and unit.lower() in clean_title.lower())
    unit_suffix = "" if is_long_metric_unit else ("%" if unit == "%" else (f" {unit}" if unit else ""))
    if unit and unit.lower() not in clean_title.lower():
        unit_paren = f" (đơn vị: {unit.lower() if len(unit) > 4 else unit})"
    else:
        unit_paren = ""

    all_valid_points = []
    points_by_series = {}
    for s_name, vals in series_data.items():
        points_by_series[s_name] = []
        for i, v in enumerate(vals):
            c_label = cats[i] if i < len(cats) else f"Mốc {i+1}"
            if isinstance(v, (int, float)):
                pt = (float(v), s_name, c_label, i)
                all_valid_points.append(pt)
                points_by_series[s_name].append(pt)

    # --------------------------------------------------------------------------
    # 1. CẤP 1: TỔNG QUAN 5 GIÂY
    # --------------------------------------------------------------------------
    if is_time_series:
        scope_phrase = f"từ năm {cats[0]} đến năm {cats[-1]}"
    else:
        scope_phrase = f"qua {len(cats)} nhóm danh mục"

    trend_sentence = ""
    if is_time_series:
        if len(series_data) >= 2:
            s_means = {s: (sum(p[0] for p in pts) / len(pts)) for s, pts in points_by_series.items() if pts}
            sorted_s_names = sorted(s_means.keys(), key=lambda x: s_means[x], reverse=True)
            top_s = sorted_s_names[0]
            other_s = sorted_s_names[1] if len(sorted_s_names) > 1 else ""

            all_inc = all(
                len(pts) >= 2 and all(pts[k][0] <= pts[k+1][0] for k in range(len(pts)-1))
                for pts in points_by_series.values() if pts
            )
            all_dec = all(
                len(pts) >= 2 and all(pts[k][0] >= pts[k+1][0] for k in range(len(pts)-1))
                for pts in points_by_series.values() if pts
            )
            top_pts = points_by_series.get(top_s, [])
            other_pts = points_by_series.get(other_s, [])
            always_higher = (
                len(top_pts) == len(other_pts) and len(top_pts) > 0 and
                all(top_pts[k][0] > other_pts[k][0] for k in range(len(top_pts)))
            )

            if all_inc:
                if always_higher and len(series_data) == 2:
                    trend_sentence = f"Qua {len(cats)} năm, cả hai nhóm đều có xu hướng tăng nhẹ và ổn định, trong đó {top_s} luôn cao hơn {other_s}."
                else:
                    trend_sentence = f"Qua {len(cats)} năm, các nhóm đều có xu hướng tăng, nổi bật là {top_s} duy trì mức cao nhất."
            elif all_dec:
                trend_sentence = f"Qua {len(cats)} năm, các nhóm đều ghi nhận xu hướng giảm, trong đó {top_s} vẫn giữ mức cao nhất."
            else:
                if always_higher and len(series_data) == 2:
                    trend_sentence = f"Qua {len(cats)} năm, diễn biến các nhóm có sự biến động, trong đó {top_s} luôn cao hơn {other_s}."
                else:
                    trend_sentence = f"Qua {len(cats)} năm, các chuỗi có diễn biến biến động khác nhau, nổi bật nhất là {top_s}."
        else:
            main_s = series_names[0]
            pts = points_by_series.get(main_s, [])
            if len(pts) >= 2:
                v_start, v_end = pts[0][0], pts[-1][0]
                is_inc = all(pts[k][0] <= pts[k+1][0] for k in range(len(pts)-1))
                is_dec = all(pts[k][0] >= pts[k+1][0] for k in range(len(pts)-1))
                if is_inc:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị ghi nhận xu hướng tăng liên tục."
                elif is_dec:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị ghi nhận xu hướng giảm liên tục."
                elif v_end > v_start:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị có xu hướng tăng chung dù có nhịp dao động."
                elif v_end < v_start:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị có xu hướng giảm về cuối giai đoạn."
                else:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị duy trì ở mức tương đối ổn định."
    elif c_type == "pie":
        if all_valid_points:
            top_pt = max(all_valid_points, key=lambda x: x[0])
            min_pt = min(all_valid_points, key=lambda x: x[0])
            trend_sentence = f"Cơ cấu cho thấy {top_pt[2]} chiếm tỷ trọng cao nhất ({fmt_vn(top_pt[0])}{unit_suffix}), trong khi {min_pt[2]} chiếm tỷ trọng thấp nhất."
        else:
            trend_sentence = "Biểu đồ phản ánh cơ cấu tỷ trọng giữa các nhóm thành phần."
    else:
        if all_valid_points:
            top_pt = max(all_valid_points, key=lambda x: x[0])
            min_pt = min(all_valid_points, key=lambda x: x[0])
            trend_sentence = f"Số liệu cho thấy sự chênh lệch rõ nét giữa các nhóm, dẫn đầu là {top_pt[2]} và thấp nhất là {min_pt[2]}."
        else:
            trend_sentence = "Biểu đồ thể hiện sự so sánh giá trị giữa các danh mục khảo sát."

    desc_5s_parts = [
        f"{c_type_label} thể hiện {clean_title} {scope_phrase}{unit_paren}.",
        trend_sentence
    ]
    if has_un:
        desc_5s_parts.append("Lưu ý: Một số giá trị trên biểu đồ chưa xác minh được chắc chắn do ảnh mờ hoặc thiếu thông tin.")
    desc_5s = " ".join(p for p in desc_5s_parts if p)

    # --------------------------------------------------------------------------
    # 2. CẤP 2: TÓM TẮT XU HƯỚNG 30 GIÂY (ĐOẠN VĂN XUÔI MẠCH LẠC)
    # --------------------------------------------------------------------------
    desc_30s_parts = []
    if is_time_series:
        if len(series_data) >= 2:
            all_inc = all(
                len(pts) >= 2 and all(pts[k][0] <= pts[k+1][0] for k in range(len(pts)-1))
                for pts in points_by_series.values() if pts
            )
            if all_inc:
                desc_30s_parts.append(f"Từ năm {cats[0]} đến năm {cats[-1]}, {clean_title} đều tăng dần qua các mốc khảo sát.")
            else:
                desc_30s_parts.append(f"Từ năm {cats[0]} đến năm {cats[-1]}, {clean_title} ghi nhận sự biến chuyển qua {len(cats)} mốc khảo sát.")
        else:
            desc_30s_parts.append(f"Từ năm {cats[0]} đến năm {cats[-1]}, {clean_title} thay đổi qua {len(cats)} mốc thời gian.")
    elif c_type == "pie":
        desc_30s_parts.append(f"Xét về cơ cấu qua {len(cats)} nhóm thành phần, {clean_title} phân bổ không đồng đều giữa các đối tượng.")
    else:
        desc_30s_parts.append(f"So sánh qua {len(cats)} danh mục khảo sát, {clean_title} thể hiện sự chênh lệch rõ rệt về quy mô.")

    if all_valid_points:
        max_pt = max(all_valid_points, key=lambda x: x[0])
        min_pt = min(all_valid_points, key=lambda x: x[0])
        max_val, max_s, max_cat, _ = max_pt
        min_val, min_s, min_cat, _ = min_pt
        diff_val = round(max_val - min_val, 2)

        if len(series_data) >= 2:
            if is_time_series:
                desc_30s_parts.append(
                    f"Nhóm {max_s} duy trì mức cao hơn và đạt đỉnh ở năm {max_cat} với {fmt_vn(max_val)}{unit_suffix}, trong khi nhóm {min_s} thấp nhất ở năm {min_cat} với {fmt_vn(min_val)}{unit_suffix}."
                )
            else:
                desc_30s_parts.append(
                    f"Mức cao nhất thuộc về {max_cat} ở nhóm {max_s} đạt {fmt_vn(max_val)}{unit_suffix}, trong khi mức thấp nhất thuộc về {min_cat} ở nhóm {min_s} với {fmt_vn(min_val)}{unit_suffix}."
                )
        else:
            if is_time_series:
                desc_30s_parts.append(
                    f"Giá trị đạt đỉnh vào năm {max_cat} với {fmt_vn(max_val)}{unit_suffix} và thấp nhất vào năm {min_cat} với {fmt_vn(min_val)}{unit_suffix}."
                )
            else:
                desc_30s_parts.append(
                    f"Nhóm {max_cat} dẫn đầu với {fmt_vn(max_val)}{unit_suffix}, trong khi nhóm thấp nhất là {min_cat} đạt {fmt_vn(min_val)}{unit_suffix}."
                )

        if diff_val > 0:
            desc_30s_parts.append(
                f"Khoảng cách chênh lệch lớn nhất giữa giá trị cao nhất và thấp nhất trên biểu đồ là {fmt_vn(diff_val)}{unit_suffix}."
            )

        if is_time_series:
            main_s = series_names[0]
            pts = points_by_series.get(main_s, [])
            if len(pts) >= 2:
                v_first = pts[0][0]
                v_last = pts[-1][0]
                net_change = round(v_last - v_first, 2)
                if net_change > 0:
                    desc_30s_parts.append(
                        f"Tính từ năm {pts[0][2]} đến năm {pts[-1][2]}, chuỗi {main_s} tăng thêm {fmt_vn(net_change)}{unit_suffix} so với mốc ban đầu."
                    )
                elif net_change < 0:
                    desc_30s_parts.append(
                        f"Tính từ năm {pts[0][2]} đến năm {pts[-1][2]}, chuỗi {main_s} giảm {fmt_vn(abs(net_change))}{unit_suffix} so với mốc ban đầu."
                    )

    un_locations = []
    for s_name, vals in series_data.items():
        for i, v in enumerate(vals):
            if v is None:
                c_lbl = cats[i] if i < len(cats) else f"Mốc {i+1}"
                un_locations.append(f"chuỗi {s_name} tại {c_lbl}")

    if un_locations:
        desc_30s_parts.append(
            f"Lưu ý có {len(un_locations)} vị trí chưa xác minh được số liệu ({', '.join(un_locations[:3])})."
        )

    desc_30s = " ".join(desc_30s_parts)

    # --------------------------------------------------------------------------
    # 3. CẤP 3: PHÂN TÍCH CHI TIẾT (SÁT SỐ LIỆU, KHÔNG NHÃN NGOẶC VUÔNG, KHÔNG LẶP)
    # --------------------------------------------------------------------------
    desc_study_parts = []
    if is_time_series:
        desc_study_parts.append(f"Số liệu theo từng nhóm qua các năm ({cats[0]}–{cats[-1]}):")
        for s_name, vals in series_data.items():
            val_items = []
            for i, v in enumerate(vals):
                c_lbl = cats[i] if i < len(cats) else f"Mốc {i+1}"
                val_items.append(f"năm {c_lbl} đạt {fmt_vn(v)}")
            desc_study_parts.append(f"{s_name}: {'; '.join(val_items)}.")
    else:
        desc_study_parts.append(f"Số liệu chi tiết theo từng danh mục{unit_paren}:")
        for s_name, vals in series_data.items():
            val_items = []
            for i, v in enumerate(vals):
                c_lbl = cats[i] if i < len(cats) else f"Mốc {i+1}"
                val_items.append(f"{c_lbl} đạt {fmt_vn(v)}{unit_suffix}")
            if len(series_data) == 1:
                desc_study_parts.append(f"{'; '.join(val_items)}.")
            else:
                desc_study_parts.append(f"{s_name}: {'; '.join(val_items)}.")

    desc_study_parts.append("Nhận xét biến động & so sánh:")
    if is_time_series:
        for s_name, pts in points_by_series.items():
            if len(pts) >= 2:
                flat_spans = []
                max_step_change = 0.0
                max_step_span = ""
                step_direction = ""
                for k in range(len(pts) - 1):
                    v1, _, c1, _ = pts[k]
                    v2, _, c2, _ = pts[k+1]
                    diff = round(v2 - v1, 2)
                    if diff == 0:
                        flat_spans.append(f"giai đoạn {c1}–{c2} giữ nguyên mức {fmt_vn(v1)}")
                    elif abs(diff) > abs(max_step_change):
                        max_step_change = diff
                        max_step_span = f"từ năm {c1} đến năm {c2}"
                        step_direction = "tăng" if diff > 0 else "giảm"

                if max_step_span and abs(max_step_change) > 0:
                    flat_note = f" (riêng {', '.join(flat_spans)})" if flat_spans else ""
                    desc_study_parts.append(
                        f"Chuỗi {s_name} có bước biến động lớn nhất {max_step_span}, {step_direction} {fmt_vn(abs(max_step_change))}{unit_suffix}{flat_note}."
                    )
                elif flat_spans:
                    desc_study_parts.append(f"Chuỗi {s_name} duy trì ổn định: {', '.join(flat_spans)}.")

        if len(series_data) >= 2:
            s_means = {s: (sum(p[0] for p in pts) / len(pts)) for s, pts in points_by_series.items() if pts}
            sorted_s = sorted(s_means.keys(), key=lambda x: s_means[x], reverse=True)
            s_hi, s_lo = sorted_s[0], sorted_s[1]
            pts_hi = points_by_series.get(s_hi, [])
            pts_lo = points_by_series.get(s_lo, [])
            if len(pts_hi) >= 2 and len(pts_lo) >= 2:
                gap_start = round(abs(pts_hi[0][0] - pts_lo[0][0]), 2)
                gap_end = round(abs(pts_hi[-1][0] - pts_lo[-1][0]), 2)
                always_higher = len(pts_hi) == len(pts_lo) and all(pts_hi[k][0] > pts_lo[k][0] for k in range(len(pts_hi)))
                if always_higher:
                    desc_study_parts.append(
                        f"Trong toàn giai đoạn, mức của {s_hi} luôn cao hơn {s_lo} (chênh lệch từ {fmt_vn(gap_start)}{unit_suffix} vào năm {pts_hi[0][2]} đến {fmt_vn(gap_end)}{unit_suffix} vào năm {pts_hi[-1][2]})."
                    )
                else:
                    desc_study_parts.append(
                        f"So sánh hai chuỗi ở hai đầu giai đoạn, mức chênh lệch giữa {s_hi} và {s_lo} là {fmt_vn(gap_start)}{unit_suffix} vào năm {pts_hi[0][2]} và {fmt_vn(gap_end)}{unit_suffix} vào năm {pts_hi[-1][2]}."
                    )
    elif c_type == "pie":
        total_sum = round(sum(p[0] for p in all_valid_points), 2) if all_valid_points else 100.0
        sorted_pts = sorted(all_valid_points, key=lambda x: x[0], reverse=True)
        if sorted_pts:
            top_part = sorted_pts[0]
            low_part = sorted_pts[-1]
            gap_pie = round(top_part[0] - low_part[0], 2)
            desc_study_parts.append(
                f"Tổng tỷ trọng các thành phần đạt {fmt_vn(total_sum)}{unit_suffix}. Nhóm {top_part[2]} chiếm tỷ trọng lớn nhất ({fmt_vn(top_part[0])}{unit_suffix}), cao hơn nhóm thấp nhất là {low_part[2]} ({fmt_vn(low_part[0])}{unit_suffix}) là {fmt_vn(gap_pie)}{unit_suffix}."
            )
    else:
        sorted_pts = sorted(all_valid_points, key=lambda x: x[0], reverse=True)
        if len(sorted_pts) >= 2:
            rank_strings = [f"{pt[2]} ({fmt_vn(pt[0])}{unit_suffix})" for pt in sorted_pts]
            desc_study_parts.append(f"Thứ tự giá trị từ cao xuống thấp: {', '.join(rank_strings)}.")
            top_pt = sorted_pts[0]
            second_pt = sorted_pts[1]
            gap = round(top_pt[0] - second_pt[0], 2)
            desc_study_parts.append(
                f"Nhóm dẫn đầu là {top_pt[2]} vượt lên trên vị trí tiếp theo ({second_pt[2]}) khoảng cách {fmt_vn(gap)}{unit_suffix}."
            )

    if un_locations:
        desc_study_parts.append(
            f"Ghi chú dữ liệu: Các vị trí {', '.join(un_locations)} chưa xác minh được số liệu cụ thể."
        )

    desc_study = "\n\n".join(desc_study_parts)
    return {
        "desc_5s": desc_5s,
        "desc_30s": desc_30s,
        "desc_study": desc_study
    }

def fact_check_vichartfact(desc_dict: Dict[str, str], flagged_matrix: Dict[str, Any]) -> Dict[str, Any]:
    """
    Thước đo ViChartFact: Đo lường độ trung thực số liệu giữa nội dung mô tả 3 cấp độ
    với bảng số liệu đã kiểm chứng, nhãn trục, cấu trúc siêu dữ liệu và các phép toán phái sinh hợp lệ.
    Công thức: Accuracy = (N_khớp / N_tổng đối chiếu) * 100%.
    Dung sai cho phép: <= 5% sai số tương đối hoặc <= 0.05 sai số tuyệt đối.
    Hỗ trợ chuẩn hóa số kiểu Việt (1.200 -> 1200, 12,5 -> 12.5).
    """
    title = flagged_matrix.get("chart_title", "")
    unit = flagged_matrix.get("unit", "")
    cats = flagged_matrix.get("categories", [])
    series_data = flagged_matrix.get("series_data", {})

    # 1. Xây dựng tập đối chuẩn (Ground-truth pool)
    # 1.1 Tập giá trị ô dữ liệu (Data Cells)
    cell_pool = []
    all_numeric_vals = []
    for s_name, vals in series_data.items():
        for i, v in enumerate(vals):
            if v is not None and isinstance(v, (int, float)):
                c_label = cats[i] if i < len(cats) else f"Cột {i+1}"
                cell_pool.append({
                    "val": float(v),
                    "series": str(s_name),
                    "category": str(c_label)
                })
                all_numeric_vals.append(float(v))

    # 1.2 Tập nhãn trục / năm / danh mục (Categories & Years)
    cat_pool = []
    for c in cats:
        nums = re.findall(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", str(c))
        for n_str in nums:
            n_val = clean_vietnamese_number(n_str)
            if n_val is not None:
                cat_pool.append({
                    "val": n_val,
                    "raw": n_str,
                    "cat_name": str(c)
                })

    # 1.3 Tập số liệu cấu trúc / siêu dữ liệu (Structure & Metadata)
    meta_pool = [
        {"val": float(len(cats)), "desc": f"Số lượng mốc danh mục ({len(cats)} mốc)"},
        {"val": float(len(series_data)), "desc": f"Số lượng chuỗi dữ liệu ({len(series_data)} chuỗi)"}
    ]
    if title:
        for t_n in re.findall(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", str(title)):
            t_val = clean_vietnamese_number(t_n)
            if t_val is not None:
                meta_pool.append({"val": t_val, "desc": f"Số trong tiêu đề biểu đồ ('{title}')"})
    if unit:
        for u_n in re.findall(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", str(unit)):
            u_val = clean_vietnamese_number(u_n)
            if u_val is not None:
                meta_pool.append({"val": u_val, "desc": f"Số trong đơn vị tính ('{unit}')"})

    # 1.4 Tập số liệu tính toán phái sinh từ bảng gốc (Derived / Calculated Pool)
    derived_pool = []
    if all_numeric_vals:
        max_v = max(all_numeric_vals)
        min_v = min(all_numeric_vals)
        derived_pool.append({"val": round(max_v - min_v, 2), "desc": f"Chênh lệch cực đại - cực tiểu ({max_v} - {min_v})"})
        derived_pool.append({"val": round(sum(all_numeric_vals), 2), "desc": "Tổng giá trị các ô dữ liệu"})
        for i in range(len(all_numeric_vals)):
            for j in range(len(all_numeric_vals)):
                if i != j:
                    diff = round(abs(all_numeric_vals[i] - all_numeric_vals[j]), 2)
                    if diff > 0:
                        v_hi = max(all_numeric_vals[i], all_numeric_vals[j])
                        v_lo = min(all_numeric_vals[i], all_numeric_vals[j])
                        derived_pool.append({"val": diff, "desc": f"Chênh lệch giữa 2 ô dữ liệu ({v_hi} - {v_lo})"})
                    if all_numeric_vals[j] > 0.001:
                        ratio1 = round(all_numeric_vals[i] / all_numeric_vals[j], 1)
                        ratio2 = round(all_numeric_vals[i] / all_numeric_vals[j], 2)
                        derived_pool.append({"val": ratio1, "desc": f"Tỷ lệ gấp giữa 2 ô ({all_numeric_vals[i]} / {all_numeric_vals[j]} = {ratio1})"})
                        derived_pool.append({"val": ratio2, "desc": f"Tỷ lệ gấp giữa 2 ô ({all_numeric_vals[i]} / {all_numeric_vals[j]} = {ratio2})"})

    # 2. Quét và đối chiếu số theo từng cấp mô tả
    levels_config = [
        ("Cấp 1: Tổng quan 5s", desc_dict.get("desc_5s", "")),
        ("Cấp 2: Tóm tắt sư phạm 30s", desc_dict.get("desc_30s", "")),
        ("Cấp 3: Phân tích học tập chuyên sâu", desc_dict.get("desc_study", ""))
    ]

    matched_items = []
    unmatched_items = []

    for level_name, level_text in levels_config:
        if not level_text:
            continue
        matches = list(re.finditer(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", level_text))
        for m in matches:
            raw_str = m.group(1)
            start_pos, end_pos = m.span()
            clean_val = clean_vietnamese_number(raw_str)
            if clean_val is None:
                continue

            c_start = max(0, level_text.rfind('\n', 0, start_pos) + 1)
            dot_before = level_text.rfind('. ', 0, start_pos)
            if dot_before != -1 and dot_before + 2 > c_start:
                c_start = dot_before + 2

            c_end = level_text.find('\n', end_pos)
            if c_end == -1:
                c_end = len(level_text)
            dot_after = level_text.find('. ', end_pos)
            if dot_after != -1 and dot_after + 1 < c_end:
                c_end = dot_after + 1

            snippet = level_text[c_start:c_end].strip()
            if len(snippet) > 130:
                rel_s = max(0, start_pos - c_start - 30)
                rel_e = min(len(snippet), (end_pos - c_start) + 30)
                snippet = ("..." if rel_s > 0 else "") + snippet[rel_s:rel_e] + ("..." if rel_e < len(snippet) else "")

            matched = False
            match_type = ""
            gt_ref = ""

            # Tầng 1: Khớp ô số liệu bảng gốc (dung sai sai số tương đối <= 5% hoặc sai số tuyệt đối <= 0.05)
            for c_item in cell_pool:
                g = c_item["val"]
                abs_diff = abs(clean_val - g)
                rel_diff = abs_diff / abs(g) if abs(g) > 1e-6 else abs_diff
                if abs_diff <= 0.05 or rel_diff <= 0.05:
                    matched = True
                    match_type = "Ô số liệu bảng gốc (Data Cell)"
                    gt_ref = f"Khớp chuỗi '{c_item['series']}', mốc '{c_item['category']}': {g} (sai số {rel_diff*100:.2f}%)"
                    break

            # Tầng 2: Khớp nhãn mốc thời gian / trục hoành
            if not matched:
                for cat_item in cat_pool:
                    if abs(clean_val - cat_item["val"]) < 0.01:
                        matched = True
                        match_type = "Nhãn mốc thời gian / Trục hoành"
                        gt_ref = f"Khớp danh mục '{cat_item['cat_name']}'"
                        break

            # Tầng 3: Khớp số cấu trúc / siêu dữ liệu biểu đồ
            if not matched:
                for m_item in meta_pool:
                    if abs(clean_val - m_item["val"]) < 0.01:
                        matched = True
                        match_type = "Số cấu trúc / Siêu dữ liệu biểu đồ"
                        gt_ref = f"Khớp {m_item['desc']}"
                        break

            # Tầng 4: Khớp số tính toán phái sinh hợp lệ từ bảng gốc
            if not matched:
                for d_item in derived_pool:
                    if abs(clean_val - d_item["val"]) < 0.05:
                        matched = True
                        match_type = "Số tính toán phái sinh hợp lệ từ bảng gốc"
                        gt_ref = f"Khớp phép tính {d_item['desc']}"
                        break

            item_data = {
                "level": level_name,
                "raw_str": raw_str,
                "clean_val": clean_val,
                "sentence": snippet,
                "match_type": match_type,
                "gt_ref": gt_ref
            }

            if matched:
                matched_items.append(item_data)
            else:
                closest_cell = None
                min_rel_err = float("inf")
                for c_item in cell_pool:
                    g = c_item["val"]
                    err = abs(clean_val - g) / (abs(g) if abs(g) > 1e-6 else 1.0)
                    if err < min_rel_err:
                        min_rel_err = err
                        closest_cell = c_item

                if closest_cell and min_rel_err <= 0.35:
                    classification = "Lệch giá trị / Sai khác đơn vị (> 5% so với bảng)"
                    gt_explanation = f"Gần với ô '{closest_cell['series']}' - {closest_cell['category']} ({closest_cell['val']}) nhưng sai số là {min_rel_err*100:.1f}% (> 5%)."
                else:
                    classification = "Số ngoài bảng (Chưa đối chuẩn / Nghi vấn ảo giác)"
                    gt_explanation = "Không tìm thấy trong bảng số liệu, trục tọa độ hay siêu dữ liệu biểu đồ."

                item_data["classification"] = classification
                item_data["gt_ref"] = gt_explanation
                unmatched_items.append(item_data)

    total_checked = len(matched_items) + len(unmatched_items)
    accuracy = (len(matched_items) / total_checked * 100.0) if total_checked > 0 else 100.0
    status_title = "Đạt chuẩn ViChartFact (Khớp 100% - Zero-Hallucination)" if len(unmatched_items) == 0 else f"Phát hiện {len(unmatched_items)} số lạ / chưa đối chuẩn"

    return {
        "accuracy": accuracy,
        "total_checked": total_checked,
        "matched_count": len(matched_items),
        "unmatched_count": len(unmatched_items),
        "status_title": status_title,
        "cell_pool_count": len(cell_pool),
        "cat_pool_count": len(cat_pool),
        "meta_pool_count": len(meta_pool),
        "derived_pool_count": len(derived_pool),
        "matched_items": matched_items,
        "unmatched_items": unmatched_items
    }

def render_vichartfact_html(fact_res: Dict[str, Any]) -> str:
    """Render giao diện HTML chi tiết, minh bạch cho thước đo ViChartFact bám sát thiết kế UI stitch_v_charttext_ui_redesign_3."""
    acc = fact_res["accuracy"]
    tot = fact_res["total_checked"]
    m_cnt = fact_res["matched_count"]
    u_cnt = fact_res["unmatched_count"]
    cell_cnt = fact_res["cell_pool_count"]
    cat_cnt = fact_res["cat_pool_count"]
    unmatched_pct = max(0.0, 100.0 - acc)

    if u_cnt == 0:
        icon_box_bg = "#DEF7EC"
        icon_box_color = "#03543F"
        badge_bg = "#0E9F6E"
        badge_color = "#FFFFFF"
        badge_border = "#0E9F6E"
        badge_icon = "✓"
        badge_text = "100% Zero-Hallucination"
        conclusion_html = f"""
        <div style="background-color: #DEF7EC; border: 1px solid #BCF0DA; border-radius: 8px; padding: 14px 18px; display: flex; align-items: flex-start; gap: 12px; margin-top: 14px;">
            <span style="font-size: 20px; color: #03543F; line-height: 1.2; flex-shrink: 0;">✓</span>
            <p style="margin: 0; font-size: 13.5px; color: #03543F; line-height: 1.55;">
                <strong style="font-weight: 700;">Kết luận đối kiểm:</strong> Toàn bộ <b>{m_cnt}/{tot}</b> giá trị số xuất hiện trong cả 3 cấp mô tả đều khớp hoàn toàn với bảng số liệu đã kiểm chứng (sai số tối đa 5%) và nhãn trục biểu đồ. Không phát hiện bất kỳ số lạ hay hiện tượng ảo giác nào.
            </p>
        </div>
        """
        unmatched_table_html = ""
    else:
        icon_box_bg = "#FDE8E8"
        icon_box_color = "#9B1C1C"
        badge_bg = "#E02424"
        badge_color = "#FFFFFF"
        badge_border = "#E02424"
        badge_icon = "⚠️"
        badge_text = f"Cảnh báo: Phát hiện {u_cnt} số lạ"
        conclusion_html = f"""
        <div style="background-color: #FEF7E0; border: 1px solid #FAD2CF; border-left: 5px solid #C5221F; border-radius: 8px; padding: 14px 18px; display: flex; align-items: flex-start; gap: 12px; margin-top: 14px;">
            <span style="font-size: 20px; color: #C5221F; line-height: 1.2; flex-shrink: 0;">⚠️</span>
            <p style="margin: 0; font-size: 13.5px; color: #8A4B00; line-height: 1.55;">
                <strong style="font-weight: 700; color: #C5221F;">Kết luận đối kiểm:</strong> Phát hiện <b>{u_cnt} giá trị số</b> trong mô tả chưa đối chuẩn được với bảng số liệu gốc (Độ trung thực: <b>{acc:.1f}%</b>). <b>Tuyệt đối không xác nhận Zero-Hallucination</b> cho đến khi các số lạ này được rà soát và đối chuẩn. Vui lòng xem bảng chi tiết bên dưới.
            </p>
        </div>
        """
        rows_html = []
        for u in fact_res["unmatched_items"]:
            raw_esc = html.escape(u["raw_str"])
            sent_esc = html.escape(u["sentence"])
            highlighted_sent = sent_esc.replace(raw_esc, f"<mark style='background-color: #FAD2CF; color: #C5221F; font-weight: bold; padding: 1px 4px; border-radius: 3px;'>{raw_esc}</mark>")
            lvl_display = html.escape(u['level'])
            if "Cấp 1" in lvl_display: lvl_display = "Cấp 1 (5s)"
            elif "Cấp 2" in lvl_display: lvl_display = "Cấp 2 (30s)"
            elif "Cấp 3" in lvl_display: lvl_display = "Cấp 3 (Chi tiết)"

            rows_html.append(f"""
            <tr style="border-bottom: 1px solid #FDE8E8; font-size: 12.5px;">
                <td style="padding: 9px 12px; font-weight: 700; color: #1A40C2; border-right: 1px solid #FDE8E8; white-space: nowrap;">{lvl_display}</td>
                <td style="padding: 9px 12px; border-right: 1px solid #FDE8E8; white-space: nowrap;"><code style="background: #FDE8E8; color: #9B1C1C; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-family: monospace;">{raw_esc}</code><br><span style="font-size: 11px; color: #6B7280;">(giá trị: {u['clean_val']})</span></td>
                <td style="padding: 9px 12px; border-right: 1px solid #FDE8E8; line-height: 1.45; color: #374151;">{highlighted_sent}</td>
                <td style="padding: 9px 12px; border-right: 1px solid #FDE8E8; font-size: 12px; color: #4B5563; line-height: 1.45;">{html.escape(u['gt_ref'])}</td>
                <td style="padding: 9px 12px; font-weight: 700; color: #C5221F; font-size: 12px;">{html.escape(u['classification'])}</td>
            </tr>
            """)
        unmatched_table_html = f"""
        <div style="margin-top: 14px; border: 1px solid #F8B4B4; border-radius: 8px; overflow: hidden; background: #FFFFFF;">
            <div style="padding: 10px 14px; background: #FDE8E8; border-bottom: 1px solid #F8B4B4; font-weight: 700; color: #9B1C1C; font-size: 13.5px; display: flex; align-items: center; gap: 8px;">
                <span>🔍</span>
                <span>Danh sách chi tiết các giá trị số lạ / chưa đối chuẩn ({u_cnt} mục):</span>
            </div>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; background: #FFFFFF; text-align: left;">
                    <thead>
                        <tr style="background-color: #FDF2F2; color: #9B1C1C; border-bottom: 1px solid #F8B4B4; font-size: 12px;">
                            <th style="padding: 8px 12px; border-right: 1px solid #F8B4B4; white-space: nowrap;">Cấp mô tả</th>
                            <th style="padding: 8px 12px; border-right: 1px solid #F8B4B4; white-space: nowrap;">Số bắt được</th>
                            <th style="padding: 8px 12px; border-right: 1px solid #F8B4B4;">Ngữ cảnh trong câu</th>
                            <th style="padding: 8px 12px; border-right: 1px solid #F8B4B4;">Kết quả đối chiếu bảng gốc</th>
                            <th style="padding: 8px 12px; white-space: nowrap;">Nguyên nhân &amp; Phân loại</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(rows_html)}
                    </tbody>
                </table>
            </div>
        </div>
        """

    matched_rows_html = []
    for m in fact_res["matched_items"]:
        lvl_display = html.escape(m['level'])
        if "Cấp 1" in lvl_display: lvl_display = "Cấp 1 (5s)"
        elif "Cấp 2" in lvl_display: lvl_display = "Cấp 2 (30s)"
        elif "Cấp 3" in lvl_display: lvl_display = "Cấp 3 (Chi tiết)"

        mtype_display = html.escape(m['match_type'])
        if "Ô số liệu" in mtype_display: mtype_display = "Ô số liệu bảng gốc"
        elif "Nhãn mốc" in mtype_display: mtype_display = "Mốc thời gian / Trục hoành"
        elif "Số cấu trúc" in mtype_display: mtype_display = "Cấu trúc biểu đồ"
        elif "Số tính toán" in mtype_display: mtype_display = "Phép tính suy luận"

        matched_rows_html.append(f"""
        <tr style="border-bottom: 1px solid #F1F5F9; font-size: 12.5px;">
            <td style="padding: 8px 14px; font-weight: 600; color: #1E293B; white-space: nowrap;">{lvl_display}</td>
            <td style="padding: 8px 14px; white-space: nowrap;">
                <code style="background: #DEF7EC; color: #03543F; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{html.escape(m['raw_str'])}</code>
            </td>
            <td style="padding: 8px 14px; color: #1A40C2; font-weight: 600; white-space: nowrap;">{mtype_display}</td>
            <td style="padding: 8px 14px; color: #475569; line-height: 1.45;">{html.escape(m['gt_ref'])}</td>
        </tr>
        """)

    matched_details_html = f"""
    <details open class="v-fact-details" style="border: 1px solid #E2E6F0; border-radius: 8px; background: #FFFFFF; overflow: hidden; margin-top: 14px;">
        <summary style="padding: 12px 16px; background-color: #F8F9FC; border-bottom: 1px solid #E2E6F0; display: flex; align-items: center; justify-content: space-between; cursor: pointer; user-select: none; font-weight: 700; font-size: 13.5px; color: #1E293B;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="color: #1A40C2; font-size: 16px;">📋</span>
                <span>Bảng đối chiếu chi tiết ({m_cnt} giá trị khớp hợp lệ)</span>
            </div>
            <span class="v-expand-icon">▼</span>
        </summary>
        <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 12.5px; text-align: left;">
                <thead style="background: #F8F9FC; border-bottom: 1px solid #E2E6F0; color: #475569;">
                    <tr>
                        <th style="padding: 10px 14px; font-weight: 700; white-space: nowrap;">Cấp mô tả</th>
                        <th style="padding: 10px 14px; font-weight: 700; white-space: nowrap;">Giá trị / Số bắt được</th>
                        <th style="padding: 10px 14px; font-weight: 700; white-space: nowrap;">Loại đối chiếu</th>
                        <th style="padding: 10px 14px; font-weight: 700;">Kết quả kiểm tra</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(matched_rows_html)}
                </tbody>
            </table>
        </div>
    </details>
    """

    rules_formula_html = """
    <details class="v-fact-details" style="border: 1px solid #E2E6F0; border-radius: 8px; background: #FFFFFF; overflow: hidden; margin-top: 14px;">
        <summary style="padding: 12px 16px; background-color: #F8F9FC; border-bottom: 1px solid #E2E6F0; display: flex; align-items: center; justify-content: space-between; cursor: pointer; user-select: none; font-weight: 700; font-size: 13.5px; color: #1E293B;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="color: #4F46E5; font-size: 16px;">📖</span>
                <span>Quy chuẩn &amp; Công thức kiểm định ViChartFact</span>
            </div>
            <span class="v-expand-icon">▼</span>
        </summary>
        <div style="padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; font-size: 13.5px; color: #475569; line-height: 1.6; background: #FFFFFF;">
            <div>
                <h4 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 700; color: #0F172A;">
                    Cách tính độ trung thực
                </h4>
                <p style="margin: 0 0 6px 0;">
                    Độ trung thực (Factuality) được tính bằng số lượng giá trị khớp bảng gốc chia cho tổng số giá trị xuất hiện trong mô tả để đối chiếu, sau đó nhân với 100%:
                </p>
                <div style="display: inline-block; padding: 6px 12px; background: #F1F5F9; border-radius: 6px; font-weight: 700; color: #1E293B; font-size: 13px;">
                    Độ trung thực (Factuality) = (Số giá trị khớp / Tổng số giá trị đối chiếu) × 100%
                </div>
            </div>

            <div style="border-top: 1px solid #F1F5F9; padding-top: 12px;">
                <h4 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 700; color: #0F172A;">
                    Ngưỡng sai số và chuẩn hóa số tiếng Việt
                </h4>
                <p style="margin: 0;">
                    Hệ thống chấp nhận sai số tương đối tối đa 5% hoặc sai số tuyệt đối nhỏ hơn 0,05. Khi đọc số kiểu Việt, hệ thống tự động chuẩn hóa dấu chấm hàng nghìn và dấu phẩy thập phân (ví dụ chuyển từ 1.200 thành 1200, từ 12,5% thành 12.5%), đồng thời kiểm tra tổng phần trăm với sai số cho phép ±2%.
                </p>
            </div>

            <div style="border-top: 1px solid #F1F5F9; padding-top: 12px;">
                <h4 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 700; color: #0F172A;">
                    Tập dữ liệu gốc đối chiếu và nguyên tắc chống ảo giác
                </h4>
                <p style="margin: 0;">
                    Dữ liệu gốc bao gồm toàn bộ ô số liệu từ các chuỗi dữ liệu, nhãn danh mục trục hoành, thông số cấu trúc và các phép tính chênh lệch, biên độ, tỷ lệ suy luận hợp lệ. Hệ thống tuyệt đối không công nhận đạt chuẩn Zero-Hallucination nếu vẫn còn bất kỳ số lạ nào chưa khớp với dữ liệu gốc.
                </p>
            </div>
        </div>
    </details>
    """

    out_html = f"""
    <div style="background-color: #FFFFFF; border: 1px solid #E2E6F0; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; flex-direction: column; gap: 4px;">
        <!-- 1. Phần tổng quan đầu mục -->
        <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; margin-bottom: 16px;">
            <div style="display: flex; align-items: flex-start; gap: 12px; min-width: 0;">
                <div style="width: 40px; height: 40px; border-radius: 8px; background-color: {icon_box_bg}; color: {icon_box_color}; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-size: 20px;">
                    🛡️
                </div>
                <div>
                    <h3 style="margin: 0; font-size: 18px; font-weight: 800; color: #1E293B; letter-spacing: -0.3px;">
                        3. Kiểm Định ViChartFact
                    </h3>
                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #64748B;">
                        Đánh giá độ trung thực số liệu của mô tả biểu đồ so với dữ liệu đã kiểm chứng.
                    </p>
                </div>
            </div>
            <span style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 9999px; background-color: {badge_bg}; color: {badge_color}; border: 1px solid {badge_border}; font-size: 12.5px; font-weight: 700; white-space: nowrap;">
                <span>{badge_icon}</span>
                <span>{badge_text}</span>
            </span>
        </div>

        <!-- Hàng 3 thẻ chỉ số chính nằm ngang (Theo layout chuẩn code.html) -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 6px;">
            <div style="border-radius: 8px; background: #F8F9FC; border: 1px solid #E2E6F0; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px;">
                <span style="font-size: 12px; font-weight: 600; color: #64748B; text-transform: uppercase;">Số liệu khớp bảng gốc</span>
                <span style="font-size: 26px; font-weight: 800; color: #1A40C2; font-variant-numeric: tabular-nums;">{m_cnt} / {tot}</span>
                <span style="font-size: 12px; color: #64748B;">{cell_cnt} ô số liệu, {cat_cnt} nhãn trục</span>
            </div>

            <div style="border-radius: 8px; background: #F8F9FC; border: 1px solid #E2E6F0; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px;">
                <span style="font-size: 12px; font-weight: 600; color: #64748B; text-transform: uppercase;">Độ trung thực Factuality</span>
                <span style="font-size: 26px; font-weight: 800; color: {'#0E9F6E' if acc >= 90 else '#D97706'}; font-variant-numeric: tabular-nums;">{acc:.1f}%</span>
                <span style="font-size: 12px; color: #64748B;">Sai số cho phép tối đa 5%</span>
            </div>

            <div style="border-radius: 8px; background: #F8F9FC; border: 1px solid #E2E6F0; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px;">
                <span style="font-size: 12px; font-weight: 600; color: #64748B; text-transform: uppercase;">Tỷ lệ sai lệch / số lạ</span>
                <span style="font-size: 26px; font-weight: 800; color: {'#0E9F6E' if u_cnt == 0 else '#E02424'}; font-variant-numeric: tabular-nums;">{unmatched_pct:.1f}%</span>
                <span style="font-size: 12px; color: #64748B;">{u_cnt} số lạ bị gắn cờ</span>
            </div>
        </div>

        <!-- Khung tóm tắt kết luận ngắn gọn -->
        {conclusion_html}
        {unmatched_table_html}

        <!-- 2. Bảng đối chiếu chi tiết (thu gọn / mở rộng) -->
        {matched_details_html}

        <!-- 3. Quy chuẩn & Công thức kiểm định ViChartFact (1 mục thu gọn/mở rộng duy nhất ở cuối) -->
        {rules_formula_html}
    </div>
    """
    return out_html

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
def process_pipeline_demo(
    input_image_path: Optional[str],
    current_session_files: List[str]
) -> Tuple[
    pd.DataFrame, pd.DataFrame, str, Optional[str], str, Optional[str], str, Optional[str], str, str, List[str]
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
        err_toast = make_toast_html("Lỗi Tải Ảnh", "Vui lòng chọn hoặc tải lên một hình ảnh biểu đồ SGK hợp lệ.", "error")
        return pd.DataFrame(), pd.DataFrame(), "", None, "", None, "", None, "", err_toast, []

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
            # Môi trường local không có GPU: Hiển thị cảnh báo trung thực qua Toast & bảng thuộc tính, TUYỆT ĐỐI KHÔNG sinh dữ liệu giả
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
            return (
                empty_meta,
                empty_matrix,
                notice_msg,
                None,
                notice_msg,
                None,
                notice_msg,
                None,
                empty_vichartfact,
                warn_toast,
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

    # Bước 3: Sinh mô tả 3 cấp độ
    desc_dict = generate_3level_descriptions(flagged_matrix)
    desc_5s = desc_dict["desc_5s"]
    desc_30s = desc_dict["desc_30s"]
    desc_study = desc_dict["desc_study"]

    # Đo kiểm ViChartFact minh bạch & chi tiết
    fact_report = fact_check_vichartfact(desc_dict, flagged_matrix)
    vichartfact_html = render_vichartfact_html(fact_report)

    # Bước 4: Chuẩn hóa ngữ âm & Xuất 3 file Audio TTS riêng biệt với giọng đọc Hoài My
    new_session_files = []
    tts_engines_used = set()

    # 1. Cấp 1: Tổng quan nhanh 5s
    lvl1_text = desc_5s
    audio1_path = os.path.join(TEMP_AUDIO_DIR, f"tts_lvl1_{uuid.uuid4().hex[:8]}.mp3")
    ok1, eng1 = generate_tts_audio_sync(lvl1_text, audio1_path, voice_id=HOAI_MY_VOICE_ID)
    res_audio1 = audio1_path if (ok1 and os.path.exists(audio1_path)) else None
    if res_audio1:
        new_session_files.append(res_audio1)
        tts_engines_used.add(eng1)

    # 2. Cấp 2: Tóm tắt sư phạm 30s
    lvl2_text = desc_30s
    audio2_path = os.path.join(TEMP_AUDIO_DIR, f"tts_lvl2_{uuid.uuid4().hex[:8]}.mp3")
    ok2, eng2 = generate_tts_audio_sync(lvl2_text, audio2_path, voice_id=HOAI_MY_VOICE_ID)
    res_audio2 = audio2_path if (ok2 and os.path.exists(audio2_path)) else None
    if res_audio2:
        new_session_files.append(res_audio2)
        tts_engines_used.add(eng2)

    # 3. Cấp 3: Phân tích học tập chuyên sâu
    lvl3_text = desc_study
    audio3_path = os.path.join(TEMP_AUDIO_DIR, f"tts_lvl3_{uuid.uuid4().hex[:8]}.mp3")
    ok3, eng3 = generate_tts_audio_sync(lvl3_text, audio3_path, voice_id=HOAI_MY_VOICE_ID)
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

    return (
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

def on_image_uploaded(current_session_files: List[str]):
    """Khi người dùng tải ảnh mới từ máy tính lên: xóa sạch output cũ ngay lập tức."""
    cleanup_temp_files_list(current_session_files)
    return (
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

def on_reset_click(current_session_files: List[str]):
    """Khi bấm nút Đặt lại: xóa sạch file tạm của cả 3 cấp và xóa toàn bộ dữ liệu trên giao diện."""
    cleanup_temp_files_list(current_session_files)
    return (
        None,             # input_image
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
        Đề tài nghiên cứu khoa học V-ChartText © 2026 | Nhóm nghiên cứu AI Sư phạm &amp; Trợ năng | Sẵn sàng triển khai Hugging Face Spaces &amp; Colab
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
