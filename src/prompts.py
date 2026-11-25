"""Prompt baseline cho Mức 1. Giữ cố định suốt thí nghiệm; đổi prompt = đổi phiên bản (PROMPT_VERSION)."""

PROMPT_VERSION = "v1"

# P1 - Mô tả trực tiếp (baseline chính của đề tài: "cho VLM mô tả trực tiếp từ ảnh")
DESCRIBE = (
    "Bạn là trợ lý hỗ trợ học sinh khiếm thị. Hãy mô tả biểu đồ trong ảnh bằng tiếng Việt "
    "để học sinh nghe hiểu được. Nêu: loại biểu đồ, tiêu đề, các trục và đơn vị, chú giải, "
    "các số liệu chính, và xu hướng hoặc nhận xét nổi bật. Viết số theo cách viết Việt Nam "
    "(dấu chấm phân cách hàng nghìn, dấu phẩy thập phân), hoàn toàn bằng tiếng Việt, giữ "
    "nguyên đơn vị như trên ảnh. Chỉ dùng thông tin có trên ảnh, không bịa số liệu không có trong ảnh. "
    "Giới hạn khoảng 150-200 từ."
)

# P2 - Trích xuất bảng (chart-to-table): đo tự động độ chính xác số liệu
EXTRACT_TABLE = (
    "Trích xuất toàn bộ thông tin của biểu đồ trong ảnh và chỉ trả về đúng một đối tượng JSON, "
    "không giải thích, theo mẫu:\n"
    '{"chart_type": "bar|line|pie|combo|area|other", "title": "...", '
    '"x_axis": {"label": "...", "unit": "..."}, "y_axis": {"label": "...", "unit": "..."}, '
    '"y2_axis": null, "legend": ["..."], '
    '"data": [{"series": "...", "x": "...", "y": "<số đúng như ghi trên ảnh>"}]}\n'
    "Ghi giá trị y đúng nguyên văn như trên ảnh (giữ dấu chấm, dấu phẩy). "
    "Nếu trên ảnh không ghi số, hãy ước lượng và thêm \"estimated\": true cho điểm đó. "
    "chart_type chỉ được nhận một trong các giá trị bar | line | pie | combo | area | other. "
    "title cần được chép nguyên văn; nếu ảnh không có tiêu đề thì để chuỗi rỗng \"\". "
    "label là tên đại lượng ghi trên trục, unit là đơn vị đo, tách riêng hai trường; ví dụ trục chỉ ghi "
    "\"Nghìn km\" thì \"y_axis\": {\"label\": null, \"unit\": \"Nghìn km\"}; trục ghi "
    "\"Tỉ trọng (%)\" thì {\"label\": \"Tỉ trọng\", \"unit\": \"%\"}. Biểu đồ tròn thì y_axis.unit là \"%\". "
    "Biểu đồ có hai trục tung (thường là combo): y_axis là trục trái, y2_axis là trục phải, "
    "cùng dạng {\"label\": \"...\", \"unit\": \"...\"}, và mỗi điểm trong data thêm "
    "\"axis\": \"y\" hoặc \"axis\": \"y2\"; biểu đồ một trục tung thì y2_axis là null. "
    "Mỗi phần tử data là một điểm. series là tên trong chú giải, không phải nhãn trục. "
    "Biểu đồ chỉ có một chuỗi số liệu (không có chú giải) thì legend là []. "
    "x là nhãn trên trục hoành. y giữ nguyên cách viết như trên ảnh. Phải liệt kê đủ mọi "
    "cặp series × x có trên biểu đồ. "
    "Trường nào không có trong ảnh thì để null."
)


PROMPTS = {"describe": DESCRIBE, "extract": EXTRACT_TABLE}

# ---------------------------------------------------------------- v2 (25/11): chỉ đổi prompt trích xuất
# Sửa các lỗi đo được ở v1 (eval/results/error_stats.md, phân tích pipeline):
#   - mất tiền tố bậc số của đơn vị ("Nghìn tấn" -> "tấn"): 28/41 trường hợp thiếu đơn vị ở pipeline B
#   - tự đặt tiêu đề khi ảnh không có (L7: 41%)
#   - tên lát / chuỗi viết khác ảnh (RA@5% biểu đồ tròn: chặt 0,17 so với nới 0,50)
#   - đảo series và x ở biểu đồ miền / tròn nhiều hình
EXTRACT_TABLE_V2 = EXTRACT_TABLE + (
    "\nQuy tắc bắt buộc:\n"
    "1. Đơn vị: chép NGUYÊN VĂN, giữ cả từ chỉ bậc số như nghìn, triệu, tỉ, tỷ. Ví dụ trục ghi "
    "\"Nghìn tấn\" thì unit là \"Nghìn tấn\", KHÔNG được viết \"tấn\"; trục ghi \"Tỉ USD\" thì unit là "
    "\"Tỉ USD\", KHÔNG được viết \"USD\". Nếu đơn vị nằm trong tiêu đề, ví dụ \"(Đơn vị: triệu người)\", "
    "thì lấy đơn vị đó. Giữ đủ dấu tiếng Việt.\n"
    "2. Tiêu đề: chỉ chép dòng tiêu đề thực sự in trên ảnh. Ảnh không có tiêu đề thì title là \"\"; "
    "KHÔNG tự đặt tiêu đề. Chữ như \"Hình 2\", \"Biểu đồ 1\" đứng một mình không phải tiêu đề.\n"
    "3. Tên chuỗi, tên lát, nhãn trục hoành: chép nguyên văn như trên ảnh, giữ dấu tiếng Việt, "
    "không dịch, không viết tắt, không đổi chữ hoa thường.\n"
    "4. Biểu đồ tròn: x là tên lát (thành phần), series là tên hình tròn ghi dưới hoặc trên hình "
    "(ví dụ \"Năm 2010\"); chỉ có một hình tròn thì series là \"\".\n"
    "5. Biểu đồ miền và biểu đồ có trục thời gian: x là các mốc trên trục hoành (thường là năm), "
    "series là các thành phần trong chú giải. Không đảo hai trường này."
)

PROMPTS_BY_VERSION = {
    "v1": PROMPTS,
    "v2": {"describe": DESCRIBE, "extract": EXTRACT_TABLE_V2},
}
