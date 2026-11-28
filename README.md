# V-ChartText — Hệ Thống Thuyết Minh & Kiểm Định Biểu Đồ Địa Lí

Ứng dụng web Gradio hỗ trợ trích xuất dữ liệu biểu đồ sách giáo khoa, kiểm chứng logic sư phạm, sinh mô tả 3 cấp độ (5s, 30s, phân tích chi tiết), đo kiểm độ trung thực số liệu **ViChartFact** và đọc thuyết minh tiếng Việt (giọng Hoài My qua Edge-TTS / gTTS).

## Triển khai trên Render (Web Service - Python)

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python app.py`

---

# Pipeline, dữ liệu và đánh giá (phần của Giang, gộp từ `rangha26/V-ChartText`)

> **Số liệu dùng cho báo cáo**: `eval/results/compare_pipeline.md` (A/B/B'/C, CI 95%), `eval/results/summary_models.md`
> (trích xuất bước 1), `eval/results/paired_v1_v2.md` (prompt v1 vs v2), `eval/results/lich_su_pipeline.md`.
> Nhãn đúng dùng để chấm: `data/labels/*.json` (200 biểu đồ, đã soát lại theo ảnh gốc 24–25/11; khác `docs/Benchmark.xlsx` bản cũ).
> Thư viện cho phần này: `pip install -r requirements-pipeline.txt` (file `requirements.txt` ở gốc dành cho demo `app.py` trên Render).
> Demo thứ hai (chạy Qwen3-VL-2B 4-bit trên GPU 4 GB, có hỏi lại ảnh và viết lại văn phong): `python demo/app.py`.

Ứng dụng VLM trích xuất và sinh mô tả biểu đồ học tập (SGK Địa lí, Lịch sử) phục vụ hỗ trợ tiếp cận.

```
data/      images/ (KHÔNG đẩy lên repo public), labels/*.json, README.md = hướng dẫn gán nhãn
src/       prepare_dataset.py, prompts.py, infer_qwen.py (Qwen3-VL/Qwen2-VL), infer_vintern.py (Vintern-1B-v3.5)
eval/      validate_labels.py, score_extract.py, check_describe.py, vn_number.py, errors_manual_template.csv
outputs/   kết quả thô *.jsonl của mô hình
notebooks/ run_baseline_colab.ipynb
demo/      (Mức 2) web demo + đọc giọng nói
```

## Chuẩn bị dữ liệu (trên máy)
```bash
pip install -r requirements-pipeline.txt
python src/prepare_dataset.py --raw "raw_drive/Ảnh biểu đồ"   # ảnh tải từ Drive
python eval/validate_labels.py
```

## Chạy mô hình (Colab GPU): mở `notebooks/run_baseline_colab.ipynb`

Lệnh tương ứng:
```bash
pip install -r requirements-pipeline.txt
python src/infer_qwen.py --model Qwen/Qwen3-VL-2B-Instruct --task extract --limit 5
python src/infer_qwen.py --model Qwen/Qwen3-VL-2B-Instruct --task describe
python src/infer_vintern.py --task extract          # môi trường riêng nếu cần
python src/infer_vintern.py --task describe
python eval/score_extract.py outputs/Qwen3-VL-2B-Instruct__extract__v1.jsonl
python eval/check_describe.py outputs/Qwen3-VL-2B-Instruct__describe__v1.jsonl
```
Script chạy tiếp được khi Colab ngắt (bỏ qua id đã có trong file kết quả).

Mã gốc Qwen3-VL: https://github.com/QwenLM/Qwen3-VL (chỉ tham khảo, không cần chép vào repo).

## Mức 2: pipeline 4 bước, thí nghiệm A/B/C, demo

```
src/pipeline/verify.py    bước 2: kiểm chứng bảng (luật R1-R8, gắn cờ "chưa chắc chắn", không đoán số)
src/pipeline/describe.py  bước 3: mô tả 3 cấp bằng mẫu câu, chỉ dùng số trong bảng đã kiểm chứng
src/pipeline/vn.py        đọc số kiểu Việt ("12,5" -> "mười hai phẩy năm")
src/pipeline/speech.py    bước 4: văn bản để đọc + TTS (edge-tts / gTTS)
src/pipeline/run.py       chạy cả bộ dữ liệu; bước 1 = output extract đã có trong outputs/
eval/compare_pipeline.py  so sánh A (mô tả trực tiếp) / B (pipeline) / C (pipeline + nhãn đúng)
demo/app.py               demo Gradio + giọng đọc
```

```bash
python src/pipeline/run.py --source gold
python src/pipeline/run.py --source pred --extract outputs/Qwen3-VL-2B-Instruct__extract__v1.jsonl
python src/pipeline/run.py --source pred --extract outputs/Vintern-1B-v3_5__extract__v1.jsonl
python src/pipeline/run.py --source pred --extract outputs/Qwen3-VL-2B-Instruct__extract__v1.jsonl --uncertain hedge
python eval/compare_pipeline.py          # bảng + CI bootstrap + eval/results/compare_examples.md
# demo web: tải ảnh lên -> mô tả + giọng đọc (GPU 4 GB dùng 4-bit tự động)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
pip install -r demo/requirements.txt
python demo/app.py              # hoặc --no-model: chỉ thư viện 200 biểu đồ tính sẵn, không cần GPU
```
