# BÁO CÁO ĐÁNH GIÁ THỰC NGHIỆM: VICHARTFACT & ĐỘ ĐẦY ĐỦ MÔ TẢ (MỤC E30)

**Module thực thi:** `vichartfact_metrics.py` & `evaluate_vichartfact_completeness.py`  
**Dữ liệu đối chuẩn:** `docs/Benchmark.xlsx` (214 biểu đồ SGK), `data/result_before.xlsx` (Baseline), `data/vcharttext_extracted_results.csv` (Bước 1 trích xuất)

---

## 1. Phương Pháp Đo Lường Chuẩn Hóa

1. **Thước đo ViChartFact (Độ trung thực số liệu):**
   - Tách riêng hai góc nhìn minh bạch:
     - **ViChartFact Groundedness (Bước 3 vs Bảng Bước 2):** Đo tỷ lệ thực thể số trong mô tả 3 cấp độ khớp với bảng số liệu đã kiểm chứng (sai số $\le 5\%$ hoặc $\le 0,05$), nhãn trục/năm, metadata và các phép tính phái sinh hợp lệ (biên độ, tổng, chênh lệch cùng mốc/cùng chuỗi, tỷ lệ Max/Min).
     - **ViChartFact End-to-End (Mô tả cuối vs Benchmark GT):** Đo tỷ lệ thực thể số trong mô tả cuối khớp với đáp án chuẩn `Benchmark.xlsx`.
2. **Thước đo Độ Đầy Đủ Mô Tả (`evaluate_description_completeness` — 0% đến 100%):**
   - Chấm trên **4 trụ cột sư phạm** (mỗi trụ cột 25 điểm) đối chiếu trực tiếp với `Benchmark.xlsx`:
     1. **Chủ thể, Loại biểu đồ & Đơn vị (25đ):** Đúng loại biểu đồ (10đ) + sát chủ đề/tiêu đề (7,5đ) + đúng đơn vị đo (7,5đ).
     2. **Phạm vi, Mốc trục hoành & Chuỗi chú giải (25đ):** Tỷ lệ bao phủ các danh mục/năm (15đ) + tên chuỗi dữ liệu (10đ).
     3. **Cực trị Max/Min & Bao phủ ô số liệu (25đ):** Nêu đúng Max/Min thực tế kèm ngữ cảnh cực trị (12,5đ) + tỷ lệ bao phủ các ô số liệu GT trong mô tả (12,5đ).
     4. **Phân tích Xu hướng/Cơ cấu & Tuân thủ sư phạm (25đ):** Phân tích đúng hướng biến thiên/tỷ trọng/chênh lệch (15đ) + không bịa nguyên nhân kinh tế–xã hội và có cảnh báo `[chưa chắc chắn]` khi bảng thiếu/lệch (10đ).
3. **Lưu ý minh bạch về Baseline:** Tệp `data/result_before.xlsx` chỉ lưu bảng trích xuất thô (không lưu văn bản thuyết minh tự do), nên mô tả Baseline được sinh trực tiếp từ bảng thô chưa qua `clean_vietnamese_number` và chưa qua Bước 2 kiểm chứng/gắn cờ để đánh giá công bằng tác động của Pipeline 4 bước trên cùng bộ dữ liệu.

---

## 2. Kết Quả Tổng Hợp Thực Đo (60 Mẫu & 214 Mẫu)

| Chỉ số đánh giá | Baseline (`result_before.xlsx`) | Pipeline 4 bước (End-to-End vs GT) | Pipeline Bước 3 (Grounded vs Bước 2) | Bước 2–3 trên Bảng Chuẩn |
| :--- | :---: | :---: | :---: | :---: |
| **ViChartFact Factuality (60 mẫu)** | 86.64% | **84.97%** | **98.33%** | 100.00% |
| **Độ đầy đủ mô tả Completeness (60 mẫu)** | 50.61% | **73.32%** | **97.88%** | 98.98% |
| **ViChartFact Factuality (214 mẫu)** | 83.54% | **85.43%** | **99.53%** | 100.00% |
| **Độ đầy đủ mô tả Completeness (214 mẫu)** | 52.43% | **74.23%** | **98.83%** | 99.19% |
| **Số thực thể lệch GT TB / mẫu (214 mẫu)** | 1.32 | **3.22** | 0.00 (trên 213 ảnh) | 0.00 |

> **Nhận xét chính:**
> - **Tại Bước 3 (Sinh mô tả):** Trên **213/213** biểu đồ trích xuất được dữ liệu (trừ 1 ảnh GIF `Biểu đồ tròn_33.gif`), Pipeline đạt **100.00% Grounded ViChartFact** (tính cả mẫu GIF lỗi là **99.53%**) và **98.83%** độ bao phủ bảng Bước 2 — hoàn toàn không tự bịa số liệu mới trong quá trình diễn giải.
> - **So với Baseline trên tập 214 mẫu:** Độ đầy đủ mô tả thực tế đối chiếu GT tăng từ **52.43%** lên **74.23%** (**+21.80%**), và trên dữ liệu bảng đã kiểm chứng đạt **99.19%**. Khoảng cách giữa **74.23%** (E2E) và **99.19%** (Bảng chuẩn) phản ánh trung thực phần sai sót OCR/thiếu chuỗi còn lại ở Bước 1 (`Qwen2-VL-2B`), trong đó hệ thống đã tự động gắn cờ `[chưa chắc chắn]` cho **151/214** mẫu có dấu hiệu bất thường.

---

## 3. Phân Tích Chi Tiết Theo Loại Biểu Đồ (214 Mẫu)

| Loại biểu đồ | Số lượng | Baseline VF (vs GT) | Pipeline VF (E2E vs GT) | Pipeline VF (Grounded vs Bước 2) | Baseline Completeness | Pipeline Completeness (E2E vs GT) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| Biểu đồ cột | 74 | 89.34% | 92.16% | 100.00% | 54.74% | 85.05% |
| Biểu đồ kết hợp | 21 | 90.87% | 95.64% | 100.00% | 50.14% | 73.32% |
| Biểu đồ miền | 24 | 81.13% | 94.55% | 100.00% | 48.89% | 73.85% |
| Biểu đồ tròn | 42 | 75.73% | 70.71% | 97.62% | 44.83% | 60.65% |
| Biểu đồ đường | 53 | 79.81% | 79.51% | 100.00% | 57.73% | 70.39% |

---

## 4. Tệp Kết Quả Đã Xuất
- `data/VChartText_Outputs/vichartfact_60samples_eval.csv`
- `data/VChartText_Outputs/vichartfact_completeness_214samples_eval.csv`
- `data/VChartText_Outputs/charts/hinh2_danh_gia_vichartfact_va_do_day_du.png` (và `data/charts/...`)
- `data/VChartText_Outputs/Bao_cao_danh_gia_thuc_nghiem_Muc_E.xlsx` (và `docs/...`)
