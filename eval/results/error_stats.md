### Tần suất lỗi tự động (số biểu đồ mắc lỗi / số biểu đồ áp dụng)

| Mã | Lỗi | Qwen3-VL-2B-Instruct | Qwen3-VL-2B-Instruct@v2 | Vintern-1B-v3_5 |
|---|---|---|---|---|
| L1 | Gán sai loại biểu đồ (vd combo/area -> bar) | 26/200 (13.0%) | 26/200 (13.0%) | 83/199 (41.7%) |
| L2 | Biểu đồ nhiều chuỗi: lấy được < một nửa số chuỗi (thường chỉ 1 chuỗi) | 18/137 (13.1%) | 17/137 (12.4%) | 27/137 (19.7%) |
| L3 | Thiếu >= 30% điểm dữ liệu so với nhãn | 33/200 (16.5%) | 44/200 (22.0%) | 127/199 (63.8%) |
| L4 | >= 1 điểm lệch > 5% (E2) | 42/178 (23.6%) | 33/178 (18.5%) | 99/177 (55.9%) |
| L5 | Đọc sai dấu chấm/phẩy -> lệch đúng 10/100/1000 lần (E1) | 3/178 (1.7%) | 3/178 (1.7%) | 5/177 (2.8%) |
| L6 | Sai hoặc thiếu đơn vị trục y (chấm nới) | 19/190 (10.0%) | 20/190 (10.5%) | 34/189 (18.0%) |
| L7 | Ảnh không có tiêu đề nhưng mô hình tự đặt tiêu đề | 20/49 (40.8%) | 16/49 (32.7%) | 47/47 (100.0%) |
| L8 | Ảnh có tiêu đề nhưng chép sai (độ giống < 0.8) | 6/146 (4.1%) | 6/146 (4.1%) | 5/141 (3.5%) |
| L9 | Output extract không phải JSON hợp lệ (kể cả cứu được) | 5/200 (2.5%) | 5/200 (2.5%) | 12/200 (6.0%) |
| L10 | Lặp một điểm/cụm >= 5 lần | 2/200 (1.0%) | 3/200 (1.5%) | 5/200 (2.5%) |
| L11 | Chạm giới hạn max_new_tokens | 5/200 (2.5%) | 5/200 (2.5%) | 10/200 (5.0%) |
| D1 | Mô tả: có >= 1 con số không khớp số liệu (bịa/đọc sai) | 94/200 (47.0%) | 0/0 (None%) | 98/200 (49.0%) |
| D2 | Mô tả: có số lệch bậc 10/100/1000 (đọc nhầm 1.200 / 12,5) | 28/200 (14.0%) | 0/0 (None%) | 33/200 (16.5%) |
| D3 | Mô tả: không nhắc đơn vị của trục y | 26/190 (13.7%) | 0/0 (None%) | 26/190 (13.7%) |
| D4 | Mô tả: chen từ tiếng Anh | 39/200 (19.5%) | 0/0 (None%) | 0/200 (0.0%) |
| D5 | Mô tả: không nêu con số nào | 0/200 (0.0%) | 0/0 (None%) | 10/200 (5.0%) |

### Nhận xét tay của nhóm (tab Data_Labeling_AI), 163 ảnh có nhận xét

| Nhóm lỗi | Số ảnh | % |
|---|---|---|
| L2_thieu_chuoi | 59 | 36.2 |
| M2_sai_chinh_ta | 36 | 22.1 |
| L6_sai_don_vi | 32 | 19.6 |
| L4_sai_gia_tri | 30 | 18.4 |
| L8_sai_tieu_de | 26 | 16.0 |
| L3_thieu_diem | 22 | 13.5 |
| L1_sai_loai_bieu_do | 21 | 12.9 |
| M5_nham_truc | 19 | 11.7 |
| L7_bia_tieu_de | 16 | 9.8 |
| M1_chep_mau_prompt | 15 | 9.2 |
| M9_khac | 12 | 7.4 |
| M4_khong_doc_duoc | 11 | 6.7 |
| M3_bia_du_lieu | 10 | 6.1 |
| M6_dung | 5 | 3.1 |
| D4_chen_tieng_anh | 3 | 1.8 |
| L5_bac_so | 3 | 1.8 |
