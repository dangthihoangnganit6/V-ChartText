"""Hai bước phụ của demo, đều dùng lại mô hình đã nạp:

1) recheck: bước 1 thường sót tiêu đề (nhất là tiêu đề nằm DƯỚI hình), đơn vị, hoặc đánh số 1..N thay cho nhãn
   trục hoành. Khi bước 2 phát hiện các dấu hiệu đó, hỏi lại ảnh MỘT câu ngắn chỉ về các trường bị thiếu
   (không đọc lại số liệu), rồi kiểm chứng lại.
2) polish: viết lại câu mẫu cho tự nhiên hơn. Có rào chắn: mọi con số trong bản viết lại phải trùng khớp với bản gốc
   (không thêm, không bớt, không đổi), không có chữ Latinh lạ, độ dài hợp lý; sai thì giữ bản mẫu câu.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("src/pipeline", "eval"):
    sys.path.insert(0, str(ROOT / p))

from verify import PLACEHOLDER_UNITS, PLACEHOLDER_XLABELS  # noqa: E402
from vn_number import find_numbers  # noqa: E402

RECHECK_PROMPT = (
    "Nhìn kỹ biểu đồ trong ảnh và chỉ trả về đúng một đối tượng JSON, không giải thích:\n"
    '{"title": "...", "x_name": "...", "x_labels": ["..."], "unit": "..."}\n'
    "- title: chép nguyên văn dòng tiêu đề của biểu đồ. Tiêu đề có thể nằm phía TRÊN hoặc phía DƯỚI hình. "
    "Không có tiêu đề thì \"\". Không tự đặt tiêu đề.\n"
    "- x_name: tên trục hoành nếu ảnh có ghi (thường ở cuối trục hoành, trong ngoặc, ví dụ \"(Lớp)\", \"(Năm)\"); "
    "không có thì \"\".\n"
    "- x_labels: các nhãn ghi ngay dưới trục hoành, chép nguyên văn theo thứ tự từ trái sang phải "
    "(ví dụ \"5A\", \"Hà Nội\", \"2010\"). Không đánh số 1, 2, 3 nếu ảnh không ghi như vậy.\n"
    "- unit: đơn vị của trục tung, chép nguyên văn kể cả từ nghìn, triệu, tỉ; thường ghi ở đầu trục tung, "
    "ví dụ trục ghi \"(Học sinh)\" thì unit là \"Học sinh\". Không có thì \"\"."
)

POLISH_PROMPT = (
    "Bạn là biên tập viên viết lời đọc cho học sinh khiếm thị. Viết lại đoạn mô tả biểu đồ dưới đây bằng tiếng Việt "
    "tự nhiên, mạch lạc, câu ngắn, dễ nghe.\n"
    "Quy tắc bắt buộc:\n"
    "- Giữ NGUYÊN mọi con số và cách viết số (ví dụ 12,5 vẫn là 12,5), giữ đơn vị đi kèm.\n"
    "- Không thêm con số mới, không tự tính tổng hay hiệu, không thêm thông tin không có trong đoạn gốc, "
    "không suy đoán nguyên nhân.\n"
    "- Không dùng tiếng Anh, không gạch đầu dòng, không ký hiệu markdown.\n"
    "- Chỉ trả về đoạn văn đã viết lại.\n\n"
    "Đoạn gốc:\n"
)


def _json(text):
    t = re.sub(r"```(?:json)?", "", text or "")
    m = re.search(r"\{.*\}", t, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def suspects(t):
    """Các trường đáng hỏi lại, dựa trên bảng sau bước 2."""
    s = []
    if not t.get("title"):
        s.append("title")
    if not t.get("unit") and t["chart_type"] != "pie":
        s.append("unit")
    if any(f.startswith("nhãn trục hoành chỉ là số thứ tự") for f in t["flags"]):
        s.append("x_labels")
    return s


def apply_recheck(pred, t, answer):
    """Ghép câu trả lời hỏi lại vào pred (chỉ trường bị nghi). -> (pred mới, danh sách trường đã sửa)."""
    a = _json(answer) or {}
    pred = json.loads(json.dumps(pred))
    fixed = []
    want = suspects(t)
    if "title" in want and isinstance(a.get("title"), str) and a["title"].strip():
        pred["title"] = a["title"].strip()
        fixed.append("tiêu đề")
    unit = a.get("unit")
    if "unit" in want and isinstance(unit, str) and unit.strip("() ").strip() and \
            unit.strip("() ").lower() not in PLACEHOLDER_UNITS:
        pred.setdefault("y_axis", {})
        if not isinstance(pred["y_axis"], dict):
            pred["y_axis"] = {}
        pred["y_axis"]["unit"] = unit.strip("() ").strip()
        fixed.append("đơn vị")
    labels = a.get("x_labels")
    if "x_labels" in want and isinstance(labels, list):
        labels = [str(x).strip() for x in labels if str(x).strip()]
        old = list(dict.fromkeys(str(d.get("x")) for d in pred.get("data") or [] if isinstance(d, dict)))
        if len(labels) == len(old) and len(set(labels)) == len(labels):
            m = dict(zip(old, labels))
            for d in pred["data"]:
                if isinstance(d, dict):
                    d["x"] = m.get(str(d.get("x")), d.get("x"))
            fixed.append("nhãn trục hoành")
    xn = a.get("x_name")
    if fixed and isinstance(xn, str) and xn.strip("() ").strip() and xn.strip("() ").lower() not in PLACEHOLDER_XLABELS:
        xa = pred.get("x_axis") if isinstance(pred.get("x_axis"), dict) else {}
        if not xa.get("label") or str(xa.get("label")).lower() in PLACEHOLDER_XLABELS:
            xa["label"] = xn.strip("() ").strip()
            pred["x_axis"] = xa
    return pred, fixed


def row_prompt(t):
    """Đọc lại theo từng mốc: mỗi mốc ghi các số theo thứ tự chú giải. Khớp với cách mô hình đọc trái -> phải,
    nên tránh lỗi đọc thành một dãy số rồi chia nhầm cho các chuỗi."""
    series = ", ".join(f'"{s}"' for s in t["series"])
    xs = ", ".join(f'"{x}"' for x in t["xs"])
    return (
        f"Biểu đồ trong ảnh có {len(t['series'])} chuỗi số liệu theo thứ tự chú giải: {series}. "
        f"Các mốc trên trục hoành, từ trái sang phải: {xs}.\n"
        "Ở mỗi mốc có một nhóm cột (hoặc điểm) đứng cạnh nhau theo đúng thứ tự chú giải. Hãy đọc LẦN LƯỢT TỪNG MỐC "
        "từ trái sang phải; ở mỗi mốc ghi số trên đỉnh từng cột theo thứ tự chú giải.\n"
        "Chỉ trả về đúng một đối tượng JSON, không giải thích:\n"
        '{"rows": [{"x": "<mốc>", "y": ["<số của chuỗi 1>", "<số của chuỗi 2>"]}]}\n'
        "Ghi số đúng như trên ảnh. Số nào không đọc được thì để null. Phải có đủ mọi mốc, "
        "mỗi mốc đủ số lượng giá trị bằng số chuỗi."
    )


def need_rows(t):
    """Biểu đồ nhiều chuỗi bị nghi gán nhầm số giữa chuỗi hoặc thiếu ô -> nên đọc lại theo mốc."""
    if len(t["series"]) < 2 or t["chart_type"] == "pie" or t.get("group_key") == "series":
        return False
    return any(("trùng số ở" in f) or ("thiếu" in f and "ô" in f) for f in t["flags"])


def apply_rows(pred, t, answer):
    """-> pred mới (thay toàn bộ data bằng bản đọc theo mốc) hoặc None nếu bản đọc lại không đầy đủ."""
    a = _json(answer) or {}
    rows = a.get("rows")
    ns, xs = t["series"], [str(x) for x in t["xs"]]
    if not isinstance(rows, list) or len(rows) != len(xs):
        return None
    data = []
    for x, r in zip(xs, rows):
        ys = r.get("y") if isinstance(r, dict) else None
        if not isinstance(ys, list) or len(ys) != len(ns):
            return None
        data += [{"series": s, "x": x, "y": y} for s, y in zip(ns, ys) if y not in (None, "", "null")]
    pred = json.loads(json.dumps(pred))
    pred["data"] = data
    return pred


def _nums(s):
    return sorted(re.sub(r"\s", "", n) for n in find_numbers(s))


def check_polish(src, out):
    """-> (ok, lý do). Số trong bản viết lại phải trùng khớp (cả số lần xuất hiện) với bản gốc."""
    out = (out or "").strip().strip('"').strip()
    if not out:
        return False, "bản viết lại rỗng"
    if _nums(out) != _nums(src):
        return False, "bản viết lại làm thay đổi con số"
    n_src, n_out = len(src.split()), len(out.split())
    if not 0.5 * n_src <= n_out <= 1.6 * n_src + 10:
        return False, "độ dài bất thường"
    if re.search(r"[*#`]|^\s*[-•]", out, re.M):
        return False, "có ký hiệu markdown"
    if re.search(r"\b(the|and|of|chart|value|total|increase|decrease)\b", out, re.I):
        return False, "chen tiếng Anh"
    return True, ""


def polish(extractor, text):
    """-> (văn bản dùng để đọc, đã viết lại?, lý do nếu giữ bản gốc)."""
    out = extractor.generate(POLISH_PROMPT + text, max_new_tokens=512)
    out = re.sub(r"^(đoạn (văn )?(đã )?viết lại|bản viết lại)\s*:\s*", "", out.strip(), flags=re.I)
    ok, why = check_polish(text, out)
    return (out, True, "") if ok else (text, False, why)
