# V-ChartText — Hệ Thống Thuyết Minh & Kiểm Định Biểu Đồ Địa Lí

Ứng dụng web Gradio hỗ trợ trích xuất dữ liệu biểu đồ sách giáo khoa, kiểm chứng logic sư phạm, sinh mô tả 3 cấp độ (5s, 30s, phân tích chi tiết), đo kiểm độ trung thực số liệu **ViChartFact** và đọc thuyết minh tiếng Việt (giọng Hoài My qua Edge-TTS / gTTS).

## Triển khai trên Render (Web Service - Python)

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python app.py`

## Cấu trúc dự án

```
data/labels/*.json  (200 biểu đồ, nhãn đã soát)  ──xuất──►  docs/Benchmark.xlsx   (python src/export_benchmark.py)
        │
Bước 1    Qwen3-VL-2B đọc ảnh → bảng JSON          demo: app.py (Colab) · thực nghiệm: outputs/ (Kaggle, 200 ảnh, thêm Vintern-1B)
Bước 2–3  kiểm chứng R1–R9 + mô tả 3 mức           src/pipeline/ (dùng chung cho demo và thực nghiệm)
Bước 4    đọc số tiếng Việt + giọng Hoài My         app.py
Đánh giá  % số sai, độ phủ (eval/) + ViChartFact, Độ đầy đủ (vichartfact_metrics.py) → eval/results/
```

- **Demo:** `python app.py`. Bước 2–3 mặc định dùng luật R1–R9 (`src/pipeline`). Đặt biến môi trường `VCHART_STEP23=nhom`
  để dùng bộ luật cơ sở trong `vichartfact_metrics.py`.
- **Thực nghiệm, số liệu báo cáo, bảng mục checklist → file:** `README_pipeline.md`.
- **Nhãn:** sửa trong `data/labels/*.json`, rồi chạy `python src/export_benchmark.py`. Kết quả cũ trên nhãn chưa soát nằm ở `docs/archive/`.
