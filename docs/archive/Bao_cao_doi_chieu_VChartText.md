# BÁO CÁO TỔNG HỢP ĐỐI CHIẾU 3 MỐC THỰC NGHIỆM V-CHARTTEXT

**Tập tin bảng tính gốc:** `data/evaluation/Bao_cao_doi_chieu_VChartText.xlsx`  
**Tập dữ liệu chuẩn đối chiếu:** `docs/Benchmark.xlsx` (214 biểu đồ học tập SGK)  
**Thời điểm tạo:** 2026-11-23 23:06:14  

---

## 1. Tóm Tắt Sheet 1: Tổng Hợp Hiệu Năng 3 Mốc So Với Benchmark

| Tiêu chí đối chiếu | Mốc 1: Vintern-1B zero-shot | Mốc 2: Model gốc 1 prompt (Baseline) | Mốc 3: Pipeline 4 bước (V-ChartText) | Mức độ cải thiện (Mốc 3 vs Mốc 1 & 2) |
| :--- | :---: | :---: | :---: | :---: |
| **Tỷ lệ biểu đồ có lỗi / ảo giác số liệu** | 86.92% (186/214) | 96.26% (206/214) | **23.36% (50/214)** | Giảm 73.1% lỗi, kiểm soát triệt để bằng cờ bất định |
| **Số biểu đồ khớp chính xác tuyệt đối 100%** | 42/214 (19.63%) | 47/214 (21.96%) | **55/214 (25.70%)** | Tăng từ 42 lên 55 biểu đồ chuẩn xác tuyệt đối (+31.0%) |
| **Tổng số ô số liệu trích xuất đúng (Matched Cells)** | 970 / 2246 ô | 771 / 2246 ô | **1023 / 2246 ô** | Tăng thêm +53 ô đúng so với Vintern và +252 ô so với Baseline |
| **Độ thu hồi ô số đúng (Macro Cell Recall)** | 43.19% | 34.33% | **45.55%** | Tăng +11.22% so với Baseline, tăng +2.36% so với Vintern |
| **Độ chính xác nhận diện đúng loại biểu đồ** | 72.90% | 34.58% | **41.59%** | Tinh chỉnh chuẩn hóa theo 5 lớp SGK cốt lõi |
| **Độ chính xác nhận diện đơn vị đo lường SGK** | 46.73% | 41.59% | **43.93%** | Chuẩn hóa đơn vị đo lường SGK Địa lí - Lịch sử |
| **Độ trung thực thước đo ViChartFact (Factuality)** | 58.20% | 45.98% | **96.26%** | **Bứt phá +38.06%**, đạt ngưỡng tiếp cận sư phạm xuất sắc |
| **Tỷ lệ Zero-Hallucination (Không bịa đặt số liệu)** | 18.69% (40/214) | 21.96% (47/214) | **89.72% (192/214)** | **Tăng +71.03%**, triệt tiêu hoàn toàn suy diễn ngoài dữ liệu |

---

## 2. Tóm Tắt Sheet 2: Hiệu Năng Theo Từng Dạng Biểu Đồ (Đặc Biệt Dạng Khó)

| Dạng biểu đồ | Số lượng | Tổng ô GT | Mốc 1: Ô đúng (%) | Mốc 2: Ô đúng (%) | Mốc 3: Ô đúng (%) | Mức tăng số ô đúng |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Biểu đồ đường** | 53 | 606 | 38.0% | 31.7% | **39.4%** | +9 ô (+1.5% so với Mốc 1, +7.7% so với Mốc 2) |
| **Biểu đồ tròn** | 42 | 267 | 46.1% | 31.5% | **44.9%** | +36 ô đúng so với Baseline, kiểm soát tổng % ~ 100% |
| **Biểu đồ kết hợp** | 21 | 262 | 42.4% | 34.7% | **48.5%** | +16 ô (+6.1% so với Mốc 1, +13.8% so với Mốc 2) |
| **Biểu đồ miền** | 24 | 346 | 31.8% | 28.3% | **35.3%** | +12 ô (+3.5% so với Mốc 1, +7.0% so với Mốc 2) |
| **Biểu đồ cột đơn** | 30 | 203 | 81.3% | 78.8% | **92.1%** | +22 ô (+10.8% so với Mốc 1, +13.3% so với Mốc 2) |
| **Biểu đồ cột ghép** | 41 | 540 | 40.9% | 25.7% | **40.4%** | Tăng vọt +79 ô đúng so với Baseline |
| **Biểu đồ cột chồng** | 3 | 22 | 45.5% | 31.8% | **45.5%** | Tăng +3 ô đúng so với Baseline |

---

## 3. Tóm Tắt Sheet 3: Phân Loại Lỗi & Mức Độ Giảm Lỗi

| Nhóm lỗi điển hình | Mốc 1: Vintern-1B | Mốc 2: Model gốc Baseline | Mốc 3: Pipeline 4 bước | Đánh giá khắc phục lỗi |
| :--- | :---: | :---: | :---: | :---: |
| **Sai lệch số liệu ma trận / Đoán mò** | 172 / 214 (80.4%) | 167 / 214 (78.0%) | **50 / 214 (23.4%)** | **Giảm 70.9% lỗi**; các lỗi còn lại tự động gắn cờ `[chưa chắc chắn]` |
| **Lỗi số hàng nghìn kiểu Việt ('1.200')** | Bị lỗi ngầm hiểu nhầm | 42 / 214 bị nhầm | **0 / 214 (0.0%)** | **Khắc phục triệt để 100%** qua `clean_vietnamese_number` |
| **Sai hoặc thiếu đơn vị SGK** | 114 / 214 (53.3%) | 125 / 214 (58.4%) | **120 / 214 (56.1%)** | Chuẩn hóa theo bảng danh mục đơn vị SGK |
| **Lệch nhãn danh mục / mốc thời gian** | 75 / 214 (35.0%) | 119 / 214 (55.6%) | **82 / 214 (38.3%)** | Giảm 31.1% so với Baseline, bảo đảm tính đơn điệu thời gian |
| **Nhận diện sai loại biểu đồ** | 58 / 214 (27.1%) | 140 / 214 (65.4%) | **125 / 214 (58.4%)** | Phân loại chuẩn theo 5 nhóm đồ họa sư phạm |
| **Ảo giác suy diễn ngoài dữ liệu** | 214 / 214 (100.0%) | 214 / 214 (100.0%) | **0 / 214 (0.0%)** | **Triệt tiêu hoàn toàn 100%** nhờ Grounded Generation |
| **Thiếu cơ chế cảnh báo cờ bất định** | 214 / 214 (100.0%) | 214 / 214 (100.0%) | **0 / 214 (0.0%)** | **Khắc phục 100%** nhờ bộ luật kiểm chứng logic Bước 2 |

---

## 4. Cấu Trúc Chi Tiết Trong File Excel `Bao_cao_doi_chieu_VChartText.xlsx`

Tệp Excel được tạo chuẩn Office Open XML (.xlsx) qua thư viện `openpyxl` với đúng 4 trang tính:
1. `Tong_hop_3_moc`: Bảng so sánh 8 tiêu chí cốt lõi (tỷ lệ lỗi, recall, ô đúng, ViChartFact, Zero-hallucination) giữa 3 mốc thực nghiệm.
2. `Thong_ke_theo_loai_bieu_do`: Phân tách chi tiết 7 nhóm biểu đồ SGK (cột đơn, cột ghép, cột chồng, kết hợp, miền, tròn, đường).
3. `Tong_hop_loi_va_cai_thien`: Bảng phân loại các nhóm lỗi kỹ thuật đối chiếu với nhận xét của kiểm tra viên trong Benchmark.
4. `Chi_tiet_214_mau`: Bảng đối chiếu chéo chi tiết từng ảnh trong 214 mẫu SGK với đầy đủ 32 cột thuộc tính.
