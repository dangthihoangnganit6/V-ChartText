"""Số kiểu Việt Nam: định dạng để viết (bước 3) và đọc thành chữ (bước 4)."""
import re

DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
SCALES = ["", " nghìn", " triệu", " tỷ"]


def fmt(v, max_dec=3):
    """12.5 -> '12,5' ; 4296 -> '4.296' ; 2010.0 -> '2.010'. Bỏ số 0 thừa sau dấu phẩy."""
    if v is None:
        return "?"
    neg = v < 0
    v = abs(v)
    s = f"{v:.{max_dec}f}".rstrip("0").rstrip(".")
    ip, _, dp = s.partition(".")
    ip = f"{int(ip):,}".replace(",", ".")
    out = ip + ("," + dp if dp else "")
    return ("-" if neg else "") + out


def fmt_unit(v, unit):
    s = fmt(v)
    if not unit:
        return s
    return s + "%" if unit.strip() == "%" else f"{s} {unit}"


# ------------------------------------------------------------------ đọc số
def _block(n, full):
    """Đọc số 0..999. full=True: đọc cả 'không trăm', 'linh' (khối không đứng đầu)."""
    h, t, u = n // 100, n // 10 % 10, n % 10
    w = []
    if h or full:
        w += [DIGITS[h], "trăm"]
    if t == 0:
        if u and (h or full):
            w.append("linh")
    elif t == 1:
        w.append("mười")
    else:
        w += [DIGITS[t], "mươi"]
    if u:
        if u == 1 and t >= 2:
            w.append("mốt")
        elif u == 5 and t >= 1:
            w.append("lăm")
        elif u == 4 and t >= 2:
            w.append("tư")
        else:
            w.append(DIGITS[u])
    return " ".join(w)


def read_int(n):
    if n == 0:
        return "không"
    if n < 0:
        return "âm " + read_int(-n)
    parts, i = [], 0
    while n:
        parts.append((n % 1000, i))
        n //= 1000
        i += 1
    if i > 4:                       # > 999 tỷ: đọc từng chữ số cho an toàn
        return " ".join(DIGITS[int(c)] for c in str(sum(b * 1000 ** k for b, k in parts)))
    words, top = [], len(parts) - 1
    for b, k in reversed(parts):
        if b == 0:
            continue
        words.append(_block(b, full=k != top) + SCALES[k])
    return " ".join(words)


def read_number(s):
    """'12,5' -> 'mười hai phẩy năm' ; '1.200' -> 'một nghìn hai trăm' ; '0,05' -> 'không phẩy không năm'."""
    s = s.strip()
    neg = s.startswith(("-", "−"))
    s = s.lstrip("-−")
    ip, _, dp = s.partition(",")
    ip = ip.replace(".", "")
    out = read_int(int(ip or 0))
    if dp:
        if dp.startswith("0") or len(dp) > 2:
            out += " phẩy " + " ".join(DIGITS[int(c)] for c in dp)
        else:
            out += " phẩy " + read_int(int(dp))
    return ("âm " if neg else "") + out


NUM_VN = re.compile(r"(?<![\w,.])[-−]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\w])|(?<![\w,.])[-−]?\d+(?:,\d+)?(?![\w])")
UNIT_WORDS = [("%", " phần trăm"), ("°C", " độ C"), ("km²", " ki-lô-mét vuông"), ("kWh", " ki-lô-oát giờ"),
              ("USD", " đô la Mỹ"), ("mm", " mi-li-mét"), ("km", " ki-lô-mét"), ("ha", " héc-ta"),
              ("tạ/ha", " tạ trên héc-ta")]


def to_speech(text):
    """Chuẩn hoá văn bản cho TTS: số -> chữ, đơn vị -> chữ, khoảng năm '2010 - 2018' -> 'từ ... đến ...'."""
    t = re.sub(r"(\d)\s*[-–—]\s*(\d)", r"\1 đến \2", text)
    t = t.replace("/", " trên ") if "tạ/ha" in t else t
    t = NUM_VN.sub(lambda m: read_number(m.group(0)), t)
    for a, b in UNIT_WORDS:
        t = re.sub(r"(?<=\w)\s*" + re.escape(a) + r"(?![\w])", b, t) if a == "%" else \
            re.sub(r"(?<![\w])" + re.escape(a) + r"(?![\w])", b.strip(), t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def sentences(text, max_words=25):
    """Tách câu ngắn cho người nghe: câu dài hơn max_words cắt ở dấu phẩy / chấm phẩy."""
    out = []
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        words = s.split()
        if len(words) <= max_words:
            out.append(s)
            continue
        cur = []
        for part in re.split(r"(?<=[;,])\s+", s):
            if cur and len(" ".join(cur + [part]).split()) > max_words:
                out.append(" ".join(cur).rstrip(",;") + ".")
                cur = []
            cur.append(part)
        if cur:
            out.append(" ".join(cur))
    return [s for s in out if s]


if __name__ == "__main__":
    for x in ["0", "5", "10", "15", "21", "24", "105", "1.200", "2010", "2.021", "12,5", "3,25", "0,05", "-4,5",
              "71.995,5", "1.000.000", "20.893,7"]:
        print(x, "->", read_number(x))
    print(to_speech("Năm 2010 đạt 12,5% và 7.666 nghìn ha; giai đoạn 2010 - 2018."))
