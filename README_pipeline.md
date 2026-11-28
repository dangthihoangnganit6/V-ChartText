# V-ChartText: bộ thực nghiệm đánh giá pipeline 4 bước

Phần này của repo dùng để **đo** xem pipeline 4 bước (trích xuất → kiểm chứng → mô tả 3 cấp → đọc giọng nói) có giảm lỗi số liệu
so với việc để VLM mô tả thẳng từ ảnh hay không. Thực nghiệm chạy trên 200 biểu đồ SGK, 2 mô hình, và nhãn đã soát lại.
Lịch sử commit đầy đủ: repo `rangha26/V-ChartText`, nhánh `dev`.

## Repo này có những phần nào

| Phần | Vai trò |
|---|---|
| `app.py`, `notebooks/VChartText_*` (gốc repo) | **Demo web chính thức** (Gradio, Render, Qwen3-VL qua Colab, TTS Hoài My). Bước 2–3 gọi `src/pipeline` qua `src/pipeline/team_adapter.py` |
| `vichartfact_metrics.py` | Thước đo ViChartFact và Độ đầy đủ (dùng trong demo và thực nghiệm); bộ luật cơ sở của bước 2–3 (đối chứng B-nhóm, và là bản dự phòng của demo khi đặt `VCHART_STEP23=nhom`) |
| `src/`, `eval/`, `outputs/`, `data/labels/` | **Pipeline và bộ thực nghiệm**: bước 2–3 (R1–R9) dùng chung cho demo và thực nghiệm, chạy mô hình trên 200 ảnh, chấm điểm. Mọi số liệu trong báo cáo đến từ đây |
| `eval/run_team_pipeline.py` | Đưa bước 2–3 của nhóm (`vichartfact_metrics.py`) vào **cùng bộ thực nghiệm**, chấm bằng cả hai bộ chỉ số |

**Một nguồn nhãn: `data/labels/*.json`** (200 biểu đồ đã soát lại theo ảnh gốc ngày 24–25/11, xem `data/DATA_CARD.md`).
`docs/Benchmark.xlsx` được **xuất từ các file JSON này** bằng `python src/export_benchmark.py`, giữ đúng bố cục cũ để `app.py`
và các script của nhóm đọc như trước. Muốn sửa nhãn: sửa JSON rồi chạy lại lệnh trên, không sửa tay file Excel.
Bản Benchmark cũ (trước đợt soát) và các báo cáo chấm trên nó nằm ở `docs/archive/`.

## Mục checklist → file

| Mục | Nội dung | File |
|---|---|---|
| A4 | Chọn checkpoint vừa tài nguyên | `src/infer_qwen.py` (Qwen3-VL-2B-Instruct, fp16 trên T4), `src/infer_vintern.py` |
| B12, B15, B16 | Nhãn, kiểm tra chéo, data card | `data/labels/`, `data/DATA_CARD.md`, `eval/validate_labels.py` |
| C19 | Chạy Vintern-1B trên bộ dữ liệu | `outputs/Vintern-1B-v3_5__*.jsonl`, `notebooks/run_full_kaggle.ipynb` |
| C20 | Thống kê lỗi thường gặp | `eval/error_stats.py` → `eval/results/error_stats.md` |
| D22 | Parser JSON, chuẩn hoá số kiểu Việt | `eval/score_extract.py` (`read_pred`), `eval/vn_number.py` |
| D23–D24 | Luật kiểm chứng, gắn cờ "chưa chắc chắn" | `src/pipeline/verify.py` (luật R1–R9, dùng cho demo và thực nghiệm) |
| D25 | Mô tả 3 cấp từ bảng đã kiểm chứng | `src/pipeline/describe.py` |
| D26 | Kiểm tra mọi con số trong mô tả | `eval/check_describe.py`, `eval/compare_pipeline.py` |
| D27 | Đọc số kiểu Việt, TTS | `src/pipeline/vn.py`, `src/pipeline/speech.py` |
| D28 | Chạy toàn pipeline | `src/pipeline/run.py` |
| E29 | Đo trích xuất bảng (RA@5%) | `eval/score_extract.py`, `eval/summarize.py` → `eval/results/summary_models.md` |
| E31 | So sánh pipeline với baseline | `eval/compare_pipeline.py` → `eval/results/compare_pipeline.md`; `eval/paired_test.py` |
| E30 + E31 | Hai bản bước 2–3, hai bộ chỉ số, cùng dữ liệu | `eval/run_team_pipeline.py` → `eval/results/compare_team_pipeline.md` |
| F33, F34 | Demo web có giọng đọc | `app.py` ở gốc repo (bước 2–3 qua `src/pipeline/team_adapter.py`) |

## Kết quả chính (200 biểu đồ, nhãn đã soát)

**Bước 1: trích xuất bảng** (`eval/results/summary_models.md`)

| Mô hình | JSON hợp lệ | RA@5% chặt | RA@5% nới | RNSS |
|---|---|---|---|---|
| Qwen3-VL-2B-Instruct (prompt v1) | 0,975 | 0,609 | **0,705** | **0,901** |
| Qwen3-VL-2B-Instruct (prompt v2) | 0,975 | 0,616 | 0,682 | 0,863 |
| Vintern-1B-v3.5 | 0,940 | 0,236 | 0,319 | 0,587 |

**Mô tả** (`eval/results/compare_pipeline.md`). A = VLM mô tả thẳng từ ảnh, B = pipeline 4 bước, B' = pipeline có đọc số bị gắn cờ
kèm chữ "khoảng", C = pipeline với bảng nhãn đúng thay cho bước 1 (mức trần).

| Nhánh | % biểu đồ có số sai | % số sai | Độ phủ | % thiếu đơn vị |
|---|---|---|---|---|
| A – Qwen | 36,5 | 10,1 | 85,8 | 11,0 |
| **B – Qwen** | **12,5** | **5,2** | 68,4 | 20,5 |
| B' – Qwen | 14,0 | 5,7 | 72,3 | 20,5 |
| A – Vintern | 40,0 | 13,5 | 47,0 | 11,5 |
| B – Vintern | 18,0 | 11,6 | 51,3 | 26,0 |
| C – nhãn đúng | 0,0 | 0,0 | 75,9 | 1,5 |

Hiệu B − A, khoảng tin cậy 95% bootstrap ghép cặp:
- Qwen: % biểu đồ có số sai −24,0 [−32,0; −16,5]; % số sai −4,9 [−8,0; −2,0].
- Vintern: % biểu đồ có số sai −22,0 [−30,5; −13,5]; % số sai −1,8 [−13,6; +5,7] (không có ý nghĩa thống kê).

Prompt v2 không tốt hơn v1 một cách có ý nghĩa thống kê, và còn làm sót điểm nhiều hơn (`eval/results/paired_v1_v2.md`). Vì vậy báo cáo dùng v1.
Lịch sử các lần sửa luật: `eval/results/lich_su_pipeline.md`. Độ chính xác của cờ "chưa chắc chắn": `eval/results/phan_tich_co_kiem_chung.md`.

**Hạn chế của thước đo:** "% số sai" chỉ kiểm con số có nằm trong bảng nhãn hay không, **không** kiểm số đó có đặt đúng chuỗi hay mốc không.

### Hai bản cài đặt bước 2–3, chấm bằng hai bộ chỉ số (`eval/results/compare_team_pipeline.md`)

Hai bản dùng **cùng bảng bước 1**. **B-nhóm** là `vichartfact_metrics.py`; **B** là `src/pipeline/` với luật R1–R9.
Thước đo của nhóm (ViChartFact, Độ đầy đủ) được tính lại trên nhãn đã soát.

| Nhánh (Qwen3-VL) | % bđ có số sai (gồm số phái sinh đúng)¹ | ViChartFact (so với nhãn) | Số thực thể lệch / bđ | Độ đầy đủ | Số từ |
|---|---|---|---|---|---|
| A – mô tả thẳng | 24,5 | 96,2 | 0,84 | 81,9 | 172 |
| B-nhóm | 18,5 | 97,6 | 1,12 | **94,0** | 255 |
| B | **8,5** | **98,9** | **0,30** | 78,3 | 88 |
| C-nhóm (nhãn đúng) | 10,5 | 100,0 | 0,00 | 99,4 | 163 |
| C (nhãn đúng) | 0,0 | 99,7 | 0,17 | 83,7 | 94 |

¹ Mô tả của nhóm có nêu chênh lệch và mức tăng ("tăng thêm 32,4 nghìn ha"). Vì vậy cột này chấp nhận số phái sinh đúng
(hiệu, tổng, % thay đổi, số lần) tính từ bảng nhãn. Nếu chỉ chấp nhận giá trị ô, B-nhóm có 95,5% biểu đồ chứa số sai.

Cách đọc:
- **B ít lỗi số hơn B-nhóm** trên mọi mô hình, kể cả khi tính theo thước đo của nhóm. % biểu đồ có số sai giảm 10 điểm [−15,5; −4],
  ViChartFact tăng 1,4 [0,4; 2,5]. Với Vintern, khoảng cách còn rõ hơn (−27 điểm).
- **B-nhóm đầy đủ hơn hẳn**: Độ đầy đủ cao hơn khoảng 15 điểm, vì mô tả dài gấp khoảng 3 lần và nêu cả phân tích. Đây là
  đánh đổi giữa nói ít mà chắc và nói nhiều mà dễ sai.
- B-nhóm so với A: với Qwen, chênh lệch không có ý nghĩa thống kê (−6 [−14; +2]); với Vintern, B-nhóm kém hơn (+15),
  vì bộ luật đơn giản không bắt được bảng đọc sai.
- Ngay cả trên nhãn đúng (C-nhóm), khuôn câu của nhóm vẫn sai ở **biểu đồ có nhiều hình tròn**: cộng lát của các năm khác nhau
  ("đạt tổng tỷ trọng 200%") hoặc so lát năm này với lát năm khác ("gấp 22,4 lần").
- Hướng kết hợp: dùng bộ luật R1–R9 của B làm bước 2, giữ phần phân tích của B-nhóm nhưng chỉ tính trong cùng một hình tròn.

### Lỗi đã biết trong bộ đọc số của `vichartfact_metrics.py` (chưa sửa, để người viết thước đo quyết định)

- `clean_vietnamese_number` hiểu mọi số có đúng 3 chữ số sau dấu chấm hoặc dấu phẩy là số nguyên có dấu phân cách nghìn:
  '19,257' và '19.257' đều thành 19257. `docs/Benchmark.xlsx` mới tránh lỗi này bằng cách ghi '19,2570'. Tuy nhiên ViChartFact
  trên demo vẫn chấm sai mô tả có số như vậy (bar_049, line_018, area_013: mô tả đúng nhưng điểm 71–89%).
- Bộ tách số của ViChartFact đọc '6.586,6' thành hai số '6' và '586,6'. `team_adapter.py` bỏ dấu chấm nghìn trong mô tả của demo
  ('6586,6'), và `eval/run_team_pipeline.py` làm như vậy cho mọi nhánh trước khi chấm.

Lưu ý khi đo: `vichartfact_metrics` đọc số có dấu chấm nghìn ("6.586,6") thành hai số "6" và "586,6", nên script bỏ dấu chấm nghìn
khỏi mọi văn bản trước khi đưa vào thước đo của nhóm. Việc này chỉ đổi cách viết, không đổi giá trị. Mã bước 2–3 của nhóm không bị sửa.

## Chạy lại

```bash
pip install -r requirements-pipeline.txt        # requirements.txt ở gốc dành cho app.py / Render

# 0. (tuỳ chọn) chép ảnh từ data/dataset sang data/images/<id> theo manifest. Chỉ cần khi chạy lại bước 1
python src/prepare_dataset.py --raw data/dataset # sẽ tạo thêm 2 nhãn khung bar_063, bar_069 (ảnh trùng, status todo): xoá đi

# 1. Bước 1 đã chạy sẵn trên Kaggle -> outputs/*.jsonl (chạy lại: notebooks/run_full_kaggle.ipynb, cần GPU T4)

# 2. Bước 2–4 cho cả bộ dữ liệu (CPU, vài giây; kết quả luôn giống nhau)
for m in Qwen3-VL-2B-Instruct__extract__v1 Qwen3-VL-2B-Instruct__extract__v2 Vintern-1B-v3_5__extract__v1; do
  for u in omit hedge; do python src/pipeline/run.py --source pred --extract outputs/$m.jsonl --uncertain $u; done
done
python src/pipeline/run.py --source gold

# 3. Chấm điểm
for f in outputs/*__extract__*.jsonl;  do python eval/score_extract.py "$f"; done
for f in outputs/*__describe__*.jsonl; do python eval/check_describe.py "$f"; done
python eval/summarize.py
python eval/error_stats.py
python eval/compare_pipeline.py
python eval/paired_test.py
python eval/run_team_pipeline.py                 # bước 2–3 của nhóm, chấm bằng cả hai bộ chỉ số
```

PowerShell không có vòng `for` kiểu bash. Trên Windows, chạy trong Git Bash, hoặc gõ từng lệnh một.
Các file sinh ra (`outputs/pipeline/`, bảng chi tiết `eval/results/*__*.csv`) đã được ignore, không cần commit.

Notebook Kaggle clone repo `rangha26/V-ChartText` nhánh `dev` (bản gốc của phần này) và cần Kaggle secret `GH_TOKEN`.

Demo web của dự án là `app.py` ở gốc repo (xem `README.md`).
