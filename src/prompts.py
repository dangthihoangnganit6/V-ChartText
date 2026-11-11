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
