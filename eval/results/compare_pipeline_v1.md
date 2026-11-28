### So sánh mô tả trực tiếp (A), pipeline (B) và pipeline + nhãn đúng (C)

| nhanh | tap | n_bd | n_so | %so_sai | %so_E1 | %bd_co_so_sai | do_phu_% | %thieu_don_vi | so_tu_tb |
|---|---|---|---|---|---|---|---|---|---|
| A_Qwen3-VL-2B-Instruct | tat_ca | 200 | 2209 | 10.1 | 1.1 | 36.5 | 85.8 | 11.0 | 172 |
| A_Vintern-1B-v3_5 | tat_ca | 200 | 1583 | 13.5 | 2.4 | 40.0 | 47.0 | 11.5 | 123 |
| C_nhan | tat_ca | 200 | 1305 | 0.0 | 0.0 | 0.0 | 75.0 | 1.0 | 92 |
| B_Qwen3-VL-2B-Instruct | tat_ca | 200 | 1151 | 5.2 | 0.9 | 11.5 | 66.4 | 26.5 | 87 |
| B_Vintern-1B-v3_5 | tat_ca | 200 | 894 | 11.1 | 1.9 | 17.5 | 48.3 | 39.5 | 72 |
| B'_Qwen3-VL-2B-Instruct | tat_ca | 200 | 1274 | 5.6 | 0.8 | 14.0 | 72.0 | 21.0 | 86 |
| B'_Vintern-1B-v3_5 | tat_ca | 200 | 1050 | 10.0 | 1.8 | 19.0 | 57.1 | 26.5 | 72 |
| A_Qwen3-VL-2B-Instruct | sach | 160 | 1586 | 8.3 | 1.1 | 30.6 | 88.3 | 11.2 | 163 |
| A_Vintern-1B-v3_5 | sach | 160 | 1435 | 12.0 | 2.4 | 36.9 | 52.6 | 11.9 | 126 |
| C_nhan | sach | 160 | 1026 | 0.0 | 0.0 | 0.0 | 76.7 | 0.6 | 92 |
| B_Qwen3-VL-2B-Instruct | sach | 160 | 922 | 4.4 | 0.8 | 11.2 | 69.2 | 25.6 | 87 |
| B_Vintern-1B-v3_5 | sach | 160 | 682 | 11.1 | 2.5 | 15.0 | 48.5 | 41.9 | 72 |
| B'_Qwen3-VL-2B-Instruct | sach | 160 | 1013 | 4.1 | 0.7 | 11.9 | 74.9 | 20.6 | 86 |
| B'_Vintern-1B-v3_5 | sach | 160 | 830 | 9.6 | 2.3 | 16.2 | 59.1 | 26.2 | 71 |

### Hiệu so với mô tả trực tiếp cùng mô hình (âm = pipeline ít lỗi hơn), CI 95% bootstrap

| so_sanh | chi_so | hieu | CI95 |
|---|---|---|---|
| B_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai | -25.0 | [-33.0; -17.0] |
| B_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %so_sai | -4.9 | [-8.1; -1.8] |
| B_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %bd_co_so_sai | -22.5 | [-31.0; -14.5] |
| B_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %so_sai | -2.4 | [-13.9; 5.0] |
| B'_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai | -22.5 | [-30.0; -15.0] |
| B'_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %so_sai | -4.6 | [-7.5; -1.7] |
| B'_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %bd_co_so_sai | -21.0 | [-29.5; -12.5] |
| B'_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %so_sai | -3.5 | [-14.8; 3.5] |

### Theo loại biểu đồ

| nhanh | loai | n_bd | %so_sai | %bd_co_so_sai | do_phu_% |
|---|---|---|---|---|---|
| A_Qwen3-VL-2B-Instruct | area | 24 | 8.3 | 37.5 | 78.1 |
| A_Qwen3-VL-2B-Instruct | bar | 72 | 11.7 | 38.9 | 85.5 |
| A_Qwen3-VL-2B-Instruct | combo | 21 | 9.8 | 38.1 | 77.3 |
| A_Qwen3-VL-2B-Instruct | line | 41 | 14.1 | 39.0 | 85.5 |
| A_Qwen3-VL-2B-Instruct | pie | 42 | 4.9 | 28.6 | 95.1 |
| A_Vintern-1B-v3_5 | area | 24 | 8.8 | 75.0 | 29.2 |
| A_Vintern-1B-v3_5 | bar | 72 | 22.2 | 31.9 | 37.5 |
| A_Vintern-1B-v3_5 | combo | 21 | 30.3 | 52.4 | 40.2 |
| A_Vintern-1B-v3_5 | line | 41 | 5.9 | 39.0 | 54.0 |
| A_Vintern-1B-v3_5 | pie | 42 | 18.4 | 28.6 | 69.9 |
| C_nhan | area | 24 | 0.0 | 0.0 | 72.3 |
| C_nhan | bar | 72 | 0.0 | 0.0 | 68.4 |
| C_nhan | combo | 21 | 0.0 | 0.0 | 67.8 |
| C_nhan | line | 41 | 0.0 | 0.0 | 72.1 |
| C_nhan | pie | 42 | 0.0 | 0.0 | 94.3 |
| B_Qwen3-VL-2B-Instruct | area | 24 | 0.8 | 4.2 | 52.8 |
| B_Qwen3-VL-2B-Instruct | bar | 72 | 8.5 | 18.1 | 62.7 |
| B_Qwen3-VL-2B-Instruct | combo | 21 | 3.2 | 14.3 | 62.5 |
| B_Qwen3-VL-2B-Instruct | line | 41 | 8.8 | 7.3 | 64.9 |
| B_Qwen3-VL-2B-Instruct | pie | 42 | 1.0 | 7.1 | 83.9 |
| B_Vintern-1B-v3_5 | area | 24 | 0.0 | 0.0 | 44.7 |
| B_Vintern-1B-v3_5 | bar | 72 | 10.3 | 22.2 | 56.6 |
| B_Vintern-1B-v3_5 | combo | 21 | 7.3 | 14.3 | 46.1 |
| B_Vintern-1B-v3_5 | line | 41 | 13.4 | 12.2 | 59.1 |
| B_Vintern-1B-v3_5 | pie | 42 | 27.1 | 26.2 | 26.4 |
| B'_Qwen3-VL-2B-Instruct | area | 24 | 3.7 | 16.7 | 73.6 |
| B'_Qwen3-VL-2B-Instruct | bar | 72 | 8.4 | 19.4 | 65.1 |
| B'_Qwen3-VL-2B-Instruct | combo | 21 | 3.1 | 14.3 | 64.7 |
| B'_Qwen3-VL-2B-Instruct | line | 41 | 8.5 | 7.3 | 68.5 |
| B'_Qwen3-VL-2B-Instruct | pie | 42 | 2.1 | 9.5 | 89.9 |
| B'_Vintern-1B-v3_5 | area | 24 | 0.0 | 0.0 | 46.7 |
| B'_Vintern-1B-v3_5 | bar | 72 | 10.4 | 23.6 | 58.1 |
| B'_Vintern-1B-v3_5 | combo | 21 | 7.2 | 14.3 | 46.7 |
| B'_Vintern-1B-v3_5 | line | 41 | 13.2 | 12.2 | 60.8 |
| B'_Vintern-1B-v3_5 | pie | 42 | 13.4 | 31.0 | 62.8 |

Ví dụ trước/sau: eval\results\compare_examples.md
