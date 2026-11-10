# V-ChartText — Nhóm 7

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
pip install pillow numpy scipy
python src/prepare_dataset.py --raw "raw_drive/Ảnh biểu đồ"   # ảnh tải từ Drive
python eval/validate_labels.py
```

## Chạy mô hình (Colab GPU): mở `notebooks/run_baseline_colab.ipynb`

Lệnh tương ứng:
```bash
pip install -r requirements.txt
python src/infer_qwen.py --model Qwen/Qwen3-VL-2B-Instruct --task extract --limit 5
python src/infer_qwen.py --model Qwen/Qwen3-VL-2B-Instruct --task describe
python src/infer_vintern.py --task extract          # môi trường riêng nếu cần
python src/infer_vintern.py --task describe
python eval/score_extract.py outputs/Qwen3-VL-2B-Instruct__extract__v1.jsonl
python eval/check_describe.py outputs/Qwen3-VL-2B-Instruct__describe__v1.jsonl
```
Script chạy tiếp được khi Colab ngắt (bỏ qua id đã có trong file kết quả).

Mã gốc Qwen3-VL: https://github.com/QwenLM/Qwen3-VL (chỉ tham khảo, không cần chép vào repo).
