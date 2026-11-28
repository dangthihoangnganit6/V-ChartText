# Data card: V-ChartText v1 (đóng băng 20/11/2026)

Bộ dữ liệu biểu đồ học tập tiếng Việt dùng để đánh giá VLM trích xuất số liệu và mô tả biểu đồ cho học sinh khiếm thị
(đề tài Nhóm 7, môn Các vấn đề hiện đại CNTT). Mỗi biểu đồ gồm một ảnh `data/images/<id>.<đuôi>` và một nhãn
`data/labels/<id>.json`.

## 1. Quy mô

| | Số lượng |
|---|---|
| Ảnh đã thu thập (`manifest.csv`) | 215 |
| Ảnh đã xoá trước khi gán vì trùng ảnh khác (`bar_063`, `bar_069`) | 2 |
| File nhãn | 213 |
| Bị loại khỏi benchmark (`status = excluded`) | 13 |
| **Dùng để chấm điểm** | **200 biểu đồ, 2.230 điểm dữ liệu** |
| Trong đó: tập "sạch" (có in số trên hình và không trùng số liệu) | 160 |

Phân bố 200 biểu đồ dùng để chấm:

| Loại | Số biểu đồ | Số điểm dữ liệu | Ghi chú |
|---|---|---|---|
| `bar` (cột) | 72 | 749 | 28 cột đơn, 40 cột ghép, 3 cột chồng (`bar_mode`) |
| `pie` (tròn) | 42 | 267 | nhiều ảnh có 2-3 hình tròn (mỗi hình là một `series`) |
| `line` (đường) | 41 | 606 | |
| `area` (miền) | 24 | 346 | |
| `combo` (cột + đường) | 21 | 262 | 21 ảnh có trục tung thứ hai (`y2_axis`), tính cả 1 ảnh đường |

- 138/200 biểu đồ có từ 2 chuỗi số liệu trở lên; trung vị 9 điểm/biểu đồ, nhiều nhất 62.
- 89 biểu đồ đơn vị `%`; 42 biểu đồ có giá trị ≥ 1.000; 144 biểu đồ có số thập phân; 5 biểu đồ có giá trị âm.
- 47 ảnh không có tiêu đề (`title = ""`).
- Môn (`subject`): 168 `dia_li`, 32 `khac` (biểu đồ toán lớp 6, kinh doanh, giá vàng, ...). Môn được **đoán tự động bằng từ khoá**
  (`subject_guessed = true`), chưa ai duyệt. Chưa có ảnh nào được gán `lich_su`.
- Ảnh: 158 png, 27 jpg, 8 webp, 6 jpeg, 1 gif; cạnh ngang trung vị 886 px (350-2.760 px); 77 ảnh có cạnh dài < 800 px.

## 2. Nguồn
Ảnh lấy từ SGK Địa lí (chủ yếu bộ Kết nối tri thức), đề ôn thi THPT, sách Toán 6 và các trang báo kinh tế. Trường `source.type`,
`book`, `page` **chưa điền**; chỉ có `source.original_file` (tên file gốc trên Drive). Dùng cho mục đích học tập, repo để private,
không phân phối lại ảnh.

## 3. Quy trình gán nhãn
1. Ba người (Ngân: cột; Nhi: đường + 20 tròn; Giang: tròn còn lại, kết hợp, miền) gán bảng số liệu trên Google Sheet
   (tab `Data_Labeling`): tiêu đề, loại, đơn vị, trục hoành, categories, chuỗi, giá trị.
   Một phần nhãn của Giang do Claude soạn nháp từ ảnh gốc, sau đó Giang soát.
2. 5 ảnh mẫu (`area_001`, `bar_001`, `combo_001`, `line_001`, `pie_001`) gán tay trực tiếp bằng JSON, đầy đủ trường hơn.
3. Ngày 20/11 soát định dạng toàn bộ Sheet: sửa 12 dòng sai cấu trúc (số giá trị không khớp số mốc, đảo categories/series,
   gõ nhầm số, dấu `||` thừa), mỗi chỗ sửa có ghi `[20/11]` trong cột "Ghi chú nhãn".
4. Script `import_sheet.py` chuyển Sheet sang JSON; `python eval/validate_labels.py`: 0 lỗi.
5. Kiểm tra chéo: 41 ảnh (≈ 20%), mỗi người soát ảnh của người khác. Kết quả: 17/41 ảnh có ít nhất một chỗ bất đồng
   (41,5%), nhưng chỉ 13/485 điểm dữ liệu (2,7%); bất đồng chủ yếu ở ảnh không in số (ước lượng theo vạch) và tên chuỗi.
6. Ngày 24–25/11 soát lại **toàn bộ 200 nhãn** theo ảnh gốc (có script tự kiểm: tổng % khác 100, y ≠ y_raw, điểm trùng,
   chữ mẫu, chỗ lệch xa output mô hình): sửa khoảng 60 nhãn (giá trị gõ nhầm, sai tên chuỗi, ngược trục/đơn vị, chính tả),
   gắn cờ đủ 22 ảnh không ghi số, dựng lại 5 nhãn mẫu `*_001`.

> **`data/labels/*.json` là bản nhãn chuẩn** dùng để chấm điểm. `docs/Benchmark.xlsx` là bản xuất từ Sheet *trước* đợt soát
> 24–25/11, không dùng để chấm. File gán nhãn trung gian (Sheet CSV, Excel từng người, kết quả kiểm tra chéo, danh sách ô cần
> sửa trên Sheet) và script `import_sheet.py`, `cross_check.py` lưu ở repo cá nhân `rangha26/V-ChartText` (nhánh `dev`).

## 4. Quy ước
- `y` là số máy (dấu chấm thập phân); `y_raw` viết kiểu Việt Nam (dấu phẩy thập phân). Trên Sheet số luôn viết dấu chấm thập phân,
  không có dấu phân cách nghìn.
- Giữ nguyên chữ trên ảnh (tiêu đề, chú giải, đơn vị, kể cả "Tỉ"/"Tỷ", "thuỷ"/"thủy"). Lỗi in trên ảnh cũng giữ nguyên
  và ghi chú (vd `bar_052`: ảnh in 2141,74, nhiều khả năng đúng là 241,74).
- Biểu đồ hai trục: `y_axis` là đơn vị thứ nhất, `y2_axis` là đơn vị thứ hai (thứ tự như cột `unit` trên Sheet).
  Chưa ghi chuỗi nào thuộc trục nào (`axis` theo điểm) cho ảnh nhập từ Sheet.
- Ảnh có 2-3 hình tròn: mỗi hình là một `series` (thường là năm), lát cắt là `x`.

## 5. Ảnh bị loại và các cờ cần biết

**Bị loại (13):** `line_011`, `019`, `025`, `040`, `041`, `043`, `045`-`050` (12 biểu đồ đường không ghi số hoặc chưa có giá trị);
`bar_046` (cùng một ảnh với `bar_047`, khác đuôi file).

**Ảnh không ghi số, giá trị là ước lượng theo vạch chia (`values_shown_on_chart = false`, 22):** `area_009`, `area_013`, `bar_024`-`026`, `bar_029`, `bar_034`, `bar_050`, `bar_051`, `bar_056`, `bar_057`, `bar_059`-`061`, `bar_072`, `bar_073`, `combo_017`, `line_044`, `line_051`-`053`, `pie_035`. RA@5% trên các ảnh này đo khả năng ước lượng, không đo khả
năng đọc số, nên báo cáo tách riêng (cột `RA@5%_sach` trong `summary_models.csv`).

**Trùng số liệu với ảnh khác (`duplicate_of`, 18):** `area_011`, `area_014`, `area_018`, `area_023`, `bar_019`, `bar_020`,
`bar_036`, `bar_064`, `combo_005`, `combo_008`, `combo_018`, `line_027`, `line_033`, `line_036`, `line_037`, `line_039`, `pie_032`, `pie_034`.
Phần lớn là cùng bảng số liệu nhưng vẽ khác (màu, cỡ, có hoặc không tiêu đề), nên được giữ lại; kết quả báo cáo cả khi có và
khi bỏ các ảnh này.

## 6. Hạn chế
- Mỗi ảnh chỉ có một người gán; độ tin cậy nhãn dựa vào đợt kiểm tra chéo 20%.
- Có thể còn ảnh không in số nhưng chưa gắn cờ. Ai phát hiện thì sửa trực tiếp `values_shown_on_chart: false` trong file JSON.
- Lệch về Địa lí và về biểu đồ cột; chưa có biểu đồ Lịch sử.
- Chưa có mô tả 3 cấp viết tay làm tham chiếu; mô tả được chấm bằng cách so từng con số với bảng nhãn.

## 7. Kiểm tra
```bash
python eval/validate_labels.py      # kiểm định dạng mọi file nhãn
```
Sửa nhãn: sửa trực tiếp file JSON (giữ `y` và `y_raw` khớp nhau), rồi chạy lại lệnh trên và các lệnh chấm điểm trong `README_pipeline.md`.
