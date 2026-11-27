"""
V-ChartText: Batch Pipeline 4 Bước Trên 214 Ảnh Dataset (Không Benchmark)
========================================================================
Quy tắc bắt buộc:
1. TUYỆT ĐỐI KHÔNG đọc, tham chiếu, copy hay fallback sang bất kỳ file/cột/dữ liệu benchmark hay ground-truth nào.
2. Quét toàn bộ file ảnh trong data/dataset (sắp xếp STT 1..214, ghi đúng image_name).
3. Điền đúng 9 cột chính A..I trên Sheet1:
   STT, image_name, chart_title, chart_type, unit, x_axis_label, categories, series_name, values
4. Bổ sung các cột đầu ra của Bước 2, 3, 4 ở các cột tiếp theo (J..R).
5. Lưu checkpoint định kỳ cuốn chiếu.
6. Ảnh lỗi/không trích xuất được thì để trống và ghi trạng thái lỗi an toàn, không lấy dữ liệu benchmark.
"""

import os
import sys
import re
import csv
import time
from typing import Dict, List, Any, Tuple, Optional
import pandas as pd

from vichartfact_metrics import (
    validate_chart_data,
    apply_uncertainty_flagging,
    generate_3level_descriptions,
    fact_check_vichartfact,
    evaluate_description_completeness,
    normalize_chart_type,
)
from xlsx_utils import write_xlsx_sheets

# Đảm bảo UTF-8 trên Windows PowerShell
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Cấu hình đường dẫn
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
DATASET_DIR = os.path.join(DATA_DIR, "dataset")
if not os.path.exists(DATASET_DIR):
    DATASET_DIR = os.path.join(WORKSPACE_DIR, "dataset")

EXTRACTED_RESULTS_PATH = os.path.join(DATA_DIR, "vcharttext_extracted_results.csv")

OUTPUT_XLSX = os.path.join(DATA_DIR, "pipeline_4_steps_results_214_filled.xlsx")
OUTPUT_CSV = os.path.join(DATA_DIR, "pipeline_4_steps_results_214_filled.csv")
CHECKPOINT_CSV = os.path.join(DATA_DIR, "pipeline_4_steps_results_214_filled_checkpoint.csv")

# Các hàm logic thuần túy đã được import từ vichartfact_metrics (không tham chiếu Benchmark)

def natural_sort_key(s: str) -> List[Any]:
    """Tách số và chữ để sắp xếp tự nhiên (ví dụ: Biểu đồ cột_2 đứng trước Biểu đồ cột_10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def scan_and_sort_dataset(dataset_path: str) -> List[Tuple[str, str]]:
    """
    Quét toàn bộ ảnh trong dataset_path, loại trừ file trùng lặp,
    và sắp xếp theo thứ tự chuẩn sư phạm: cột -> kết hợp -> miền -> tròn -> đường (1..214).
    """
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Không tìm thấy thư mục dataset tại: {dataset_path}")

    # Danh mục ưu tiên sắp xếp loại biểu đồ
    type_priority = {
        "cột": 1,
        "kết hợp": 2,
        "miền": 3,
        "tròn": 4,
        "đường": 5
    }

    raw_files = {}
    for root, _, files in os.walk(dataset_path):
        for f in files:
            f_clean = f.strip()
            if f_clean.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')):
                # Loại trừ file ảnh trùng lặp: 'Biểu đồ cột_46.jpg' (giữ lại bản chuẩn 'Biểu đồ cột_46.png')
                if f_clean == "Biểu đồ cột_46.jpg":
                    continue
                full_p = os.path.join(root, f)
                raw_files[f_clean] = full_p

    def category_sort_key(filename: str):
        fn_lower = filename.lower()
        cat_order = 99
        for k, prio in type_priority.items():
            if k in fn_lower:
                cat_order = prio
                break
        return (cat_order, natural_sort_key(filename))

    sorted_names = sorted(list(raw_files.keys()), key=category_sort_key)
    return [(fn, raw_files[fn]) for fn in sorted_names]

def load_extracted_results_only(csv_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Chỉ nạp kết quả trích xuất thực tế từ model (vcharttext_extracted_results.csv).
    Tuyệt đối không tham chiếu hay nạp bất kỳ file benchmark nào.
    """
    extracted_data = {}
    if not os.path.exists(csv_path):
        print(f"⚠️ Cảnh báo: Không tìm thấy file trích xuất: {csv_path}")
        return extracted_data

    df = pd.read_csv(csv_path)
    for _, row in df.iterrows():
        img_name = str(row.get("image_name", "")).strip()
        if not img_name or img_name == "nan":
            continue
        extracted_data[img_name] = {
            "chart_title": str(row.get("chart_title", "")).strip() if pd.notna(row.get("chart_title")) else "",
            "chart_type": normalize_chart_type(row.get("chart_type", "column")),
            "unit": str(row.get("unit", "")).strip() if pd.notna(row.get("unit")) else "",
            "x_axis_label": str(row.get("x_axis_label", "")).strip() if pd.notna(row.get("x_axis_label")) else "",
            "categories": str(row.get("categories", "")).strip() if pd.notna(row.get("categories")) else "",
            "series_name": str(row.get("series_name", "")).strip() if pd.notna(row.get("series_name")) else "",
            "values": str(row.get("values", "")).strip() if pd.notna(row.get("values")) else "",
        }
    print(f"✓ Đã nạp {len(extracted_data)} bản ghi trích xuất thực tế từ: {os.path.basename(csv_path)}")
    return extracted_data

def run_pipeline():
    start_time = time.time()
    print("=" * 70)
    print("KHỞI CHẠY PIPELINE 4 BƯỚC TRÊN 214 ẢNH DATASET (KHÔNG DÙNG BENCHMARK)")
    print("=" * 70)

    # 1. Quét toàn bộ ảnh trong thư mục dataset
    image_list = scan_and_sort_dataset(DATASET_DIR)
    total_images = len(image_list)
    print(f"✓ Quét thành công: {total_images} ảnh từ thư mục dataset.")

    # 2. Nạp dữ liệu trích xuất từ Bước 1
    extracted_lookup = load_extracted_results_only(EXTRACTED_RESULTS_PATH)

    # 3. Đọc Checkpoint cuốn chiếu nếu có
    completed_records = {}
    if os.path.exists(CHECKPOINT_CSV):
        try:
            df_ckpt = pd.read_csv(CHECKPOINT_CSV, encoding="utf-8-sig")
            for _, r in df_ckpt.iterrows():
                completed_records[str(r["image_name"]).strip()] = r.to_dict()
            print(f"🔄 Tìm thấy checkpoint: Đã xử lý {len(completed_records)}/{total_images} ảnh.")
        except Exception as e:
            print(f"Không thể đọc checkpoint ({e}), sẽ chạy mới từ đầu.")

    results: List[Dict[str, Any]] = []
    success_count = 0
    error_count = 0
    batch_buffer: List[Dict[str, Any]] = []
    batch_size = 10

    for idx, (img_name, img_path) in enumerate(image_list, start=1):
        # Nếu đã có trong checkpoint
        if img_name in completed_records:
            results.append(completed_records[img_name])
            if completed_records[img_name].get("execution_status") == "Thành công":
                success_count += 1
            else:
                error_count += 1
            continue

        item_start = time.time()
        
        # BƯỚC 1: LẤY DỮ LIỆU TRÍCH XUẤT THỰC TẾ (TUYỆT ĐỐI KHÔNG FALLBACK BENCHMARK)
        if img_name in extracted_lookup:
            ext_record = extracted_lookup[img_name]
            step1_dict = {
                "chart_title": ext_record.get("chart_title", ""),
                "chart_type": ext_record.get("chart_type", "column"),
                "unit": ext_record.get("unit", ""),
                "x_axis_label": ext_record.get("x_axis_label", ""),
                "categories": ext_record.get("categories", ""),
                "series_name": ext_record.get("series_name", ""),
                "values": ext_record.get("values", "")
            }
            extraction_valid = True
        else:
            # Ảnh không trích xuất được số liệu từ Bước 1 (ví dụ: Biểu đồ tròn_33.gif)
            # TUYỆT ĐỐI KHÔNG lấy ground-truth benchmark -> để trống và ghi nhận lỗi trích xuất
            step1_dict = {
                "chart_title": "",
                "chart_type": "",
                "unit": "",
                "x_axis_label": "",
                "categories": "",
                "series_name": "",
                "values": ""
            }
            extraction_valid = False

        if extraction_valid:
            try:
                # BƯỚC 2: Kiểm chứng dữ liệu & Gắn cờ [chưa chắc chắn]
                val_status, val_notes, parsed_matrix = validate_chart_data(step1_dict)
                flagged_matrix = apply_uncertainty_flagging(parsed_matrix, val_notes)

                # BƯỚC 3: Sinh mô tả 3 cấp độ (5s, 30s, Phân tích học tập chuyên sâu)
                desc_dict = generate_3level_descriptions(flagged_matrix)

                # BƯỚC 4: Đo kiểm độ trung thực ViChartFact & Độ đầy đủ mô tả (so với bảng Bước 2)
                fact_res = fact_check_vichartfact(desc_dict, flagged_matrix)
                comp_res = evaluate_description_completeness(
                    desc_dict,
                    step1_dict,
                    has_uncertainty=flagged_matrix.get("has_uncertainty", False),
                )

                exec_status = "Thành công"
                err_msg = ""
                success_count += 1
            except Exception as e:
                val_status = "Lỗi xử lý"
                val_notes = str(e)
                flagged_matrix = {"has_uncertainty": False}
                desc_dict = {"desc_5s": "", "desc_30s": "", "desc_study": ""}
                fact_res = {"status_title": "Lỗi", "accuracy": 0.0}
                comp_res = {"completeness_score": 0.0}
                exec_status = "Thất bại"
                err_msg = str(e)
                error_count += 1
        else:
            val_status = "Lỗi trích xuất"
            val_notes = "Không trích xuất được số liệu từ ảnh (định dạng GIF/ảnh rỗng)"
            flagged_matrix = {"has_uncertainty": False}
            desc_dict = {"desc_5s": "", "desc_30s": "", "desc_study": ""}
            fact_res = {"status_title": "Chưa đối chuẩn (thiếu số liệu)", "accuracy": 0.0}
            comp_res = {"completeness_score": 0.0}
            exec_status = "Lỗi trích xuất (Không fallback benchmark)"
            err_msg = "Không có số liệu trích xuất từ Bước 1; để trống theo yêu cầu Không tham chiếu Benchmark"
            error_count += 1

        elapsed_ms = round((time.time() - item_start) * 1000, 2)

        # Cấu trúc bản ghi: Đúng 9 cột chuẩn đầu tiên A..I
        row_data = {
            # 9 CỘT BẮT BUỘC (A..I)
            "STT": idx,
            "image_name": img_name,
            "chart_title": step1_dict["chart_title"],
            "chart_type": step1_dict["chart_type"],
            "unit": step1_dict["unit"],
            "x_axis_label": step1_dict["x_axis_label"],
            "categories": step1_dict["categories"],
            "series_name": step1_dict["series_name"],
            "values": step1_dict["values"],

            # CÁC CỘT BỔ SUNG CỦA BƯỚC 2, 3, 4 (J..R)
            "step2_validation_status": val_status,
            "step2_validation_notes": "; ".join(val_notes) if isinstance(val_notes, list) else str(val_notes),
            "step2_has_uncertainty": "Có" if flagged_matrix.get("has_uncertainty") else "Không",
            "step3_desc_5s": desc_dict.get("desc_5s", ""),
            "step3_desc_30s": desc_dict.get("desc_30s", ""),
            "step3_desc_study": desc_dict.get("desc_study", ""),
            "step4_vichartfact_status": fact_res.get("status_title", ""),
            "step4_vichartfact_accuracy": fact_res.get("accuracy", 0.0),
            "step4_completeness_score": comp_res.get("completeness_score", 0.0),
            "execution_status": exec_status,
            "error_log": err_msg
        }

        results.append(row_data)
        batch_buffer.append(row_data)

        # Checkpoint cuốn chiếu
        if len(batch_buffer) >= batch_size:
            df_cur = pd.DataFrame(results)
            df_cur.to_csv(CHECKPOINT_CSV, index=False, encoding="utf-8-sig")
            print(f"-> Checkpoint tiến độ: {len(results)}/{total_images} ảnh ({len(results)*100/total_images:.1f}%)")
            batch_buffer = []

    # Lưu checkpoint hoàn chỉnh cuối cùng
    df_final = pd.DataFrame(results)
    df_final.to_csv(CHECKPOINT_CSV, index=False, encoding="utf-8-sig")

    total_time = round(time.time() - start_time, 2)
    print("=" * 70)
    print("HOÀN THÀNH TOÀN BỘ 214 ẢNH!")
    print(f"Tổng thời gian: {total_time}s | Thành công: {success_count} | Lỗi: {error_count}")
    print("=" * 70)

    # 4. XUẤT FILE EXCEL THEO ĐÚNG BỐ CỤC YÊU CẦU
    print(f"Đang ghi file Excel: {OUTPUT_XLSX} ...")

    main_9_cols = [
        "STT", "image_name", "chart_title", "chart_type",
        "unit", "x_axis_label", "categories", "series_name", "values"
    ]
    all_cols = list(df_final.columns)

    sheet1_rows = [all_cols] + [
        [r_data.get(col_name, "") for col_name in all_cols] for r_data in results
    ]
    sheet2_rows = [main_9_cols] + [
        [r_data.get(col_name, "") for col_name in main_9_cols] for r_data in results
    ]
    write_xlsx_sheets(
        OUTPUT_XLSX,
        [("Sheet1", sheet1_rows), ("9_Cot_Chinh_Trich_Xuat", sheet2_rows)],
    )
    print(f"✓ Đã lưu file Excel: {OUTPUT_XLSX}")

    # Xuất file CSV UTF-8 BOM
    df_final.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"✓ Đã lưu file CSV: {OUTPUT_CSV}")

    return OUTPUT_XLSX

if __name__ == "__main__":
    run_pipeline()
