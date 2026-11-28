# Lịch sử cải tiến pipeline (bước 2–3), 200 biểu đồ, bảng trích xuất prompt v1

Chỉ số: % biểu đồ có ≥ 1 số sai · % số sai · độ phủ · % thiếu đơn vị (càng thấp càng tốt, trừ độ phủ).

| phiên bản | B Qwen | B Vintern | C nhãn đúng (mức trần) |
|---|---|---|---|
| v1 (21–25/11) | 11.5 · 5.2 · 66.4 · 26.5 | 17.5 · 11.1 · 48.3 · 39.5 | 0.0 · 0.0 · 75.0 · 1.0 |
| v2: nới R5/R7, chuẩn hoá đơn vị (25/11) | 12.5 · 5.1 · 68.7 · 20.5 | 18.0 · 10.7 · 51.0 · 26.0 | 0.0 · 0.0 · 75.7 · 1.5 |
| v3: văn phong mới, R8b (26/11) | 12.5 · 5.1 · 69.0 · 20.5 | 18.0 · 11.3 · 52.0 · 26.0 | 0.0 · 0.0 · 75.9 · 1.5 |
| v4: + R9 trùng số giữa chuỗi (26/11, hiện tại) | 12.5 · 5.2 · 68.4 · 20.5 | 18.0 · 11.6 · 51.3 · 26.0 | 0.0 · 0.0 · 75.9 · 1.5 |

- v2: R5 (tổng % < 100) chỉ còn cờ mức biểu đồ vì 89% (Qwen) / 99% (Vintern) số bị R5 cũ bỏ đi thực ra đúng; R7 (chuỗi không đổi) thành cờ mức biểu đồ; 'Ti USD' -> 'Tỉ USD'; biểu đồ tròn/miền luôn nêu đơn vị.
- v3: số 1..N ở biểu đồ cột không còn bị coi là trục thời gian (hết câu 'giá trị gần như không đổi trong giai đoạn' khi so sánh các lớp); liệt kê tự nhiên hơn; bỏ đơn vị chữ mẫu ('đơn vị', 'thứ tự'); R8b: nhãn trục 1..N -> cờ.
- v4: R9 gắn cờ ô mà hai chuỗi trùng số ở ≥ 3 mốc (mô hình đọc số thành một dãy rồi chia nhầm cho các chuỗi). Chỉ số % số sai tăng nhẹ vì thước đo chỉ kiểm con số có trong bảng hay không, KHÔNG kiểm số có đặt đúng chuỗi/mốc không (xem phan_tich_co_kiem_chung.md).
