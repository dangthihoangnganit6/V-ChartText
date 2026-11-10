"""Prompt baseline cho Mức 1. Giữ cố định suốt thí nghiệm; đổi prompt = đổi phiên bản (PROMPT_VERSION)."""

PROMPT_VERSION = "v1"

# P1 - Mô tả trực tiếp (baseline chính của đề tài: "cho VLM mô tả trực tiếp từ ảnh")
DESCRIBE = (
    "Bạn là trợ lý hỗ trợ học sinh khiếm thị. Hãy mô tả biểu đồ trong ảnh bằng tiếng Việt "
    "để học sinh nghe hiểu được. Nêu: loại biểu đồ, tiêu đề, các trục và đơn vị, chú giải, "
    "các số liệu chính, và xu hướng hoặc nhận xét nổi bật. Viết số theo cách viết Việt Nam "
    "(dấu chấm phân cách hàng nghìn, dấu phẩy thập phân). Không bịa số liệu không có trong ảnh."
)

# P2 - Trích xuất bảng (chart-to-table): đo tự động độ chính xác số liệu
EXTRACT_TABLE = (
    "Trích xuất toàn bộ thông tin của biểu đồ trong ảnh và chỉ trả về đúng một đối tượng JSON, "
    "không giải thích, theo mẫu:\n"
    '{"chart_type": "bar|line|pie|combo|area|other", "title": "...", '
    '"x_axis": {"label": "...", "unit": "..."}, "y_axis": {"label": "...", "unit": "..."}, '
    '"legend": ["..."], '
    '"data": [{"series": "...", "x": "...", "y": "<số đúng như ghi trên ảnh>"}]}\n'
    "Ghi giá trị y đúng nguyên văn như trên ảnh (giữ dấu chấm, dấu phẩy). "
    "Nếu trên ảnh không ghi số, hãy ước lượng và thêm \"estimated\": true cho điểm đó. "
    "Trường nào không có trong ảnh thì để null."
)

PROMPTS = {"describe": DESCRIBE, "extract": EXTRACT_TABLE}
