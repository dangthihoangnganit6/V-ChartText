"""Bước 2: kiểm chứng bảng số liệu do VLM trích xuất (bước 1). Nguyên tắc: KHÔNG đoán số.

Đầu vào: dict JSON của bước 1 (prompt extract) hoặc nhãn gốc (để làm mức trần).
Đầu ra: bảng chuẩn hoá
  {chart_type, title, x_label, unit, unit2, series[], xs[], groups (biểu đồ tròn/miền),
   points: [{series, x, y, flags[]}], flags[] (mức biểu đồ)}
Điểm có flags khác rỗng = "chưa chắc chắn": bước 3 không đọc con số của điểm đó.

Luật:
  R1 số: đọc theo quy ước VN/Anh; số mơ hồ (1.200 / 1,200) chọn cách đọc gần trung vị chuỗi, không có căn cứ -> cờ
  R2 trùng: cùng (chuỗi, x) lặp lại cùng giá trị -> bỏ bản lặp; khác giá trị -> cờ "mâu thuẫn" cho cả hai
  R3 giá trị mẫu của prompt (123.4, 567.8, 1234, 5678) -> cờ
  R4 lệch bậc: giá trị gấp/kém >= 8 lần trung vị chuỗi và chia/nhân 10^k thì về gần trung vị -> cờ
  R5 tổng %: biểu đồ tròn (mỗi hình) / miền (mỗi mốc) / đơn vị % có cấu trúc 100%: tổng vượt 100 + 3 -> cờ cả nhóm;
     tổng thiếu (< 97, thường do sót thành phần, số còn lại vẫn đúng) -> chỉ cờ mức biểu đồ
  R6 thiếu ô: biểu đồ nhiều chuỗi mà một chuỗi thiếu mốc x -> cờ mức biểu đồ (không bịa ô thiếu)
  R7 chuỗi hằng: >= 4 mốc cùng một giá trị trong khi chuỗi khác thay đổi -> cờ mức biểu đồ (dấu hiệu chép/lặp)
  R8 loại biểu đồ ngoài tập cho phép / đơn vị trống / tiêu đề mẫu -> sửa nhẹ hoặc cờ mức biểu đồ
     (R8b: nhãn trục hoành chỉ là 1..N -> cờ mức biểu đồ; đơn vị / tên trục là chữ mẫu -> bỏ)
  R9 hai chuỗi trùng số ở >= 3 mốc (và >= 30% số mốc chung) -> cờ các ô trùng (nghi gán nhầm số giữa chuỗi)
"""
import math
import re
import statistics
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))
from vn_number import parse_pred  # noqa: E402

VALID = {"bar", "line", "pie", "combo", "area", "other"}
PLACEHOLDER_VALUES = {123.4, 567.8, 1234.0, 5678.0}
PLACEHOLDER_TITLES = {"pie chart", "bar chart", "line chart", "biểu đồ", "dữ liệu biểu đồ", "tiêu đề", "...",
                      "chart", "title", "tên biểu đồ"}
PCT_TOL = 3.0
UNIT_FIX = {"ti": "tỉ", "ty": "tỷ", "nghin": "nghìn", "ngàn": "nghìn", "trieu": "triệu"}
# chữ mẫu mô hình hay điền khi không đọc được đơn vị / tên trục (không phải thông tin trên ảnh)
PLACEHOLDER_UNITS = {"đơn vị", "đơn vị đo", "đơn vị tính", "unit", "units", "giá trị", "value", "values", "số liệu", "y"}
PLACEHOLDER_XLABELS = {"thứ tự", "stt", "số thứ tự", "x", "nhãn", "label", "category", "categories", "danh mục",
                       "trục x", "trục hoành", "hạng mục"}


def nfc(s):
    return unicodedata.normalize("NFC", str(s)).strip() if s is not None else ""


def _clean_label(s):
    s = nfc(s)
    return None if s.lower() in ("", "null", "none", "...", "-") else s


def _num(raw):
    """-> (giá trị, các cách đọc khác) hoặc (None, ())."""
    if isinstance(raw, bool) or raw is None:
        return None, ()
    if isinstance(raw, list):
        raw = raw[0] if raw else None
        if raw is None:
            return None, ()
    try:
        v, kind = parse_pred(raw)
    except (ValueError, TypeError):
        m = re.search(r"[-−]?\d[\d.,]*", str(raw))
        if not m:
            return None, ()
        try:
            v, kind = parse_pred(m.group(0))
        except ValueError:
            return None, ()
    if kind == "ambiguous":
        t = str(raw).strip()
        alt = float(t.replace(",", ".")) if "," in t else float(t)
        return v, (alt,)
    return v, ()


def from_pred(pred):
    """dict của prompt extract -> bảng thô."""
    pred = pred or {}
    ya = pred.get("y_axis") if isinstance(pred.get("y_axis"), dict) else {}
    y2 = pred.get("y2_axis") if isinstance(pred.get("y2_axis"), dict) else {}
    xa = pred.get("x_axis") if isinstance(pred.get("x_axis"), dict) else {}
    pts = []
    for d in pred.get("data") or []:
        if isinstance(d, dict):
            pts.append({"series": d.get("series"), "x": d.get("x"), "raw": d.get("y"), "axis": d.get("axis")})
    return {"chart_type": pred.get("chart_type"), "title": pred.get("title"), "x_label": xa.get("label"),
            "unit": ya.get("unit"), "unit_label": ya.get("label"), "unit2": y2.get("unit"), "points": pts}


def from_gold(rec):
    """nhãn gốc -> bảng thô (nhánh C: mức trần, bước 1 hoàn hảo)."""
    return {"chart_type": rec["chart_type"], "title": rec.get("title"),
            "x_label": (rec.get("x_axis") or {}).get("label"), "unit": (rec.get("y_axis") or {}).get("unit"),
            "unit_label": (rec.get("y_axis") or {}).get("label"), "unit2": (rec.get("y2_axis") or {}).get("unit"),
            "points": [{"series": d["series"], "x": d["x"], "raw": d["y"], "axis": d.get("axis")} for d in rec["data"]]}


def verify(raw):
    flags = []
    # R8: loại biểu đồ
    ct = nfc(raw.get("chart_type")).lower()
    if ct not in VALID:
        if "bar" in ct and "line" in ct:
            ct = "combo"
        else:
            ct = next((t for t in VALID if t in ct), "other")
        flags.append("loại biểu đồ không hợp lệ, đã quy về " + ct)
    title = _clean_label(raw.get("title"))
    if title and title.lower() in PLACEHOLDER_TITLES:
        flags.append("tiêu đề là chữ mẫu, bỏ")
        title = None
    if title and title.isupper():
        title = title[0] + title[1:].lower()
    unit = _clean_label(raw.get("unit"))
    if not unit:
        m = re.search(r"\(([^)]+)\)", nfc(raw.get("unit_label")))
        unit = m.group(1).strip() if m else None
    if unit:
        unit = unit.strip().strip("()[]").strip() or None
    if unit:   # mô hình hay bỏ dấu: "Ti USD" -> "Tỉ USD"
        unit = " ".join(UNIT_FIX.get(w.lower(), w) for w in unit.split())
    if unit and unit.lower() in PLACEHOLDER_UNITS:
        flags.append(f"đơn vị '{unit}' là chữ mẫu, bỏ")
        unit = None
    if not unit and ct == "pie":
        unit = "%"
    if not unit:
        flags.append("không rõ đơn vị")
    unit2 = _clean_label(raw.get("unit2"))
    if unit2 and (unit2.lower() in PLACEHOLDER_UNITS or (unit and unit2.lower() == unit.lower())):
        unit2 = None
    x_label = _clean_label(raw.get("x_label"))
    if x_label and x_label.lower() in PLACEHOLDER_XLABELS:
        x_label = None

    # R1, R3: đọc số
    pts = []
    for p in raw["points"]:
        s, x = _clean_label(p["series"]), _clean_label(p["x"])
        if isinstance(p["series"], (int, float)):
            s = nfc(p["series"])
        if isinstance(p["x"], (int, float)):
            x = nfc(int(p["x"]) if float(p["x"]).is_integer() else p["x"])
        v, alts = _num(p["raw"])
        if v is None:
            continue
        if s is None and x is None:
            continue
        pts.append({"series": s, "x": x, "y": v, "alts": alts, "axis": p.get("axis"), "flags": []})
    n_dropped = len(raw["points"]) - len(pts)
    if n_dropped:
        flags.append(f"bỏ {n_dropped} điểm không đọc được số")
    # biểu đồ tròn / một chuỗi: x trống thì dùng tên chuỗi làm x
    for p in pts:
        if p["x"] is None:
            p["x"], p["series"] = p["series"], None
    names = {p["series"] for p in pts}
    single = len(names) <= 1
    for p in pts:
        if p["series"] is None:
            p["series"] = title or "Giá trị"
    by_series = {}
    for p in pts:
        by_series.setdefault(p["series"], []).append(p)
    for s, ps in by_series.items():
        sure = [abs(p["y"]) for p in ps if not p["alts"] and p["y"]]
        med = statistics.median(sure) if sure else None
        for p in ps:
            if p["alts"]:
                cands = [p["y"], *p["alts"]]
                if med:
                    p["y"] = min(cands, key=lambda c: abs(math.log10(max(abs(c), 1e-9)) - math.log10(med)))
                else:
                    p["flags"].append("số mơ hồ (1.200 hay 1,2?)")
            if p["y"] in PLACEHOLDER_VALUES:
                p["flags"].append("giá trị mẫu của prompt")

    # R2: trùng / mâu thuẫn
    seen, keep = {}, []
    for p in pts:
        k = (p["series"].lower(), str(p["x"]).lower())
        if k in seen:
            q = seen[k]
            if abs(q["y"] - p["y"]) > 1e-9:
                if "mâu thuẫn: một ô có hai giá trị" not in q["flags"]:
                    q["flags"].append("mâu thuẫn: một ô có hai giá trị")
            continue
        seen[k] = p
        keep.append(p)
    if len(keep) < len(pts):
        flags.append(f"bỏ {len(pts) - len(keep)} điểm lặp")
    pts = keep
    by_series = {}
    for p in pts:
        by_series.setdefault(p["series"], []).append(p)

    # R4: lệch bậc trong chuỗi
    # so với các điểm kề bên (không so trung vị: chuỗi tăng trưởng thật có thể gấp hàng chục lần sau nhiều năm)
    for s, ps in by_series.items():
        if len(ps) < 3:
            continue
        for i, p in enumerate(ps):
            v = abs(p["y"])
            nb = [abs(q["y"]) for q in ps[max(0, i - 1):i] + ps[i + 1:i + 2] if q["y"]]
            if not v or not nb:
                continue
            if all(v / n >= 8 or n / v >= 8 for n in nb):
                ref = statistics.median(nb)
                if any(abs(v * f - ref) / ref < 0.5 for f in (10, 100, 1000, 0.1, 0.01, 0.001)):
                    p["flags"].append("nghi đọc lệch bậc (x10/x100/x1000)")

    # R7: chuỗi hằng
    if len(by_series) > 1:
        for s, ps in by_series.items():
            if len(ps) >= 4 and len({p["y"] for p in ps}) == 1:   # đo trên 200 ảnh: 100% điểm bị cờ vẫn đúng
                flags.append(f"chuỗi '{s}' không đổi qua {len(ps)} mốc, cần kiểm tra")

    # R9: hai chuỗi trùng số ở nhiều mốc -> mô hình đọc số thành một dãy rồi chia nhầm cho các chuỗi
    #     (vd biểu đồ cột ghép bar_075: tháng 6-10 hai chuỗi giống hệt nhau). Gắn cờ các ô trùng.
    names_ = list(by_series)
    for i, s1 in enumerate(names_):
        for s2 in names_[i + 1:]:
            m1 = {str(p["x"]): p for p in by_series[s1]}
            m2 = {str(p["x"]): p for p in by_series[s2]}
            common = [x for x in m1 if x in m2]
            same = [x for x in common if m1[x]["y"] == m2[x]["y"] and m1[x]["y"] != 0]
            if len(same) >= 3 and len(same) >= 0.3 * len(common):
                for x in same:
                    for p, other in ((m1[x], s2), (m2[x], s1)):
                        p["flags"].append(f"trùng số với chuỗi '{other}' ở cùng mốc, nghi đọc nhầm chuỗi")
                flags.append(f"'{s1}' và '{s2}' trùng số ở {len(same)}/{len(common)} mốc, nghi gán nhầm số giữa các chuỗi")

    xs = list(dict.fromkeys(p["x"] for p in pts))
    series = list(by_series)
    # mỗi "chuỗi" chỉ có 1 điểm: mô hình đã tách từng cột thành một chuỗi -> gộp thành 1 chuỗi
    if len(series) > 1 and all(len(v) == 1 for v in by_series.values()) and ct != "pie":
        one = title or "Giá trị"
        for p in pts:
            if len(xs) == 1:
                p["x"] = p["series"]
            p["series"] = one
        flags.append("gộp các chuỗi một điểm thành một chuỗi")
        by_series = {one: pts}
        xs = list(dict.fromkeys(p["x"] for p in pts))
        series = [one]
        single = True

    # R5: tổng 100%
    groups, group_key = None, None
    if ct in ("pie", "area") or (unit == "%" and len(series) > 1):
        best = None
        for key in ("series", "x"):
            g = {}
            for p in pts:
                g.setdefault(p[key], []).append(p)
            if len(g) == len(pts):          # mỗi nhóm 1 điểm -> không phải nhóm 100%
                continue
            dev = statistics.mean(abs(sum(q["y"] for q in v) - 100) for v in g.values())
            if best is None or dev < best[0]:
                best = (dev, key, g)
        if ct == "pie" and best is None and pts:   # một hình tròn, mỗi lát một chuỗi
            best = (abs(sum(p["y"] for p in pts) - 100), None, {"": pts})
        if best and (ct in ("pie", "area") or best[0] <= PCT_TOL):
            _, group_key, g = best
            groups = {}
            for name, v in g.items():
                tot = sum(q["y"] for q in v)
                groups[name] = round(tot, 3)
                if unit == "%" and tot > 100 + PCT_TOL:      # vượt 100%: chắc chắn có số sai
                    for q in v:
                        q["flags"].append(f"tổng nhóm '{name}' = {round(tot, 1)}, vượt 100")
                elif unit == "%" and tot < 100 - PCT_TOL:    # thiếu: thường do sót thành phần, số còn lại vẫn đúng
                    flags.append(f"nhóm '{name}' chỉ cộng được {round(tot, 1)}%, có thể thiếu thành phần")

    # R8b: nhãn trục hoành chỉ là 1, 2, ..., N ở biểu đồ không phải đường -> nghi mô hình đánh số thay vì chép nhãn
    if ct not in ("line", "area") and len(xs) >= 2 and [str(x) for x in xs] == [str(i) for i in range(1, len(xs) + 1)]:
        flags.append("nhãn trục hoành chỉ là số thứ tự 1..N, có thể chưa chép đúng nhãn trên ảnh")

    # R6: thiếu ô
    if len(series) > 1 and group_key != "series":
        missing = sum(len(xs) - len({p["x"] for p in ps}) for ps in by_series.values())
        if missing:
            flags.append(f"thiếu {missing} ô (chuỗi không đủ mốc)")

    for p in pts:
        p.pop("alts", None)
    return {"chart_type": ct, "title": title, "x_label": x_label, "unit": unit,
            "unit2": unit2, "single": single, "series": series, "xs": xs, "group_key": group_key,
            "groups": groups, "points": pts, "flags": flags,
            "n_uncertain": sum(bool(p["flags"]) for p in pts)}
