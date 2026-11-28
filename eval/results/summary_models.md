
### Theo mô hình

| model | n_charts_extract | json_ok | RA@5% | RNSS | type_ok | unit_ok | RA@5%_noi | RNSS_noi | unit_ok_noi | n_sach | RA@5%_sach | RA@5%_noi_sach | n_tat_ca | json_ok_tat_ca | json_cuu_duoc | extract_cham_gioi_han | extract_lap | loai_dung_tat_ca | loai_khong_hop_le | n_charts_describe | desc_%so_dung | desc_so_chua_khop | desc_E1 | desc_E3_thieu_don_vi_% | desc_E9_khong_TV_% | desc_so_tu_tb | desc_lap_tat_ca | desc_chen_tieng_Anh_% | desc_khong_co_so | giay_moi_lan_goi |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3-VL-2B-Instruct | 200 | 0.975 | 0.609 | 0.901 | 0.845 | 0.695 | 0.705 | 0.907 | 0.9 | 160 | 0.618 | 0.731 | 200 | 0.975 | 5 | 5 | 2 | 0.87 | 9 | 200 | 0.777 | 486 | 89 | 0.13 | 0.0 | 171.89 | 4 | 0.195 | 0 | 19.299 |
| Qwen3-VL-2B-Instruct@v2 | 200 | 0.975 | 0.616 | 0.863 | 0.845 | 0.732 | 0.682 | 0.87 | 0.895 | 160 | 0.626 | 0.707 | 200 | 0.975 | 5 | 5 | 3 | 0.87 | 9 |  |  |  |  |  |  |  |  |  |  | 24.391 |
| Vintern-1B-v3_5 | 200 | 0.94 | 0.236 | 0.587 | 0.545 | 0.332 | 0.319 | 0.602 | 0.816 | 160 | 0.25 | 0.335 | 200 | 0.94 | 11 | 10 | 5 | 0.583 | 0 | 200 | 0.771 | 337 | 74 | 0.13 | 0.0 | 123.495 | 3 | 0.0 | 10 | 9.451 |

### Theo loại biểu đồ

| model | chart_type | n | RA@5% | RA@5%_noi | RNSS | loai_dung_tat_ca | desc_%so_dung |
|---|---|---|---|---|---|---|---|
| Qwen3-VL-2B-Instruct | area | 24 | 0.514 | 0.514 | 0.93 | 0.792 | 0.889 |
| Qwen3-VL-2B-Instruct | bar | 72 | 0.786 | 0.81 | 0.927 | 1.0 | 0.732 |
| Qwen3-VL-2B-Instruct | combo | 21 | 0.74 | 0.74 | 0.887 | 0.0 | 0.875 |
| Qwen3-VL-2B-Instruct | line | 41 | 0.736 | 0.823 | 0.877 | 1.0 | 0.819 |
| Qwen3-VL-2B-Instruct | pie | 42 | 0.169 | 0.503 | 0.872 | 1.0 | 0.729 |
| Qwen3-VL-2B-Instruct@v2 | area | 24 | 0.559 | 0.559 | 0.923 | 0.792 |  |
| Qwen3-VL-2B-Instruct@v2 | bar | 72 | 0.755 | 0.779 | 0.899 | 1.0 |  |
| Qwen3-VL-2B-Instruct@v2 | combo | 21 | 0.725 | 0.725 | 0.872 | 0.0 |  |
| Qwen3-VL-2B-Instruct@v2 | line | 41 | 0.735 | 0.822 | 0.877 | 1.0 |  |
| Qwen3-VL-2B-Instruct@v2 | pie | 42 | 0.241 | 0.43 | 0.749 | 1.0 |  |
| Vintern-1B-v3_5 | area | 24 | 0.096 | 0.096 | 0.438 | 0.0 | 0.901 |
| Vintern-1B-v3_5 | bar | 72 | 0.373 | 0.479 | 0.69 | 1.0 | 0.637 |
| Vintern-1B-v3_5 | combo | 21 | 0.209 | 0.226 | 0.494 | 0.0 | 0.669 |
| Vintern-1B-v3_5 | line | 41 | 0.335 | 0.409 | 0.554 | 0.073 | 0.917 |
| Vintern-1B-v3_5 | pie | 42 | 0.0 | 0.129 | 0.575 | 1.0 | 0.58 |

### Tần suất lỗi (chặt)

| model | E0 | E1 | E2 | E8 |
|---|---|---|---|---|
| Qwen3-VL-2B-Instruct | 122 | 8 | 403 | 423 |
| Qwen3-VL-2B-Instruct@v2 | 128 | 16 | 384 | 443 |
| Vintern-1B-v3_5 | 223 | 10 | 338 | 1245 |

### Tần suất lỗi (nới)

| model | E0b | E1 | E2 | E8 |
|---|---|---|---|---|
| Qwen3-VL-2B-Instruct | 58 | 41 | 464 | 257 |
| Qwen3-VL-2B-Instruct@v2 | 75 | 38 | 409 | 348 |
| Vintern-1B-v3_5 | 180 | 11 | 443 | 1075 |
