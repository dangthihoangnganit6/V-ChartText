### So sánh mô tả trực tiếp (A), pipeline (B) và pipeline + nhãn đúng (C)

| nhanh | tap | n_bd | n_so | %so_sai | %so_E1 | %bd_co_so_sai | do_phu_% | %thieu_don_vi | so_tu_tb |
|---|---|---|---|---|---|---|---|---|---|
| A_Qwen3-VL-2B-Instruct | tat_ca | 200 | 2209 | 10.1 | 1.1 | 36.5 | 85.8 | 11.0 | 172 |
| A_Vintern-1B-v3_5 | tat_ca | 200 | 1583 | 13.5 | 2.4 | 40.0 | 47.0 | 11.5 | 123 |
| C_nhan | tat_ca | 200 | 1330 | 0.0 | 0.0 | 0.0 | 75.9 | 1.5 | 94 |
| B_Qwen3-VL-2B-Instruct@v2 | tat_ca | 200 | 1038 | 6.1 | 1.1 | 10.5 | 61.5 | 17.5 | 83 |
| B_Qwen3-VL-2B-Instruct | tat_ca | 200 | 1211 | 5.2 | 0.8 | 12.5 | 68.4 | 20.5 | 88 |
| B_Vintern-1B-v3_5 | tat_ca | 200 | 971 | 11.6 | 1.9 | 18.0 | 51.3 | 26.0 | 74 |
| B'_Qwen3-VL-2B-Instruct@v2 | tat_ca | 200 | 1148 | 6.4 | 1.0 | 12.5 | 67.1 | 17.5 | 83 |
| B'_Qwen3-VL-2B-Instruct | tat_ca | 200 | 1297 | 5.7 | 0.8 | 14.0 | 72.3 | 20.5 | 88 |
| B'_Vintern-1B-v3_5 | tat_ca | 200 | 1114 | 10.7 | 1.8 | 19.5 | 58.3 | 26.0 | 73 |
| A_Qwen3-VL-2B-Instruct | sach | 160 | 1586 | 8.3 | 1.1 | 30.6 | 88.3 | 11.2 | 163 |
| A_Vintern-1B-v3_5 | sach | 160 | 1435 | 12.0 | 2.4 | 36.9 | 52.6 | 11.9 | 126 |
| C_nhan | sach | 160 | 1051 | 0.0 | 0.0 | 0.0 | 77.9 | 1.2 | 94 |
| B_Qwen3-VL-2B-Instruct@v2 | sach | 160 | 818 | 4.6 | 0.9 | 8.8 | 63.4 | 18.1 | 82 |
| B_Qwen3-VL-2B-Instruct | sach | 160 | 971 | 4.4 | 0.7 | 11.9 | 71.0 | 20.6 | 88 |
| B_Vintern-1B-v3_5 | sach | 160 | 722 | 12.0 | 2.5 | 15.6 | 51.9 | 25.6 | 73 |
| B'_Qwen3-VL-2B-Instruct@v2 | sach | 160 | 895 | 4.4 | 0.8 | 9.4 | 69.5 | 18.1 | 82 |
| B'_Qwen3-VL-2B-Instruct | sach | 160 | 1034 | 4.2 | 0.7 | 11.9 | 75.2 | 20.6 | 88 |
| B'_Vintern-1B-v3_5 | sach | 160 | 857 | 10.6 | 2.3 | 16.9 | 60.2 | 25.6 | 73 |

### Hiệu so với mô tả trực tiếp cùng mô hình (âm = pipeline ít lỗi hơn), CI 95% bootstrap

| so_sanh | chi_so | hieu | CI95 |
|---|---|---|---|
| B_Qwen3-VL-2B-Instruct@v2 - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai | -26.0 | [-33.5; -19.0] |
| B_Qwen3-VL-2B-Instruct@v2 - A_Qwen3-VL-2B-Instruct | %so_sai | -4.1 | [-7.2; -0.8] |
| B_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai | -24.0 | [-32.0; -16.5] |
| B_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %so_sai | -4.9 | [-8.0; -2.0] |
| B_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %bd_co_so_sai | -22.0 | [-30.5; -13.5] |
| B_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %so_sai | -1.8 | [-13.6; 5.7] |
| B'_Qwen3-VL-2B-Instruct@v2 - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai | -24.0 | [-31.0; -17.0] |
| B'_Qwen3-VL-2B-Instruct@v2 - A_Qwen3-VL-2B-Instruct | %so_sai | -3.7 | [-6.8; -0.7] |
| B'_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %bd_co_so_sai | -22.5 | [-30.0; -15.0] |
| B'_Qwen3-VL-2B-Instruct - A_Qwen3-VL-2B-Instruct | %so_sai | -4.4 | [-7.4; -1.6] |
| B'_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %bd_co_so_sai | -20.5 | [-29.0; -12.0] |
| B'_Vintern-1B-v3_5 - A_Vintern-1B-v3_5 | %so_sai | -2.8 | [-14.5; 4.4] |

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
| C_nhan | area | 24 | 0.0 | 0.0 | 76.5 |
| C_nhan | bar | 72 | 0.0 | 0.0 | 69.1 |
| C_nhan | combo | 21 | 0.0 | 0.0 | 67.8 |
| C_nhan | line | 41 | 0.0 | 0.0 | 72.1 |
| C_nhan | pie | 42 | 0.0 | 0.0 | 95.1 |
| B_Qwen3-VL-2B-Instruct@v2 | area | 24 | 3.5 | 8.3 | 64.2 |
| B_Qwen3-VL-2B-Instruct@v2 | bar | 72 | 7.5 | 11.1 | 61.2 |
| B_Qwen3-VL-2B-Instruct@v2 | combo | 21 | 4.7 | 19.0 | 57.5 |
| B_Qwen3-VL-2B-Instruct@v2 | line | 41 | 9.7 | 9.8 | 64.5 |
| B_Qwen3-VL-2B-Instruct@v2 | pie | 42 | 2.1 | 7.1 | 59.3 |
| B_Qwen3-VL-2B-Instruct | area | 24 | 2.9 | 12.5 | 62.0 |
| B_Qwen3-VL-2B-Instruct | bar | 72 | 8.1 | 18.1 | 63.4 |
| B_Qwen3-VL-2B-Instruct | combo | 21 | 3.7 | 14.3 | 58.5 |
| B_Qwen3-VL-2B-Instruct | line | 41 | 9.2 | 7.3 | 64.8 |
| B_Qwen3-VL-2B-Instruct | pie | 42 | 0.9 | 7.1 | 89.1 |
| B_Vintern-1B-v3_5 | area | 24 | 0.0 | 0.0 | 44.6 |
| B_Vintern-1B-v3_5 | bar | 72 | 12.3 | 22.2 | 58.6 |
| B_Vintern-1B-v3_5 | combo | 21 | 7.3 | 14.3 | 46.1 |
| B_Vintern-1B-v3_5 | line | 41 | 13.9 | 14.6 | 59.3 |
| B_Vintern-1B-v3_5 | pie | 42 | 20.2 | 26.2 | 37.7 |
| B'_Qwen3-VL-2B-Instruct@v2 | area | 24 | 5.5 | 16.7 | 74.3 |
| B'_Qwen3-VL-2B-Instruct@v2 | bar | 72 | 7.9 | 12.5 | 63.8 |
| B'_Qwen3-VL-2B-Instruct@v2 | combo | 21 | 4.1 | 19.0 | 63.7 |
| B'_Qwen3-VL-2B-Instruct@v2 | line | 41 | 9.1 | 9.8 | 68.3 |
| B'_Qwen3-VL-2B-Instruct@v2 | pie | 42 | 3.2 | 9.5 | 69.0 |
| B'_Qwen3-VL-2B-Instruct | area | 24 | 4.4 | 16.7 | 73.6 |
| B'_Qwen3-VL-2B-Instruct | bar | 72 | 8.6 | 19.4 | 65.8 |
| B'_Qwen3-VL-2B-Instruct | combo | 21 | 3.2 | 14.3 | 64.7 |
| B'_Qwen3-VL-2B-Instruct | line | 41 | 8.7 | 7.3 | 68.5 |
| B'_Qwen3-VL-2B-Instruct | pie | 42 | 2.0 | 9.5 | 89.9 |
| B'_Vintern-1B-v3_5 | area | 24 | 0.0 | 0.0 | 46.7 |
| B'_Vintern-1B-v3_5 | bar | 72 | 12.0 | 23.6 | 60.7 |
| B'_Vintern-1B-v3_5 | combo | 21 | 7.2 | 14.3 | 46.7 |
| B'_Vintern-1B-v3_5 | line | 41 | 13.4 | 14.6 | 62.0 |
| B'_Vintern-1B-v3_5 | pie | 42 | 13.3 | 31.0 | 62.8 |

Ví dụ trước/sau: eval\results\compare_examples.md
