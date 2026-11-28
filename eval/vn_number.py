"""Chuẩn hoá số kiểu Việt Nam / kiểu Anh.

Quy ước VN (SGK): dấu chấm phân cách nghìn, dấu phẩy thập phân: 1.200 = 1200 ; 12,5 = 12.5
Mô hình hay trả kiểu Anh: 1,200 = 1200 ; 12.5 = 12.5. Đây là nguồn lỗi chính cần đo.
"""
import re

NUM_RE = re.compile(r"(?<![\w.,])[-−]?\d+(?:[.,]\d+|\s\d{3}(?![\d.,]))*(?!\w)")
_VN_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+$")
_EN_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+$")


def parse_vn(s):
    """Nhãn gốc (y_raw) luôn theo quy ước VN."""
    s = str(s).strip().replace(" ", "").replace(" ", "").replace("−", "-")
    s = s.replace(".", "").replace(",", ".")
    return float(s)


def parse_pred(s):
    """Số do mô hình sinh ra: đoán quy ước. Trả (giá trị, kiểu) với kiểu in {vn, en, plain, ambiguous}."""
    if isinstance(s, (int, float)):
        return float(s), "plain"
    s = str(s).strip().replace(" ", "").replace("−", "-").rstrip("%").strip()
    s = re.sub(r"(?<=\d)\s(?=\d{3}\b)", "", s)  # 1 200 -> 1200
    neg = s.startswith("-")
    s = s.lstrip("-")
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):          # 1.200,5  -> VN
            v, kind = float(s.replace(".", "").replace(",", ".")), "vn"
        else:                                     # 1,200.5  -> EN
            v, kind = float(s.replace(",", "")), "en"
    elif "." in s:
        if _VN_THOUSANDS.match(s):                # 1.200 : VN nghìn (hoặc EN 1.2 -> mơ hồ)
            v, kind = float(s.replace(".", "")), "ambiguous"
        else:
            v, kind = float(s), "plain"
    elif "," in s:
        if _EN_THOUSANDS.match(s):                # 1,200 : EN nghìn (hoặc VN 1,2 -> mơ hồ)
            v, kind = float(s.replace(",", "")), "ambiguous"
        else:                                     # 12,5 -> VN thập phân
            v, kind = float(s.replace(",", ".")), "vn"
    else:
        v, kind = float(s), "plain"
    return (-v if neg else v), kind


def alt_readings(s):
    """Các cách đọc hợp lý của một chuỗi số. Chỉ số mơ hồ (1.200 / 1,200) mới có 2 cách đọc."""
    try:
        v, kind = parse_pred(s)
    except ValueError:
        return set()
    out = {v}
    if kind == "ambiguous":
        t = str(s).strip()
        out.add(float(t.replace(",", ".")) if "," in t else float(t))  # 1,200 -> 1.2 ; 1.200 -> 1.2
    return out


def find_numbers(text):
    return [m.group(0).strip() for m in NUM_RE.finditer(text)]


def rel_err(pred, gt):
    if gt == 0:
        return 0.0 if pred == 0 else 1.0
    return abs(pred - gt) / abs(gt)


SCALE_FACTORS = (1e-3, 1e3, 1e-1, 10, 1e-2, 1e2)


def is_scale_error(pred, gt, tol=0.05):
    """Sai do đọc nhầm dấu phân cách / bậc (vd 1.200 -> 1,2 hoặc 1200 -> 1.200.000)."""
    return gt != 0 and any(rel_err(pred, gt * f) <= tol for f in SCALE_FACTORS)
