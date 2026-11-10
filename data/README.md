# Hướng dẫn gán nhãn V-ChartText (v1)

Mỗi biểu đồ = 1 ảnh trong `data/images/` + 1 file JSON cùng tên trong `data/labels/`.
Mẫu đầy đủ: `labels/example_dl_c01_001.json`. Kiểm tra trước khi đẩy lên: `python eval/validate_labels.py`.

## 1. Đặt tên và tạo khung nhãn
Không đặt tên tay. Chạy `python src/prepare_dataset.py --raw "raw_drive/Ảnh biểu đồ"`: script chép ảnh vào `data/images/`
với id theo loại (`bar_001`, `line_001`, `pie_001`, `combo_001`, `area_001`) và tạo file nhãn khung `"status": "todo"`.
Tên file gốc trên Drive nằm ở `source.original_file`. Gán xong một ảnh thì **xoá dòng `"status": "todo"`**.
Ảnh nên giữ đủ tiêu đề, chú giải, đơn vị; cạnh dài ≥ 800 px (script liệt kê ảnh nhỏ hơn).

## 2. Các trường
| Trường | Ghi gì |
|---|---|
| `source` | `type`: `sgk` / `sbt` / `on_thi` / `atlat` / `khac`; `book`, `page` hoặc `url`; giữ nguyên `original_file` |
| `annotator` | `ngan` / `nhi` / `giang` |
| `subject` | `dia_li` / `lich_su` / `khac` |
| `chart_type` | `bar` (cột, thanh), `line` (đường), `pie` (tròn), `combo` (cột + đường), `area` (miền), `other` |
| `title` | Chép nguyên văn tiêu đề trên ảnh |
| `x_axis`, `y_axis` | `label` và `unit` đúng như ảnh ghi; không có thì `null`. Biểu đồ 2 trục y: thêm `y2_axis` |
| `legend` | Danh sách tên chuỗi số liệu, đúng chính tả như chú giải |
| `data` | Mỗi điểm 1 dòng: `series`, `x`, `y` (số chuẩn), `y_raw` (chuỗi như trên ảnh) |
| `values_shown_on_chart` | `true` nếu ảnh có ghi số trên cột/điểm; `false` nếu phải đọc theo vạch chia |

## 3. Quy ước số (quan trọng nhất)
- `y_raw`: chép **đúng như trên ảnh**, theo kiểu Việt Nam: `1.200` (một nghìn hai trăm), `12,5` (mười hai phẩy năm).
- `y`: số chuẩn kiểu máy, dấu chấm thập phân, không phân cách nghìn: `1200`, `12.5`.
- Không đổi đơn vị: ảnh ghi "nghìn tấn" và cột ghi `1.200` thì `y = 1200`, `unit = "nghìn tấn"` (KHÔNG ghi 1200000 tấn).
- Ảnh không ghi số: đọc theo vạch chia, làm tròn đến nửa vạch nhỏ nhất, ghi `"estimated": true` cho điểm đó.
- Biểu đồ tròn: `x` = tên phần, `y` = phần trăm; nếu có nhiều vòng tròn (nhiều năm), `series` = năm.
- Biểu đồ kết hợp: mỗi chuỗi một `series`, thêm `"axis": "y"` hoặc `"axis": "y2"`.

## 4. Mô tả 3 cấp (chỉ cho tập con 60 mẫu, trường `descriptions`)
```json
"descriptions": {
  "nghe_5s":  "Biểu đồ cột về sản lượng lúa nước ta 2010–2021, nhìn chung tăng nhẹ.",
  "nghe_30s": "2–4 câu: loại biểu đồ, trục, đơn vị, giá trị lớn nhất/nhỏ nhất, xu hướng chính.",
  "dien_giai": "Đoạn đầy đủ cho học tập: so sánh, tính tốc độ tăng, nhận xét và giải thích như bài làm môn Địa lí."
}
```
Viết số trong mô tả theo kiểu Việt Nam và luôn kèm đơn vị.
