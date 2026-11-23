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
def clean_chart_title_for_speech(title: str) -> str:
    """Làm sạch tiêu đề, loại bỏ tiền tố thừa như 'Biểu đồ', 'Hình X.Y', 'Bảng X.Y' để diễn đạt tự nhiên và tránh lặp từ."""
    t = str(title).strip()
    t = re.sub(r'^(?:Hình|Biểu đồ|Bảng)\s+[\d\.]+\s*[:\-–]?\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^(?:Biểu đồ|Bảng)\s+(?:thể hiện|về)?\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^(?:thể hiện|về)\s+', '', t, flags=re.IGNORECASE)
    if not t or t.lower() in ["thiếu tên biểu đồ", "chưa rõ", "none", "nan"]:
        return "các chỉ số đối tượng khảo sát"
    return t.strip()

ORDINAL_VN = ["nhất", "nhì", "ba", "tư", "năm", "sáu", "bảy", "tám", "chín", "mười"]

def generate_3level_descriptions(flagged_matrix: Dict[str, Any]) -> Dict[str, str]:
    """
    Sinh mô tả 3 cấp độ chuẩn sư phạm, không cắt ngắn cứng nhắc, không lặp từ/lặp cấu trúc,
    bám sát ma trận số liệu đã kiểm chứng và tuyệt đối không suy diễn nguyên nhân kinh tế - xã hội ngoài dữ liệu.
    - Cấp 1 (Tổng quan 5s): Loại biểu đồ, chủ đề, đơn vị tính, phạm vi và xu hướng biến thiên tổng quát.
    - Cấp 2 (Nghe 30s): Số liệu định lượng trọng tâm (đỉnh, đáy, biên độ chênh lệch, đầu kỳ - cuối kỳ, cờ chưa chắc chắn).
    - Cấp 3 (Diễn giải chuyên sâu): Toàn văn ma trận số liệu, phân tích tương quan/thứ bậc học tập có căn cứ trực tiếp từ số liệu.
    """
    raw_title = flagged_matrix["chart_title"]
    c_type = flagged_matrix["chart_type"]
    unit = flagged_matrix["unit"]
    cats = flagged_matrix["categories"]
    series_data = flagged_matrix["series_data"]
    has_un = flagged_matrix["has_uncertainty"]

    clean_title = clean_chart_title_for_speech(raw_title)

    c_type_vn = {
        "column": "cột",
        "line": "đường",
        "pie": "tròn",
        "area": "miền",
        "combo": "kết hợp"
    }.get(c_type, "cột")

    is_time_series = len(cats) >= 2 and all(re.search(r"\b(19\d{2}|20\d{2})\b", str(c)) for c in cats)
    if is_time_series:
        scope_text = f"diễn biến trong giai đoạn từ năm {cats[0]} đến năm {cats[-1]} (bao gồm {len(cats)} mốc thời gian)"
    else:
        scope_text = f"sự phân bố qua {len(cats)} danh mục khảo sát ({', '.join(cats)})"

    unit_phrase = f", với đơn vị tính là {unit}" if unit else ""

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
    # 1. CẤP 1: TỔNG QUAN 5S - TÓM TẮT NHANH BỨC TRANH TOÀN CẢNH
    # --------------------------------------------------------------------------
    trend_summary = ""
    if is_time_series:
        main_s = list(series_data.keys())[0]
        pts = points_by_series.get(main_s, [])
        if len(pts) >= 2:
            start_v = pts[0][0]
            end_v = pts[-1][0]
            is_increasing = all(pts[k][0] <= pts[k+1][0] for k in range(len(pts)-1))
            is_decreasing = all(pts[k][0] >= pts[k+1][0] for k in range(len(pts)-1))
            if is_increasing:
                trend_summary = "ghi nhận xu hướng tăng trưởng liên tục qua các mốc khảo sát"
            elif is_decreasing:
                trend_summary = "ghi nhận xu hướng giảm liên tục qua các mốc thời gian"
            elif end_v > start_v:
                trend_summary = "nhìn chung có xu hướng tăng về tổng thể dù có sự dao động giữa các thời kỳ"
            elif end_v < start_v:
                trend_summary = "nhìn chung có xu hướng giảm về mặt tổng thể qua các năm"
            else:
                trend_summary = "duy trì ở mức tương đối ổn định giữa đầu kỳ và cuối kỳ"
        else:
            trend_summary = "thể hiện sự phân bổ của các chuỗi dữ liệu qua các năm"
    elif c_type == "pie":
        if all_valid_points:
            top_pt = max(all_valid_points, key=lambda x: x[0])
            trend_summary = f"phản ánh cơ cấu tỷ trọng thành phần, trong đó nhóm '{top_pt[2]}' chiếm tỷ lệ chi phối cao nhất"
        else:
            trend_summary = "phản ánh cơ cấu tỷ trọng giữa các nhóm thành phần"
    else:
        if all_valid_points:
            top_pt = max(all_valid_points, key=lambda x: x[0])
            trend_summary = f"cho thấy sự phân hóa rõ rệt giữa các đối tượng, dẫn đầu là '{top_pt[2]}'"
        else:
            trend_summary = "thể hiện sự so sánh giá trị giữa các danh mục khảo sát"

    desc_5s_parts = [
        f"Biểu đồ dạng {c_type_vn} trực quan hóa dữ liệu về {clean_title}{unit_phrase}, {scope_text}.",
        f"Bức tranh tổng quan {trend_summary}."
    ]
    if has_un:
        desc_5s_parts.append("Lưu ý: Biểu đồ có một số giá trị số liệu chưa xác minh được chắc chắn do ảnh gốc bị mờ hoặc mâu thuẫn.")
    desc_5s = " ".join(desc_5s_parts)

    # --------------------------------------------------------------------------
    # 2. CẤP 2: TÓM TẮT SƯ PHẠM 30S - ĐỐI CHIẾU SỐ LIỆU ĐỊNH LƯỢNG TRỌNG TÂM
    # --------------------------------------------------------------------------
    desc_30s_parts = []
    desc_30s_parts.append(f"Về phương diện định lượng, dữ liệu của {len(series_data)} chuỗi trên {len(cats)} mốc khảo sát được ghi nhận chi tiết:")

    if all_valid_points:
        max_pt = max(all_valid_points, key=lambda x: x[0])
        min_pt = min(all_valid_points, key=lambda x: x[0])
        max_val, max_s, max_cat, _ = max_pt
        min_val, min_s, min_cat, _ = min_pt
        diff_val = round(max_val - min_val, 2)

        desc_30s_parts.append(
            f"- Mức đỉnh cao nhất ghi nhận ở {max_cat} (thuộc chuỗi '{max_s}') đạt {max_val} {unit}."
        )
        desc_30s_parts.append(
            f"- Mức đáy thấp nhất thuộc về {min_cat} (chuỗi '{min_s}') với {min_val} {unit}."
        )
        if diff_val > 0:
            desc_30s_parts.append(
                f"- Biên độ chênh lệch tuyệt đối giữa giá trị cao nhất và thấp nhất là {diff_val} {unit}."
            )

        if is_time_series:
            main_s = list(series_data.keys())[0]
            pts = points_by_series.get(main_s, [])
            if len(pts) >= 2:
                v_first = pts[0][0]
                v_last = pts[-1][0]
                net_change = round(v_last - v_first, 2)
                if net_change > 0:
                    desc_30s_parts.append(
                        f"- So sánh mốc xuất phát năm {pts[0][2]} ({v_first} {unit}) và mốc kết thúc năm {pts[-1][2]} ({v_last} {unit}), chuỗi '{main_s}' đã tăng thêm {net_change} {unit}."
                    )
                elif net_change < 0:
                    desc_30s_parts.append(
                        f"- So sánh giữa năm {pts[0][2]} ({v_first} {unit}) và năm {pts[-1][2]} ({v_last} {unit}), chuỗi '{main_s}' đã giảm đi {abs(net_change)} {unit}."
                    )

    un_locations = []
    for s_name, vals in series_data.items():
        for i, v in enumerate(vals):
            if v is None:
                c_lbl = cats[i] if i < len(cats) else f"Mốc {i+1}"
                un_locations.append(f"chuỗi '{s_name}' tại mốc '{c_lbl}'")

    if un_locations:
        desc_30s_parts.append(
            f"- Cảnh báo cờ dữ liệu: Có {len(un_locations)} vị trí chưa xác minh được giá trị cụ thể ({', '.join(un_locations[:3])}), đã tự động gắn cờ [chưa chắc chắn] để tránh sai lệch khi làm bài tập."
        )

    desc_30s = "\n".join(desc_30s_parts)

    # --------------------------------------------------------------------------
    # 3. CẤP 3: PHÂN TÍCH HỌC TẬP CHUYÊN SÂU (GROUNDED - TUYỆT ĐỐI KHÔNG SUY DIỄN NGOÀI DỮ LIỆU)
    # --------------------------------------------------------------------------
    desc_study_parts = []
    desc_study_parts.append(f"Phân tích học tập chuyên sâu biểu đồ: '{raw_title}'.")
    desc_study_parts.append(f"[Cấu trúc số liệu]: Biểu đồ được xây dựng từ {len(series_data)} chuỗi dữ liệu đo lường theo đơn vị {unit if unit else 'chuẩn hóa'}, phân bổ trên {len(cats)} mốc danh mục ({', '.join(cats)}).")

    desc_study_parts.append("[Bảng kê khai đầy đủ số liệu đối chiếu đã kiểm chứng]:")
    for s_name, vals in series_data.items():
        val_items = []
        for i, v in enumerate(vals):
            c_lbl = cats[i] if i < len(cats) else f"Mốc {i+1}"
            v_str = str(v) if v is not None else "[chưa chắc chắn]"
            val_items.append(f"{c_lbl}: {v_str}")
        desc_study_parts.append(f"• Chuỗi '{s_name}': {'; '.join(val_items)}.")

    desc_study_parts.append("[Nhận xét học tập có căn cứ trực tiếp từ số liệu kiểm chứng]:")
    if is_time_series:
        for s_name, pts in points_by_series.items():
            if len(pts) >= 2:
                max_step_change = 0.0
                max_step_span = ""
                step_direction = ""
                for k in range(len(pts) - 1):
                    v1, _, c1, _ = pts[k]
                    v2, _, c2, _ = pts[k+1]
                    diff = v2 - v1
                    if abs(diff) > abs(max_step_change):
                        max_step_change = diff
                        max_step_span = f"từ năm {c1} đến năm {c2}"
                        step_direction = "tăng" if diff > 0 else "giảm"
                if max_step_span and abs(max_step_change) > 0:
                    desc_study_parts.append(
                        f"• Đối với chuỗi '{s_name}': Giai đoạn có biến động biên độ lớn nhất diễn ra {max_step_span}, với mức {step_direction} {round(abs(max_step_change), 2)} {unit}."
                    )
    elif c_type == "pie":
        total_sum = round(sum(p[0] for p in all_valid_points), 2) if all_valid_points else 100.0
        sorted_pts = sorted(all_valid_points, key=lambda x: x[0], reverse=True)
        if sorted_pts:
            top_part = sorted_pts[0]
            desc_study_parts.append(
                f"• Phân bổ cơ cấu: Tổng tỷ trọng các thành phần đạt {total_sum}%. Nhóm '{top_part[2]}' chiếm tỷ trọng áp đảo lớn nhất ({top_part[0]} {unit}), gấp {round(top_part[0]/sorted_pts[-1][0], 1) if sorted_pts[-1][0]>0 else 'nhiều'} lần so với nhóm thấp nhất là '{sorted_pts[-1][2]}' ({sorted_pts[-1][0]} {unit})."
            )
    else:
        sorted_pts = sorted(all_valid_points, key=lambda x: x[0], reverse=True)
        if len(sorted_pts) >= 2:
            rank_strings = []
            for idx, pt in enumerate(sorted_pts):
                ord_name = ORDINAL_VN[idx] if idx < len(ORDINAL_VN) else f"{idx+1}"
                rank_strings.append(f"Hạng {ord_name}: {pt[2]} ({pt[0]} {unit})")
            desc_study_parts.append(
                f"• Thứ bậc xếp hạng từ cao xuống thấp: {'; '.join(rank_strings)}."
            )
            top_pt = sorted_pts[0]
            second_pt = sorted_pts[1]
            gap = round(top_pt[0] - second_pt[0], 2)
            desc_study_parts.append(
                f"• Tương quan dẫn đầu: Đối tượng '{top_pt[2]}' vượt hơn vị trí tiếp sau là '{second_pt[2]}' khoảng cách {gap} {unit}."
            )

    if len(series_data) >= 2:
        s_sums = {s_name: sum(p[0] for p in pts) for s_name, pts in points_by_series.items()}
        sorted_s = sorted(s_sums.items(), key=lambda x: x[1], reverse=True)
        desc_study_parts.append(
            f"• So sánh liên chuỗi: Chuỗi '{sorted_s[0][0]}' có quy mô tích lũy lớn hơn so với chuỗi '{sorted_s[1][0]}'."
        )

    desc_study_parts.append(
        "[Nguyên tắc sư phạm]: Toàn bộ phân tích trên được tính toán và đối chiếu độc lập từ ma trận số liệu đã kiểm chứng, tuyệt đối không suy diễn các nguyên nhân kinh tế - xã hội bên ngoài phạm vi dữ liệu cung cấp."
    )

    desc_study = "\n".join(desc_study_parts)
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
    """Render giao diện HTML chi tiết, minh bạch cho thước đo ViChartFact."""
    acc = fact_res["accuracy"]
    tot = fact_res["total_checked"]
    m_cnt = fact_res["matched_count"]
    u_cnt = fact_res["unmatched_count"]
    cell_cnt = fact_res["cell_pool_count"]
    cat_cnt = fact_res["cat_pool_count"]

    if u_cnt == 0:
        badge_bg = "#E8F8F5"
        badge_color = "#1E8449"
        badge_border = "#A9DFBF"
        badge_text = "✅ 100% ZERO-HALLUCINATION"
        conclusion_html = f"""
        <div style="background-color: #E8F8F5; border-left: 5px solid #27AE60; padding: 12px 14px; border-radius: 4px; margin-bottom: 12px; font-size: 13.5px; color: #1E8449;">
            <b>✅ Kết luận đối kiểm:</b> <b>Đạt chuẩn ViChartFact (Khớp 100% - Zero-Hallucination)</b>. Toàn bộ <b>{m_cnt}/{tot}</b> giá trị số xuất hiện trong cả 3 cấp mô tả đều khớp hoàn toàn với bảng số liệu đã kiểm chứng (sai số ≤ 5%), nhãn trục hoặc thông số cấu trúc biểu đồ. Không phát hiện bất kỳ số lạ hay hiện tượng ảo giác nào.
        </div>
        """
        unmatched_table_html = """
        <div style="background-color: #F4F6F6; border: 1px dashed #BDC3C7; border-radius: 5px; padding: 10px; text-align: center; color: #27AE60; font-size: 13px; font-weight: 500;">
            ✓ Không phát hiện số lạ nào. Toàn bộ các giá trị số trong mô tả đều được xác minh hợp lệ với bảng chân lý.
        </div>
        """
    else:
        badge_bg = "#FDEDEC"
        badge_color = "#922B21"
        badge_border = "#F5B7B1"
        badge_text = f"⚠️ CẢNH BÁO: PHÁT HIỆN {u_cnt} SỐ LẠ"
        conclusion_html = f"""
        <div style="background-color: #FEF9E7; border-left: 5px solid #E67E22; padding: 12px 14px; border-radius: 4px; margin-bottom: 12px; font-size: 13.5px; color: #935116;">
            <b>⚠️ Kết luận đối kiểm:</b> Phát hiện <b>{u_cnt} giá trị số</b> trong mô tả chưa đối chuẩn được với bảng số liệu gốc (Độ trung thực: <b>{acc:.1f}%</b>). <b>TUYỆT ĐỐI KHÔNG XÁC NHẬN ZERO-HALLUCINATION</b> cho đến khi các số lạ này được rà soát và đối chuẩn. Vui lòng xem bảng chi tiết bên dưới.
        </div>
        """
        rows_html = []
        for u in fact_res["unmatched_items"]:
            raw_esc = html.escape(u["raw_str"])
            sent_esc = html.escape(u["sentence"])
            highlighted_sent = sent_esc.replace(raw_esc, f"<mark style='background-color: #FADBD8; color: #78281F; font-weight: bold; padding: 1px 4px; border-radius: 2px;'>{raw_esc}</mark>")
            rows_html.append(f"""
            <tr style="border-bottom: 1px solid #F2D7D5; font-size: 12.5px;">
                <td style="padding: 8px 10px; font-weight: bold; color: #1B4F72; border-right: 1px solid #FADBD8; white-space: nowrap;">{html.escape(u['level'])}</td>
                <td style="padding: 8px 10px; border-right: 1px solid #FADBD8; white-space: nowrap;"><code style="background: #FDEDEC; color: #C0392B; padding: 2px 5px; border-radius: 3px; font-weight: bold;">{raw_esc}</code><br><span style="font-size: 11px; color: #7F8C8D;">(giá trị: {u['clean_val']})</span></td>
                <td style="padding: 8px 10px; border-right: 1px solid #FADBD8; line-height: 1.4; color: #2C3E50;">{highlighted_sent}</td>
                <td style="padding: 8px 10px; border-right: 1px solid #FADBD8; font-size: 12px; color: #5D6D7E; line-height: 1.4;">{html.escape(u['gt_ref'])}</td>
                <td style="padding: 8px 10px; font-weight: bold; color: #C0392B; font-size: 12px;">{html.escape(u['classification'])}</td>
            </tr>
            """)
        unmatched_table_html = f"""
        <div style="margin-top: 10px;">
            <div style="font-weight: bold; color: #C0392B; margin-bottom: 6px; font-size: 13.5px;">
                🔍 Danh sách chi tiết các giá trị số lạ / chưa đối chuẩn ({u_cnt} mục):
            </div>
            <div style="overflow-x: auto; border: 1px solid #F5B7B1; border-radius: 4px;">
                <table style="width: 100%; border-collapse: collapse; background: #FFFFFF;">
                    <thead>
                        <tr style="background-color: #FDEDEC; color: #78281F; text-align: left; border-bottom: 2px solid #F5B7B1; font-size: 12.5px;">
                            <th style="padding: 8px 10px; border-right: 1px solid #F5B7B1;">Cấp mô tả</th>
                            <th style="padding: 8px 10px; border-right: 1px solid #F5B7B1;">Số bắt được</th>
                            <th style="padding: 8px 10px; border-right: 1px solid #F5B7B1;">Ngữ cảnh trong câu</th>
                            <th style="padding: 8px 10px; border-right: 1px solid #F5B7B1;">Kết quả đối chiếu bảng gốc</th>
                            <th style="padding: 8px 10px;">Nguyên nhân & Phân loại</th>
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
        matched_rows_html.append(f"""
        <tr style="border-bottom: 1px solid #EAECEE; font-size: 12px;">
            <td style="padding: 6px 8px; font-weight: 500; color: #2C3E50; border-right: 1px solid #EAECEE;">{html.escape(m['level'])}</td>
            <td style="padding: 6px 8px; border-right: 1px solid #EAECEE;"><code style="background: #EAFAF1; color: #1E8449; padding: 2px 4px; border-radius: 3px; font-weight: bold;">{html.escape(m['raw_str'])}</code></td>
            <td style="padding: 6px 8px; border-right: 1px solid #EAECEE; color: #2874A6; font-weight: 500;">{html.escape(m['match_type'])}</td>
            <td style="padding: 6px 8px; color: #566573;">{html.escape(m['gt_ref'])}</td>
        </tr>
        """)

    matched_details_html = f"""
    <details style="margin-top: 12px; font-size: 12.5px; color: #566573;">
        <summary style="cursor: pointer; font-weight: bold; color: #2874A6; padding: 4px 0;">
            📋 Xem danh sách {m_cnt} giá trị số đã đối chiếu khớp hợp lệ...
        </summary>
        <div style="overflow-x: auto; margin-top: 8px; border: 1px solid #D4E6F1; border-radius: 4px;">
            <table style="width: 100%; border-collapse: collapse; background: #FFFFFF;">
                <thead>
                    <tr style="background-color: #EAF2F8; color: #1B4F72; text-align: left; font-size: 12px; border-bottom: 1px solid #D4E6F1;">
                        <th style="padding: 6px 8px; border-right: 1px solid #D4E6F1;">Cấp mô tả</th>
                        <th style="padding: 6px 8px; border-right: 1px solid #D4E6F1;">Số bắt được</th>
                        <th style="padding: 6px 8px; border-right: 1px solid #D4E6F1;">Tầng đối chuẩn</th>
                        <th style="padding: 6px 8px;">Chi tiết khớp bảng gốc</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(matched_rows_html)}
                </tbody>
            </table>
        </div>
    </details>
    """

    out_html = f"""
    <div style="background-color: #F8FBFD; border: 1px solid #D4E6F1; border-radius: 8px; padding: 16px; margin-top: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.03);">
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #EAECEE; padding-bottom: 10px; margin-bottom: 12px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 22px;">🛡️</span>
                <h4 style="margin: 0; color: #1B4F72; font-weight: bold; font-size: 15px;">
                    ĐO KIỂM THƯỚC ĐO VICHARTFACT (DATA FAITHFULNESS AUDIT)
                </h4>
            </div>
            <span style="background-color: {badge_bg}; color: {badge_color}; font-weight: bold; padding: 4px 12px; border-radius: 12px; font-size: 12.5px; border: 1px solid {badge_border};">
                {badge_text}
            </span>
        </div>

        <div style="background-color: #FFFFFF; border-left: 4px solid #2980B9; padding: 12px 16px; border-radius: 4px; margin-bottom: 14px; font-size: 13.5px; color: #2C3E50;">
            <div style="margin-bottom: 6px;">
                <b>📐 Công thức & Phương pháp tính độ trung thực:</b>
            </div>
            <div style="background-color: #F4F6F7; padding: 8px 12px; border-radius: 4px; font-family: monospace; font-size: 13px; color: #1A5276; margin-bottom: 6px;">
                Độ trung thực (Accuracy) = (N_khớp / N_tổng đối chiếu) × 100% = ({m_cnt} / {tot}) × 100% = <b>{acc:.1f}%</b>
            </div>
            <div style="font-size: 12.5px; color: #566573; line-height: 1.5;">
                • <b>Dung sai kiểm định:</b> Sai số tương đối ≤ 5.0% hoặc sai số tuyệt đối &lt; 0.05. Áp dụng chuẩn hóa số kiểu Việt (<code>1.200</code> → 1200, <code>12,5%</code> → 12.5%).<br>
                • <b>Tập chân lý đối chuẩn (Ground-Truth Pool):</b> {cell_cnt} ô số liệu bảng từ các chuỗi dữ liệu, {cat_cnt} nhãn mốc thời gian/danh mục trục hoành, các thông số cấu trúc/tiêu đề và các phép tính chênh lệch/biên độ/tỷ lệ phái sinh hợp lệ từ bảng gốc.
            </div>
        </div>

        {conclusion_html}
        {unmatched_table_html}
        {matched_details_html}
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

    # 2. Thử qua thư viện edge_tts in-process
    try:
        import edge_tts
        import nest_asyncio
        nest_asyncio.apply()

        async def _speak():
            comm = edge_tts.Communicate(phonetic_text, voice_id)
            await comm.save(output_path)

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        loop.run_until_complete(_speak())
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
            <div style="background-color: #F8F9F9; border: 1px dashed #BDC3C7; border-radius: 6px; padding: 14px; text-align: center; color: #7F8C8D; font-size: 13.5px; line-height: 1.5;">
                ℹ️ <b>Chưa thực hiện đo kiểm ViChartFact:</b> Do hình ảnh tải lên chưa có ma trận dữ liệu trích xuất để làm bảng chân lý đối chuẩn. Vui lòng chọn một biểu đồ trong <i>Tập mẫu đại diện</i> bên dưới để quan sát quy trình đo kiểm ViChartFact chi tiết.
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
        tts_status_msg = f"✅ Đã tạo giọng đọc Hoài My (Nữ - Truyền cảm) cho cả 3 cấp độ (Động cơ: {eng_summary})."
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
    """Tạo lại âm thanh riêng cho một cấp độ khi người dùng bấm nút Nghe lại với giọng Hoài My."""
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

    speech_text = text.strip()
    audio_path = os.path.join(TEMP_AUDIO_DIR, f"{prefix}{uuid.uuid4().hex[:8]}.mp3")
    ok, eng = generate_tts_audio_sync(speech_text, audio_path, voice_id=HOAI_MY_VOICE_ID)
    if ok and os.path.exists(audio_path):
        remaining_files.append(audio_path)
        return audio_path, f"✅ Đã tạo giọng đọc Hoài My Cấp {level_num}.", remaining_files
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

            # Tab 2: Sinh mô tả 3 cấp độ & Giọng đọc TTS trực tiếp (Giọng Hoài My)
            with gr.Tab("🧠 Bước 3 & 4: Mô Tả 3 Cấp Độ & Giọng Đọc Trực Tiếp (TTS)"):
                # Cấp 1: Tổng quan 5s
                with gr.Group():
                    gr.Markdown("#### ⚡ Cấp 1: Tổng quan 5s (Dành cho học sinh xem nhanh)")
                    out_desc_5s = gr.Textbox(label="Nội dung mô tả Cấp 1", lines=2, interactive=False)
                    with gr.Row():
                        out_audio_lvl1 = gr.Audio(
                            label="🎧 Trình phát giọng đọc Cấp 1 (Hoài My - Đọc chuẩn số Việt: 1.200, 12,5%)",
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
                            label="🎧 Trình phát giọng đọc Cấp 2 (Hoài My - Đọc chuẩn số Việt: 1.200, 12,5%)",
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
                            label="🎧 Trình phát giọng đọc Cấp 3 (Hoài My - Đọc chuẩn số Việt: 1.200, 12,5%)",
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
                ### 🛡️ Nguyên Tắc Chống Ảo Giác & Thước Đo ViChartFact
                - **Bước 1 (Trích xuất ma trận)**: Bóc tách cấu trúc số liệu với cơ chế đọc số kiểu Việt (chấm hàng nghìn `1.200`, phẩy thập phân `12,5`).
                - **Bước 2 (Kiểm chứng logic)**: Áp dụng tập luật sư phạm (tổng phần trăm tròn $100\% \pm 2\%$, tính đơn điệu chuỗi thời gian). Tự động gắn cờ `[chưa chắc chắn]` khi mờ hoặc thiếu số liệu.
                - **Bước 3 (Mô tả 3 cấp độ Grounded & Đo kiểm ViChartFact)**:
                  - **Mô tả 3 cấp độ**: Sinh mô tả 5s (tổng quan nhanh), 30s (tóm tắt sư phạm), và chuyên sâu (phân tích chi tiết học tập) bám sát ma trận số liệu đã kiểm chứng.
                  - **Công thức ViChartFact**: $\text{Độ trung thực (Accuracy)} = \frac{N_{\text{khớp}}}{N_{\text{tổng đối chiếu}}} \times 100\%$ với dung sai cho phép $\le 5.0\%$ (hoặc sai số tuyệt đối $< 0.05$).
                  - **Tập chân lý đối chuẩn**: Toàn bộ ô số liệu bảng (`series_data`), nhãn mốc thời gian / danh mục (`categories`), và thông số cấu trúc / siêu dữ liệu biểu đồ.
                  - **Minh bạch số lạ**: Hiển thị bảng chi tiết từng số lạ (Cấp mô tả, Giá trị số bắt được, Câu văn ngữ cảnh, Đối chiếu bảng gốc, Phân loại nguyên nhân). Tuyệt đối **không xác nhận Zero-Hallucination** khi danh sách số lạ chưa được đối chuẩn ($< 100\%$).
                - **Bước 4 (Giọng đọc trợ năng TTS)**: Tích hợp 3 trình phát âm thanh riêng biệt đặt ngay dưới từng cấp mô tả bằng giọng đọc chuẩn Hoài My (Nữ - Truyền cảm, tự nhiên). Tự động chuẩn hóa số tiếng Việt khi đọc. File âm thanh chỉ lưu tạm thời trong phiên và tự động dọn sạch khi đổi ảnh / đặt lại.
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

    # 2. Nghe lại riêng lẻ từng cấp độ với giọng Hoài My
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
