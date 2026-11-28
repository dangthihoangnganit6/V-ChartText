# Hai bản cài đặt bước 2–3 trên cùng dữ liệu, chấm bằng hai bộ chỉ số

Sinh bởi `python eval/run_team_pipeline.py`. 200 biểu đồ, nhãn `data/labels/` (đã soát).
`B-nhom` / `C-nhom` = bước 2–3 của nhóm (`vichartfact_metrics.py`); `B` / `C` = bước 2–3 của Giang (`src/pipeline/`).
Cùng bảng bước 1 (`outputs/<mô hình>__extract__v1.jsonl`); C dùng bảng nhãn thay bước 1 (mức trần).

- `%bd_co_so_sai`, `%so_sai`, `do_phu_%`, `%thieu_don_vi`: thước đo của `eval/compare_pipeline.py` (con số phải khớp một ô nhãn),
  chấm trên mức diễn giải.
- `..._ps`: như trên nhưng chấp nhận thêm số phái sinh đúng (hiệu, tổng, % thay đổi, số lần giữa hai ô cùng chuỗi/mốc) và số đếm mốc/chuỗi.
- `vichartfact_%`, `so_lech_tb`, `day_du_%`: thước đo của nhóm (`fact_check_against_ground_truth`,
  `evaluate_description_completeness`), chấm trên cả 3 mức, so với nhãn đã soát.
- Lỗi khi chạy bước 2–3 của nhóm (mô tả rỗng): không có.

| nhanh | n_bd | %bd_co_so_sai | %so_sai | do_phu_% | %thieu_don_vi | %bd_co_so_sai_ps | %so_sai_ps | vichartfact_% | so_lech_tb | day_du_% | so_tu_tb |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A_Qwen3-VL-2B-Instruct | 200 | 36.5 | 10.1 | 85.8 | 11.0 | 24.5 | 6.2 | 96.2 | 0.84 | 81.9 | 172 |
| B-nhom_Qwen3-VL-2B-Instruct | 200 | 95.5 | 25.8 | 89.1 | 29.5 | 18.5 | 5.8 | 97.6 | 1.12 | 94.0 | 255 |
| B_Qwen3-VL-2B-Instruct | 200 | 12.5 | 5.2 | 68.4 | 20.5 | 8.5 | 3.2 | 98.9 | 0.3 | 78.3 | 88 |
| A_Vintern-1B-v3_5 | 200 | 40.0 | 13.5 | 47.0 | 11.5 | 23.5 | 5.9 | 93.8 | 1.94 | 70.5 | 123 |
| B-nhom_Vintern-1B-v3_5 | 200 | 83.0 | 42.1 | 65.6 | 62.0 | 38.5 | 23.6 | 92.5 | 4.33 | 82.7 | 258 |
| B_Vintern-1B-v3_5 | 200 | 18.0 | 11.6 | 51.3 | 26.0 | 11.5 | 6.4 | 96.6 | 0.7 | 69.0 | 74 |
| C-nhom_nhan | 200 | 96.5 | 20.7 | 95.4 | 6.5 | 10.5 | 1.1 | 100.0 | 0.0 | 99.4 | 163 |
| C_nhan | 200 | 0.0 | 0.0 | 75.9 | 1.5 | 0.0 | 0.0 | 99.7 | 0.17 | 83.7 | 94 |

## Hiệu giữa các nhánh (CI 95% bootstrap ghép cặp)

| so_sanh | chi_so | hieu | CI95 | co_y_nghia |
|---|---|---|---|---|
| B-nhom_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai | 59.0 | [52.0; 66.0] | có |
| B-nhom_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai_ps | -6.0 | [-14.0; 2.0] | không |
| B-nhom_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | vichartfact_% | 1.3 | [0.1; 2.7] | có |
| B-nhom_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | day_du_% | 12.1 | [10.8; 13.4] | có |
| B-nhom_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %bd_co_so_sai | 43.0 | [34.0; 51.0] | có |
| B-nhom_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %bd_co_so_sai_ps | 15.0 | [6.5; 23.5] | có |
| B-nhom_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | vichartfact_% | -1.3 | [-4.5; 1.6] | không |
| B-nhom_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | day_du_% | 12.2 | [10.0; 14.3] | có |
| B_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai | -24.0 | [-32.0; -16.5] | có |
| B_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai_ps | -16.0 | [-22.5; -9.5] | có |
| B_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | vichartfact_% | 2.7 | [1.5; 4.0] | có |
| B_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | day_du_% | -3.6 | [-5.3; -1.8] | có |
| B_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %bd_co_so_sai | -22.0 | [-30.5; -13.5] | có |
| B_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %bd_co_so_sai_ps | -12.0 | [-19.0; -5.0] | có |
| B_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | vichartfact_% | 2.8 | [0.4; 5.1] | có |
| B_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | day_du_% | -1.4 | [-3.8; 0.8] | không |
| B_Qwen3-VL-2B-Instruct - B-nhom_Qwen3-VL-2B-Instruct | %bd_co_so_sai | -83.0 | [-88.0; -77.5] | có |
| B_Qwen3-VL-2B-Instruct - B-nhom_Qwen3-VL-2B-Instruct | %bd_co_so_sai_ps | -10.0 | [-15.5; -4.0] | có |
| B_Qwen3-VL-2B-Instruct - B-nhom_Qwen3-VL-2B-Instruct | vichartfact_% | 1.4 | [0.4; 2.5] | có |
| B_Qwen3-VL-2B-Instruct - B-nhom_Qwen3-VL-2B-Instruct | day_du_% | -15.7 | [-17.0; -14.3] | có |
| B_Vintern-1B-v3_5 - B-nhom_Vintern-1B-v3_5 | %bd_co_so_sai | -65.0 | [-71.0; -58.0] | có |
| B_Vintern-1B-v3_5 - B-nhom_Vintern-1B-v3_5 | %bd_co_so_sai_ps | -27.0 | [-33.0; -20.5] | có |
| B_Vintern-1B-v3_5 - B-nhom_Vintern-1B-v3_5 | vichartfact_% | 4.1 | [2.2; 6.4] | có |
| B_Vintern-1B-v3_5 - B-nhom_Vintern-1B-v3_5 | day_du_% | -13.7 | [-15.1; -12.3] | có |
| C_nhan - C-nhom_nhan | %bd_co_so_sai | -96.5 | [-99.0; -93.5] | có |
| C_nhan - C-nhom_nhan | %bd_co_so_sai_ps | -10.5 | [-15.0; -6.5] | có |
| C_nhan - C-nhom_nhan | vichartfact_% | -0.3 | [-0.8; 0.0] | không |
| C_nhan - C-nhom_nhan | day_du_% | -15.7 | [-16.9; -14.6] | có |
