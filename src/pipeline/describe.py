"""Bước 3: sinh mô tả 3 cấp CHỈ từ bảng đã kiểm chứng (bước 2), bằng mẫu câu.

  nghe_5s   : loại biểu đồ, chủ đề, phạm vi, một ý chính
  nghe_30s  : số liệu chính của từng chuỗi / từng hình tròn
  dien_giai : so sánh giữa các chuỗi, chuyển dịch cơ cấu, xu hướng

Nguyên tắc chống lỗi số liệu:
  - mọi con số viết ra đều lấy nguyên từ bảng; không tính tổng, hiệu, phần trăm thay đổi bằng chữ số
    (tỉ lệ thay đổi chỉ diễn đạt bằng lời: "gấp khoảng hai lần");
  - điểm bị gắn cờ "chưa chắc chắn" không đọc ra số (uncertain="omit") hoặc đọc kèm "khoảng" (uncertain="hedge");
  - không suy diễn nguyên nhân kinh tế - xã hội.
"""
import re

from vn import fmt, fmt_unit, read_int

TYPE_NAME = {"bar": "Biểu đồ cột", "line": "Biểu đồ đường", "pie": "Biểu đồ tròn", "area": "Biểu đồ miền",
             "combo": "Biểu đồ kết hợp cột và đường", "other": "Biểu đồ"}
NUM_WORDS = {1: "một", 2: "hai", 3: "ba", 4: "bốn", 5: "năm", 6: "sáu", 7: "bảy", 8: "tám", 9: "chín", 10: "mười"}
MAX_SERIES = 4
MAX_LIST = 7


def _xn(t, x):
    """Tên mốc để đọc: '3' -> 'tháng 3' nếu trục x ghi 'Tháng'; năm giữ nguyên."""
    xs = str(x).strip()
    xl = (t["x_label"] or "").strip().lower()
    if re.fullmatch(r"\d{1,2}", xs) and xl and len(xl) <= 12 and not xl.startswith("năm"):
        return f"{xl} {xs}"
    return xs


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


def _cnt(n):
    """Số đếm viết bằng chữ (không lẫn với số liệu của biểu đồ)."""
    return read_int(n)


def _head(t):
    """'Biểu đồ cột thể hiện ...' ; bỏ chữ 'Biểu đồ (thể hiện)' lặp ở đầu tiêu đề."""
    name = TYPE_NAME[t["chart_type"]]
    title = (t["title"] or "").strip().rstrip(".")
    if not title:
        return name
    core = re.sub(r"^(biểu đồ|bieu do)\s*(miền|cột|đường|tròn|kết hợp)?\s*(thể hiện|thế hiện|về|biểu diễn|:)?\s*",
                  "", title, flags=re.I).strip()
    if not core:
        return name
    return f"{name} thể hiện {core[0].lower() + core[1:] if not core[:2].isupper() else core}"


def _is_time(xs):
    hits = sum(bool(re.fullmatch(r"(năm\s*)?\d{4}|\d{1,2}/\d{1,2}|t?\d{1,2}|tháng \d{1,2}|[ivx]{1,4}|quý.*",
                                 str(x).strip().lower())) for x in xs)
    return len(xs) >= 3 and hits >= 0.7 * len(xs)


def _ratio_words(a, b):
    """Diễn đạt b so với a bằng lời, không sinh chữ số mới."""
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    r = b / a
    if 0.97 <= r <= 1.03:
        return "gần như không đổi"
    if r >= 1.9:
        n = round(r)
        word = NUM_WORDS.get(n)
        return f"gấp khoảng {word} lần" if word else "gấp nhiều lần"
    if r >= 1.4:
        return "tăng mạnh"
    if r > 1:
        return "tăng nhẹ" if r < 1.15 else "tăng"
    if r <= 0.55:
        return "giảm mạnh, còn khoảng một nửa trở xuống" if r > 0.3 else "giảm rất mạnh"
    return "giảm nhẹ" if r > 0.87 else "giảm"


class Writer:
    def __init__(self, t, uncertain="omit"):
        self.t, self.mode = t, uncertain
        self.omitted = 0

    def val(self, p, unit=None):
        unit = self.t["unit"] if unit is None else unit
        if p["flags"]:
            if self.mode == "omit":
                self.omitted += 1
                return "(chưa xác định)"
            return "khoảng " + fmt_unit(p["y"], unit)
        return fmt_unit(p["y"], unit)

    def sure(self, ps):
        return [p for p in ps if not p["flags"]]


def _series_points(t):
    out = {}
    for p in t["points"]:
        out.setdefault(p["series"], []).append(p)
    return out


def _x_word(t):
    xl = (t["x_label"] or "").lower()
    return xl if xl and len(xl) < 20 else "mốc"


def _unit_of(t, s, ps):
    if not t["unit2"]:
        return t["unit"]
    ax = {p.get("axis") for p in ps}
    if ax == {"y2"}:
        return t["unit2"]
    if ax == {"y"}:
        return t["unit"]
    return ""     # biểu đồ 2 trục mà không biết chuỗi thuộc trục nào: không gắn đơn vị sai


def describe(t, uncertain="omit"):
    w = Writer(t, uncertain)
    ct, title = t["chart_type"], t["title"]
    if not t["points"]:
        msg = (_head(t) +
               ". Không trích xuất được số liệu đáng tin cậy từ ảnh, nên không đọc số.")
        return {"nghe_5s": msg, "nghe_30s": msg, "dien_giai": msg, "omitted": 0}
    if ct == "pie" or (t["groups"] and ct == "area"):
        return _describe_parts(t, w)
    return _describe_series(t, w)


# ------------------------------------------------------------------ chuỗi theo trục x (cột, đường, kết hợp)
def _describe_series(t, w):
    ct, title, xs = t["chart_type"], t["title"], t["xs"]
    sp = _series_points(t)
    names = list(sp)
    time = _is_time(xs)
    head = _head(t)
    if t["unit2"]:
        unit_txt = f"Đơn vị: {t['unit']} và {t['unit2']}."
    else:
        unit_txt = f"Đơn vị: {t['unit']}." if t["unit"] else "Không rõ đơn vị."
    rng = f"từ {_xn(t, xs[0])} đến {_xn(t, xs[-1])}" if time and len(xs) > 1 else f"gồm {_cnt(len(xs))} {_x_word(t)}"
    if len(names) > 1:
        lst = ", ".join(names[:MAX_SERIES]) + (f" và {_cnt(len(names) - MAX_SERIES)} chuỗi khác" if len(names) > MAX_SERIES else "")
        intro = f"{head}. Có {_cnt(len(names))} chuỗi số liệu: {lst}; {rng}. {unit_txt}"
    else:
        intro = f"{head}, {rng}. {unit_txt}"

    # ý chính cho bản 5 giây
    main = names[0]
    ps = sp[main]
    sure = w.sure(ps)
    key = ""
    if time and len(sure) >= 2:
        trend = _ratio_words(sure[0]["y"], sure[-1]["y"])
        if trend:
            key = f" Nhìn chung, {main.lower() if len(names) > 1 else 'giá trị'} {trend} trong giai đoạn này."
    elif sure:
        top = max(sure, key=lambda p: p["y"])
        key = f" Lớn nhất là {top['x']}."
    l5 = intro + key

    # bản 30 giây: từng chuỗi
    body = []
    for s in names[:MAX_SERIES]:
        ps = sp[s]
        unit = _unit_of(t, s, ps)
        sure = w.sure(ps)
        lead = f"{s}: " if len(names) > 1 else ""
        if time:
            first, last = ps[0], ps[-1]
            txt = (f"năm {first['x']} là {w.val(first, unit)}, đến {_xn(t, last['x'])} là {w.val(last, unit)}"
                   if re.fullmatch(r"\d{4}", str(first["x"]).strip()) else
                   f"{_xn(t, first['x'])} là {w.val(first, unit)}, đến {_xn(t, last['x'])} là {w.val(last, unit)}")
            if len(sure) >= 3:
                hi, lo = max(sure, key=lambda p: p["y"]), min(sure, key=lambda p: p["y"])
                if hi not in (first, last):
                    txt += f"; cao nhất {w.val(hi, unit)} vào {_xn(t, hi['x'])}"
                if lo not in (first, last):
                    txt += f"; thấp nhất {w.val(lo, unit)} vào {_xn(t, lo['x'])}"
            txt = lead + (txt if lead else _cap(txt))
        else:
            if len(ps) <= MAX_LIST:
                txt = lead + "; ".join(f"{p['x']}: {w.val(p, unit)}" for p in ps)
            else:
                srt = sorted(sure, key=lambda p: -p["y"])
                txt = lead + (f"cao nhất là {srt[0]['x']}: {w.val(srt[0], unit)}, thấp nhất là "
                              f"{srt[-1]['x']}: {w.val(srt[-1], unit)}" if srt else "các giá trị chưa xác định")
        body.append(txt + ".")
    if len(names) > MAX_SERIES:
        body.append(f"Còn {_cnt(len(names) - MAX_SERIES)} chuỗi khác không đọc chi tiết.")
    l30 = intro + " " + " ".join(body)

    # diễn giải
    ins = []
    if len(names) > 1:
        last_x = xs[-1]
        at_last = [p for s in names for p in sp[s] if p["x"] == last_x and not p["flags"]]
        same_unit = not t["unit2"]
        if same_unit and len(at_last) >= 2:
            hi, lo = max(at_last, key=lambda p: p["y"]), min(at_last, key=lambda p: p["y"])
            ins.append(f"Tại {last_x}, {hi['series']} lớn nhất, {lo['series']} nhỏ nhất.")
        if time:
            moves = []
            for s in names:
                su = w.sure(sp[s])
                if len(su) >= 2 and su[0]["y"] > 0 and _ratio_words(su[0]["y"], su[-1]["y"]):
                    moves.append((su[-1]["y"] / su[0]["y"], s, _ratio_words(su[0]["y"], su[-1]["y"])))
            if len(moves) >= 2:
                moves.sort()
                ins.append(f"So với đầu kỳ, {moves[-1][1]} {moves[-1][2]}, còn {moves[0][1]} {moves[0][2]}.")
    elif time:
        su = w.sure(sp[main])
        if len(su) >= 3:
            ups = sum(b["y"] > a["y"] for a, b in zip(su, su[1:]))
            downs = sum(b["y"] < a["y"] for a, b in zip(su, su[1:]))
            if ups and not downs:
                ins.append("Giá trị tăng liên tục qua các mốc.")
            elif downs and not ups:
                ins.append("Giá trị giảm liên tục qua các mốc.")
            else:
                ins.append("Giá trị có biến động, không tăng hoặc giảm liên tục.")
    else:
        su = w.sure(sp[main])
        if len(su) >= 2:
            srt = sorted(su, key=lambda p: -p["y"])
            ins.append(f"Xếp từ cao xuống thấp: {', '.join(str(p['x']) for p in srt[:MAX_LIST])}.")
    if t["unit2"]:
        ins.append("Biểu đồ có hai trục tung với hai đơn vị khác nhau, cần đọc mỗi chuỗi theo trục của nó.")
    l_dg = l30 + " " + " ".join(ins) + _caveat(t, w)
    return {"nghe_5s": l5, "nghe_30s": l30 + _caveat(t, w), "dien_giai": l_dg.strip(), "omitted": w.omitted}


# ------------------------------------------------------------------ cơ cấu (tròn, miền)
def _describe_parts(t, w):
    ct, title = t["chart_type"], t["title"]
    gk = t["group_key"]
    pts = t["points"]
    other = "x" if gk == "series" else "series"
    groups = {}
    for p in pts:
        groups.setdefault(p[gk] if gk else "", []).append(p)
    gnames = list(groups)
    head = _head(t)
    if ct == "pie":
        intro = head + (f", gồm {_cnt(len(gnames))} hình tròn: {', '.join(map(str, gnames))}." if len(gnames) > 1 else ".")
    else:
        intro = head + (f", thể hiện cơ cấu từ {gnames[0]} đến {gnames[-1]}." if len(gnames) > 1 else ".")
    parts = list(dict.fromkeys(p[other] for p in pts))
    intro += f" Các thành phần: {', '.join(map(str, parts[:8]))}" + (" và các thành phần khác." if len(parts) > 8 else ".")
    unit = t["unit"] or "%"
    intro += f" Đơn vị: {unit}."   # luôn nêu đơn vị, kể cả khi số bị bỏ vì chưa xác minh

    g0 = groups[gnames[0]]
    s0 = w.sure(g0)
    key = ""
    if s0:
        top = max(s0, key=lambda p: p["y"])
        when = f" ({gnames[0]})" if len(gnames) > 1 and gnames[0] else ""
        key = f" Lớn nhất{when} là {top[other]}."
    l5 = intro + key

    body = []
    show = gnames if ct == "pie" else ([gnames[0], gnames[-1]] if len(gnames) > 1 else gnames)
    for g in show:
        ps = sorted(groups[g], key=lambda p: -p["y"])
        lead = (f"Năm {g}: " if re.fullmatch(r"\d{4}", str(g).strip()) else f"{g}: ") if g else ""
        body.append(lead + "; ".join(f"{p[other]}: {w.val(p, unit)}" for p in ps[:MAX_LIST]) + ".")
    l30 = intro + " " + " ".join(body)

    ins = []
    if len(gnames) >= 2:
        a, b = groups[gnames[0]], groups[gnames[-1]]
        bmap = {p[other]: p for p in b}
        ch = []
        for p in a:
            q = bmap.get(p[other])
            if q and not p["flags"] and not q["flags"]:
                ch.append((q["y"] - p["y"], p, q))
        if ch:
            ch.sort(key=lambda c: c[0])
            up, down = ch[-1], ch[0]
            if up[0] > 0.05:
                ins.append(f"Từ {gnames[0]} đến {gnames[-1]}, tỉ trọng {up[1][other]} tăng từ "
                           f"{w.val(up[1], unit)} lên {w.val(up[2], unit)}.")
            if down[0] < -0.05:
                ins.append(f"Tỉ trọng {down[1][other]} giảm từ {w.val(down[1], unit)} xuống {w.val(down[2], unit)}.")
            if all(abs(c[0]) < 1 for c in ch):
                ins.append("Cơ cấu gần như không thay đổi.")
    elif s0 and len(s0) >= 2:
        srt = sorted(s0, key=lambda p: -p["y"])
        ins.append(f"{srt[0][other]} chiếm tỉ trọng lớn nhất, {srt[-1][other]} nhỏ nhất.")
    l_dg = l30 + " " + " ".join(ins) + _caveat(t, w)
    return {"nghe_5s": l5, "nghe_30s": l30 + _caveat(t, w), "dien_giai": l_dg.strip(), "omitted": w.omitted}


def _caveat(t, w):
    if w.omitted or t["n_uncertain"]:
        return " Một số giá trị chưa xác minh được từ ảnh nên không đọc ra."
    return ""
