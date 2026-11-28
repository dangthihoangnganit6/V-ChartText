# Cờ 'chưa chắc chắn' của bước 2 có bắt đúng số sai không?

Chỉ tính trên các biểu đồ mà **mọi** (chuỗi, mốc) mô hình trả về đều khớp tên với nhãn, để so được từng ô. **Sai đúng ô** = giá trị lệch > 5% so với nhãn ở cùng (chuỗi, mốc). **Vẫn 'có trong bảng'** = giá trị vẫn trùng (±5%) một số nào đó của nhãn, tức thước đo % số sai của mô tả coi là đúng.

| mô hình | luật | số biểu đồ | số ô bị cờ | sai đúng ô | vẫn 'có trong bảng' |
|---|---|---|---|---|---|
| Qwen3-VL-2B-Instruct | R1 số mơ hồ 1.200 / 1,2 | 2 | 70 | 63 (90%) | 10 (14%) |
| Qwen3-VL-2B-Instruct | R5 tổng % vượt 100 | 4 | 36 | 27 (75%) | 26 (72%) |
| Qwen3-VL-2B-Instruct | R9 trùng số giữa chuỗi | 3 | 28 | 20 (71%) | 28 (100%) |
| Qwen3-VL-2B-Instruct | R4 lệch bậc ×10/×100 | 2 | 3 | 2 (67%) | 1 (33%) |
| Qwen3-VL-2B-Instruct | R2 một ô hai giá trị | 1 | 1 | 0 (0%) | 1 (100%) |
| Qwen3-VL-2B-Instruct | *(không bị cờ, để đối chiếu)* | 70 | 819 | 220 (27%) | |
| Qwen3-VL-2B-Instruct | *(số biểu đồ khớp tên được dùng)* | 75 | | | |
| Vintern-1B-v3_5 | R9 trùng số giữa chuỗi | 5 | 62 | 41 (66%) | 62 (100%) |
| Vintern-1B-v3_5 | R2 một ô hai giá trị | 5 | 10 | 6 (60%) | 10 (100%) |
| Vintern-1B-v3_5 | R4 lệch bậc ×10/×100 | 3 | 3 | 3 (100%) | 2 (67%) |
| Vintern-1B-v3_5 | *(không bị cờ, để đối chiếu)* | 68 | 403 | 206 (51%) | |
| Vintern-1B-v3_5 | *(số biểu đồ khớp tên được dùng)* | 70 | | | |

Cách đọc: một luật có ích khi tỉ lệ 'sai đúng ô' của các ô bị cờ cao hơn nhiều so với dòng 'không bị cờ'.
Ô bị R9 gắn cờ hầu như vẫn 'có trong bảng' (là số của chuỗi bên cạnh), nên % số sai của mô tả không thấy lỗi gán nhầm chuỗi; cần thêm chỉ số chấm theo ô (chuỗi × mốc).
