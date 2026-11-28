# Lưu trữ: kết quả và nhãn trước khi thống nhất (trước 28/11/2026)

Các file ở đây **không dùng cho báo cáo cuối**. Chúng được chấm trên nhãn chưa soát và/hoặc dùng các định nghĩa chỉ số khác nhau
giữa các mốc. Giữ lại để tra cứu lịch sử.

| File | Nội dung | Vì sao không dùng nữa |
|---|---|---|
| `Benchmark_truoc_soat_22-11.xlsx` | Nhãn xuất từ Google Sheet ngày 22/11 (214 dòng) | 98/200 biểu đồ khác nhãn đã soát: 99 ô giá trị sai, 12 biểu đồ đã loại vẫn còn, 14 ảnh không in số chưa gắn cờ, chữ mẫu ở tiêu đề/đơn vị. Số thập phân ghi dấu chấm ('19.257') nên `clean_vietnamese_number` đọc thành 19257 (73 giá trị). Thay bằng `docs/Benchmark.xlsx` xuất từ `data/labels/` (`python src/export_benchmark.py`) |
| `Bao_cao_doi_chieu_3_moc_benchmark.md`, `Bao_cao_doi_chieu_VChartText.md` | Đối chiếu 3 mốc (Qwen2-VL) | Chấm trên nhãn cũ; ViChartFact của mốc 1–2 tính bằng công thức gán trọng số từ F1 trích xuất, mốc 3 so mô tả với chính bảng bước 2, nên hai bên không so được với nhau |
| `Bao_cao_pipeline_4_buoc_214_anh.md` | Chạy bước 2–4 trên 214 ảnh | Nhãn cũ, Qwen2-VL; ViChartFact ở đây là mô tả so với bảng bước 2 (tự nhất quán), không so với nhãn |
| `Bao_cao_ViChartFact_va_Do_Day_Du.md` | ViChartFact và Độ đầy đủ (E30) | Chấm trên nhãn cũ. Chạy lại `python evaluate_vichartfact_completeness.py` để có bản mới trên `docs/Benchmark.xlsx` mới |

Số liệu dùng cho báo cáo: `eval/results/compare_pipeline.md`, `eval/results/compare_team_pipeline.md` (xem `README_pipeline.md`).
`docs/Bao_cao_danh_gia_thuc_nghiem_Muc_E.docx/.xlsx` và `data/VChartText_Outputs/` cũng còn số cũ cho tới khi chạy lại script trên.
