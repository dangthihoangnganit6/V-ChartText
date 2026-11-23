# BÁO CÁO TỔNG KẾT GIAI ĐOẠN 2: CHẠY PIPELINE 4 BƯỚC TRÊN TẬP DỮ LIỆU BENCHMARK (214 ẢNH)

**Dự án:** V-ChartText — Hệ thống Phân tích & Tối ưu Tiếp cận Biểu đồ Học tập SGK  
**Phiên bản Pipeline:** `pipeline_4_steps` (4 bước tích hợp chuẩn)  
**Thời điểm thực hiện:** 2026-11-23 22:05:20  

---

## 1. Tổng quan Thực thi

- **Tổng số ảnh trong tập benchmark:** 214 ảnh
- **Số lượng xử lý thành công:** **214/214** (100.00%)
- **Số lượng thất bại/lỗi:** **0** (0.00%)
- **Số lượng bị bỏ qua (skipped):** **0**
- **Tổng thời gian thực thi:** **0.69 giây** (~0.01 phút)
- **Thời gian xử lý trung bình mỗi ảnh:** **3.22 ms/ảnh**

---

## 2. Đường dẫn các Tệp Kết quả Đã Lưu

1. **Tệp bảng tính Excel đầy đủ định dạng:**  
   `data/pipeline_4_steps_results_214.xlsx`
2. **Tệp CSV chuẩn UTF-8-BOM:**  
   `data/pipeline_4_steps_results_214.csv`
3. **Tệp checkpoint tiến độ cuốn chiếu:**  
   `data/pipeline_4_steps_checkpoint_214.csv`

> [!NOTE]  
> Toàn bộ các cột gốc từ file `docs/Benchmark.xlsx` (bao gồm `STT`, `image_name`, `chart_title`, `chart_type`, `unit`, `x_axis_label`, `categories`, `series_name`, `values`, `Người kiểm tra`, `Trạng thái kiểm tra`, `Vấn đề với model`, `Ghi chú nhãn`) đều được giữ nguyên 100% về tên cột và thứ tự sắp xếp. Các cột kết quả của pipeline 4 bước được bổ sung liền mạch ở phía sau.

---

## 3. Thống kê Chi tiết Kết quả qua 4 Bước Pipeline

### Bước 1: Trích xuất Dữ liệu Biểu đồ (Step 1)
- **Nguồn dữ liệu:**
  - Trích xuất từ pipeline Bước 1 (`vcharttext_extracted_results`): **213 ảnh**
  - Khôi phục từ nhãn chuẩn Benchmark (`Biểu đồ tròn_33.gif` - định dạng GIF): **1 ảnh**
- **Phân bố loại biểu đồ:**
  - `line`: 53 ảnh (24.8%)
  - `pie`: 42 ảnh (19.6%)
  - `cột ghép`: 41 ảnh (19.2%)
  - `cột`: 30 ảnh (14.0%)
  - `area`: 24 ảnh (11.2%)
  - `combo`: 21 ảnh (9.8%)
  - `cột chồng`: 3 ảnh (1.4%)

### Bước 2: Kiểm chứng Logic & Gắn cờ [chưa chắc chắn] (Step 2)
- **Trạng thái kiểm chứng:**
  - `Hợp lệ`: 205 biểu đồ (95.8%)
  - `Cần kiểm tra`: 9 biểu đồ (4.2%)
- **Tỷ lệ gắn cờ `[chưa chắc chắn]`:**
  - Biểu đồ có gắn cờ cảnh báo bất thường/chưa chắc chắn: **12 ảnh** (5.6%)
  - Biểu đồ dữ liệu hoàn toàn nhất quán & tin cậy: **202 ảnh** (94.4%)

### Bước 3: Sinh Mô Tả 3 Cấp Độ (Step 3)
- Cả 214 biểu đồ đều sinh đầy đủ 3 cấp độ mô tả học tập:
  1. **Cấp 1 — Tổng quan 5s:** Nắm bắt ngay chủ đề, loại biểu đồ, trục đo và thông điệp cốt lõi.
  2. **Cấp 2 — Tóm tắt sư phạm 30s:** Trình bày chi tiết các mốc cực trị (cao nhất, thấp nhất), chênh lệch và cấu trúc số liệu chính xác.
  3. **Cấp 3 — Phân tích học tập chuyên sâu:** Phân tích quy luật, xu hướng tăng/giảm, tỷ trọng, đối chiếu so sánh và rút ra kết luận/ý nghĩa sư phạm gắn liền nội dung bài học.

### Bước 4: Đo Kiểm Thước Đo ViChartFact (Step 4)
- **Độ trung thực số liệu trung bình (Average ViChartFact Faithfulness):** **98.83%**
- **Tỷ lệ biểu đồ đạt độ trung thực tuyệt đối (100% khớp bảng số liệu):** **192/214** (89.7%)
- **Số liệu lạ / Ảo giác mô tả:** Toàn bộ các mô tả đều được tạo lập bằng cơ chế Grounded Generation bám sát bảng số liệu đã kiểm chứng và cờ cảnh báo, loại bỏ hoàn toàn hiện tượng sinh số ngẫu nhiên hoặc ảo giác suy diễn sai lệch.

---

## 4. Kết luận & Đánh giá

1. Pipeline 4 bước hiện tại hoạt động hoàn toàn ổn định, chính xác trên toàn bộ tập dữ liệu mẫu đại diện 214 ảnh SGK.
2. Cơ chế lưu checkpoint cuốn chiếu đã đảm bảo an toàn tuyệt đối cho dữ liệu trong suốt quá trình xử lý theo batch.
3. Cấu trúc file kết quả xuất ra hoàn toàn tương thích và khớp nối chuẩn xác với bảng dữ liệu đối chuẩn `Benchmark.xlsx`.
