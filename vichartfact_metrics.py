"""
V-ChartText: Core Pipeline Logic, ViChartFact & Description Completeness Metrics
==============================================================================
Shared pure-Python module (no Gradio dependency) providing:
1. Vietnamese number normalization & structured chart validation (Step 2)
2. Grounded 3-level description generation (Step 3)
3. ViChartFact numerical faithfulness checking (vs Step-2 table & vs Ground Truth)
4. Pedagogical description completeness scoring across 4 dimensions (0-100%)
"""

import ast
import html
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd


CHART_TYPE_LABELS_VN = {
    "column": ["biểu đồ cột", "cột", "cột đơn", "cột ghép", "cột chồng"],
    "line": ["biểu đồ đường", "đường"],
    "pie": ["biểu đồ tròn", "tròn"],
    "area": ["biểu đồ miền", "miền"],
    "combo": ["biểu đồ kết hợp", "kết hợp"],
}

HALLUCINATED_CAUSE_PHRASES = [
    "do kinh tế phát triển",
    "do chính sách đổi mới",
    "do tác động covid",
    "do dịch covid",
    "do công nghiệp hóa",
    "do đô thị hóa",
    "nhờ chính sách",
    "nguyên nhân là do",
    "bởi vì chính sách",
]

VN_STOPWORDS = {
    "biểu", "đồ", "bảng", "hình", "số", "liệu", "thể", "hiện", "về", "của",
    "và", "các", "một", "những", "trong", "qua", "theo", "tại", "giai", "đoạn",
    "thời", "kì", "kỳ", "năm", "nước", "ta", "này", "đến", "từ", "cho", "với",
    "có", "là", "đơn", "vị", "tính", "không", "tên", "tiêu", "đề",
}


def normalize_text_nfc(text: Any) -> str:
    """Normalize Unicode string to NFC and strip outer whitespace."""
    if text is None:
        return ""
    try:
        if pd.isna(text):
            return ""
    except Exception:
        pass
    return unicodedata.normalize("NFC", str(text)).strip()


def normalize_chart_type(c_type_raw: str) -> str:
    """Map raw Vietnamese/English chart type labels into 5 canonical classes."""
    c = normalize_text_nfc(c_type_raw).lower()
    if "cột" in c or "column" in c or "bar" in c:
        return "column"
    if "đường" in c or "line" in c:
        return "line"
    if "tròn" in c or "pie" in c:
        return "pie"
    if "miền" in c or "area" in c:
        return "area"
    if "kết hợp" in c or "combo" in c or "combined" in c:
        return "combo"
    return "column"


def clean_vietnamese_number(num_str: Any) -> Optional[float]:
    """
    Parse Vietnamese-formatted numbers safely:
    - '1.200' -> 1200.0, '19.257' -> 19257.0
    - '12,5' -> 12.5, '0,8' -> 0.8
    Rejects malformed dictionary/JSON fragments containing multiple disjoint numbers.
    """
    if num_str is None:
        return None
    s = normalize_text_nfc(num_str)
    if not s or s.lower() in {
        "none", "null", "nan", "không có", "chưa chắc chắn", "[chưa chắc chắn]", ""
    }:
        return None
    if any(ch in s for ch in ("{", "}", ":")):
        return None

    s = re.sub(r"[^\d,\.\-]", "", s)
    if not s or s == "-":
        return None

    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) >= 1:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) >= 1:
            s = s.replace(".", "")

    try:
        return float(s)
    except ValueError:
        return None


def parse_semicolon_or_pipe(val_str: str) -> List[str]:
    """Split serialized list strings delimited by '||', '|', or ';'."""
    if not val_str or pd.isna(val_str):
        return []
    s = normalize_text_nfc(val_str)
    if not s:
        return []
    if "||" in s:
        return [c.strip() for c in s.split("||") if c.strip()]
    if "|" in s:
        return [c.strip() for c in s.split("|") if c.strip()]
    if ";" in s:
        return [c.strip() for c in s.split(";") if c.strip()]
    return [s]


def _extract_dict_values(values_raw: str) -> Optional[List[List[Optional[float]]]]:
    """
    Recover numeric lists when Step-1 VLM serialized dict/list syntax into `values`
    (e.g. "{'category': '2021', 'value': 2478} | ..." or nested series dicts).
    """
    s = normalize_text_nfc(values_raw)
    if "{" not in s:
        return None

    chunks = [ch.strip() for ch in s.split("||") if ch.strip()]
    parsed_series: List[List[Optional[float]]] = []

    for ch in chunks:
        # Case A: pipe-separated dicts inside one chunk
        sub_items = [it.strip() for it in ch.split("|") if it.strip()]
        nested_found = False
        flat_vals: List[Optional[float]] = []

        for item in sub_items:
            try:
                obj = ast.literal_eval(item)
            except Exception:
                obj = None

            if isinstance(obj, dict) and isinstance(obj.get("values"), list):
                nested_found = True
                inner_vals: List[Optional[float]] = []
                for entry in obj["values"]:
                    if isinstance(entry, dict) and "value" in entry:
                        inner_vals.append(clean_vietnamese_number(entry["value"]))
                    else:
                        inner_vals.append(clean_vietnamese_number(entry))
                parsed_series.append(inner_vals)
            elif isinstance(obj, dict) and "value" in obj:
                flat_vals.append(clean_vietnamese_number(obj["value"]))
            else:
                # Regex fallback for `'value': 123.4`
                m = re.search(r"['\"]?value['\"]?\s*:\s*([-+]?\d+(?:[.,]\d+)?)", item)
                if m:
                    flat_vals.append(clean_vietnamese_number(m.group(1)))
                else:
                    flat_vals.append(None)

        if not nested_found:
            parsed_series.append(flat_vals)

    return parsed_series if parsed_series else None


def validate_chart_data(data: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    """Validate extracted chart matrix against Vietnamese textbook rules (Step 2)."""
    chart_type = normalize_chart_type(data.get("chart_type", "column"))
    categories_raw = parse_semicolon_or_pipe(data.get("categories", ""))
    series_raw = parse_semicolon_or_pipe(data.get("series_name", ""))
    values_raw = normalize_text_nfc(data.get("values", ""))

    parsed_matrix: Dict[str, Any] = {
        "chart_title": normalize_text_nfc(data.get("chart_title", "")),
        "chart_type": chart_type,
        "unit": normalize_text_nfc(data.get("unit", "")),
        "categories": categories_raw,
        "series_names": series_raw if series_raw else ["Giá trị"],
        "series_data": {},
        "raw_data": data,
    }

    issues: List[str] = []
    structured_series = _extract_dict_values(values_raw)
    if structured_series is not None:
        val_lists = structured_series
        issues.append("Định dạng giá trị dạng dict/JSON đã được chuẩn hóa lại")
    else:
        val_chunks = [ch.strip() for ch in values_raw.split("||") if ch.strip()]
        val_lists = []
        for chunk in val_chunks:
            items_str = [it.strip() for it in re.split(r"[|;]", chunk) if it.strip()]
            val_lists.append([clean_vietnamese_number(it) for it in items_str])

    for s_idx, s_name in enumerate(parsed_matrix["series_names"]):
        if s_idx < len(val_lists):
            num_list = list(val_lists[s_idx])
            if categories_raw and len(num_list) != len(categories_raw):
                issues.append(
                    f"Chuỗi '{s_name}' có {len(num_list)} giá trị != {len(categories_raw)} danh mục"
                )
                if len(num_list) < len(categories_raw):
                    num_list.extend([None] * (len(categories_raw) - len(num_list)))
            parsed_matrix["series_data"][s_name] = num_list
        else:
            parsed_matrix["series_data"][s_name] = [None] * len(categories_raw)
            issues.append(f"Chuỗi '{s_name}' không có giá trị trích xuất")

    if len(val_lists) > len(parsed_matrix["series_names"]):
        issues.append(
            f"Số chuỗi giá trị ({len(val_lists)}) vượt quá số tên chuỗi ({len(parsed_matrix['series_names'])})"
        )

    # Rule 1: Pie chart percentage sum ~ 100% +/- 2%
    if chart_type == "pie":
        first_series = (
            list(parsed_matrix["series_data"].values())[0]
            if parsed_matrix["series_data"]
            else []
        )
        valid_nums = [v for v in first_series if v is not None]
        if valid_nums:
            total_pct = sum(valid_nums)
            if not (98.0 <= total_pct <= 102.0):
                issues.append(
                    f"Tổng tỷ lệ phần trăm biểu đồ tròn = {total_pct:.1f}% (khác 100±2%)"
                )

    # Rule 2: Monotonic increasing years on time axis
    years = []
    for cat in categories_raw:
        m = re.search(r"\b(19\d{2}|20\d{2})\b", str(cat))
        if m:
            years.append(int(m.group(1)))
    if len(years) > 1 and years != sorted(years):
        issues.append(f"Trục thời gian không tăng dần: {years}")

    status = "Hợp lệ" if len(issues) == 0 else "Cần kiểm tra"
    notes = "; ".join(issues) if issues else "Đạt chuẩn định dạng & khớp logic số liệu"
    return status, notes, parsed_matrix


def apply_uncertainty_flagging(
    parsed_matrix: Dict[str, Any], validation_notes: str
) -> Dict[str, Any]:
    """Flag missing/invalid cells with '[chưa chắc chắn]' and propagate uncertainty status."""
    has_uncertainty = False
    flagged_series_data: Dict[str, List[Any]] = {}

    for s_name, vals in parsed_matrix["series_data"].items():
        flagged_vals: List[Any] = []
        for v in vals:
            if v is None:
                flagged_vals.append("[chưa chắc chắn]")
                has_uncertainty = True
            else:
                flagged_vals.append(v)
        flagged_series_data[s_name] = flagged_vals

    if (
        "Cần kiểm tra" in validation_notes
        or "khác 100" in validation_notes
        or "!=" in validation_notes
        or "không có giá trị" in validation_notes
        or "không tăng dần" in validation_notes
    ):
        has_uncertainty = True

    return {
        "chart_title": parsed_matrix["chart_title"],
        "chart_type": parsed_matrix["chart_type"],
        "unit": parsed_matrix["unit"],
        "categories": parsed_matrix["categories"],
        "series_names": parsed_matrix["series_names"],
        "series_data": flagged_series_data,
        "has_uncertainty": has_uncertainty,
        "validation_notes": validation_notes,
    }


def fmt_vn(val: Any) -> str:
    """Format numeric value with Vietnamese decimal comma."""
    if val is None or val == "[chưa chắc chắn]":
        return "[chưa chắc chắn]"
    if isinstance(val, (int, float)):
        f = round(float(val), 2)
        if f.is_integer():
            return str(int(f))
        s = f"{f:.2f}".rstrip("0").rstrip(".")
        return s.replace(".", ",")
    return str(val)


def clean_chart_title_for_speech(
    title: str, unit: str = "", series_names: Optional[List[str]] = None
) -> str:
    """Normalize chart title or synthesize natural subject phrase when missing."""
    t = str(title).strip()
    t = re.sub(r"^(?:Hình|Biểu đồ|Bảng)\s+[\d\.]+\s*[:\-–]?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(?:Biểu đồ|Bảng)\s+(?:thể hiện|về)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(?:thể hiện|về)\s+", "", t, flags=re.IGNORECASE)
    meaningless = {
        "", "thiếu tên biểu đồ", "không có tên", "biểu đồ không có tên",
        "chưa rõ", "none", "nan", "không có tiêu đề",
    }
    if t.lower() in meaningless:
        s_list = [
            s.strip()
            for s in (series_names or [])
            if s and s.strip().lower() not in {"giá trị", "số liệu", "tỷ trọng"}
        ]
        u_clean = unit.strip()
        if u_clean and s_list:
            if u_clean in {"%", "phần trăm"}:
                return f"cơ cấu {', '.join(s_list)}"
            if len(s_list) == 2:
                return f"diễn biến {u_clean.lower()} của {s_list[0]} và {s_list[1]}"
            if len(s_list) > 2:
                return f"diễn biến {u_clean.lower()} giữa các nhóm {', '.join(s_list)}"
            return f"{u_clean.lower()} ({s_list[0]})"
        if s_list:
            if len(s_list) == 2:
                return f"số liệu giữa {s_list[0]} và {s_list[1]}"
            return f"giá trị của {', '.join(s_list)}"
        if u_clean:
            return f"các số liệu đo lường theo {u_clean.lower()}"
        return "các chỉ số khảo sát"
    return t.strip()


def generate_3level_descriptions(flagged_matrix: Dict[str, Any]) -> Dict[str, str]:
    """
    Generate grounded 3-level Vietnamese chart descriptions strictly from verified matrix:
    - Cấp 1 (5s): Overview (type, subject, unit, scope, main trend)
    - Cấp 2 (30s): Quantitative summary (extremes, spread, net change, uncertainty warnings)
    - Cấp 3 (Study): Detailed chronological/category walkthrough and phase comparison
    """
    raw_title = flagged_matrix["chart_title"]
    c_type = flagged_matrix["chart_type"]
    unit = flagged_matrix["unit"].strip()
    cats = flagged_matrix["categories"]
    series_data = flagged_matrix["series_data"]
    series_names = list(series_data.keys())
    has_un = flagged_matrix["has_uncertainty"]

    clean_title = clean_chart_title_for_speech(raw_title, unit=unit, series_names=series_names)

    if c_type == "column":
        c_type_label = "Biểu đồ cột ghép" if len(series_data) >= 2 else "Biểu đồ cột"
    else:
        c_type_label = {
            "line": "Biểu đồ đường",
            "pie": "Biểu đồ tròn",
            "area": "Biểu đồ miền",
            "combo": "Biểu đồ kết hợp",
        }.get(c_type, "Biểu đồ")

    is_time_series = len(cats) >= 2 and all(
        re.search(r"\b(19\d{2}|20\d{2})\b", str(c)) for c in cats
    )

    is_long_metric_unit = len(unit.split()) >= 3 and unit.lower() in clean_title.lower()
    unit_suffix = "" if is_long_metric_unit else ("%" if unit == "%" else (f" {unit}" if unit else ""))
    if unit and unit.lower() not in clean_title.lower():
        unit_paren = f" (đơn vị: {unit.lower() if len(unit) > 4 else unit})"
    else:
        unit_paren = ""

    all_valid_points: List[Tuple[float, str, str, int]] = []
    points_by_series: Dict[str, List[Tuple[float, str, str, int]]] = {}
    for s_name, vals in series_data.items():
        points_by_series[s_name] = []
        for i, v in enumerate(vals):
            c_label = cats[i] if i < len(cats) else "mốc chưa khớp nhãn"
            if isinstance(v, (int, float)):
                pt = (float(v), s_name, c_label, i)
                all_valid_points.append(pt)
                points_by_series[s_name].append(pt)

    # --------------------------------------------------------------------------
    # 1. CẤP 1: TỔNG QUAN 5 GIÂY
    # --------------------------------------------------------------------------
    if is_time_series:
        scope_phrase = f"từ năm {cats[0]} đến năm {cats[-1]}"
    elif cats:
        scope_phrase = f"qua {len(cats)} nhóm danh mục"
    else:
        scope_phrase = "qua các danh mục khảo sát"

    trend_sentence = ""
    if is_time_series:
        if len(series_data) >= 2:
            s_means = {
                s: (sum(p[0] for p in pts) / len(pts))
                for s, pts in points_by_series.items()
                if pts
            }
            sorted_s_names = sorted(s_means.keys(), key=lambda x: s_means[x], reverse=True)
            if not sorted_s_names:
                trend_sentence = (
                    f"Qua {len(cats)} năm, các chuỗi số liệu hiện chưa xác minh đầy đủ để tổng hợp xu hướng."
                )
            else:
                top_s = sorted_s_names[0]
                other_s = sorted_s_names[1] if len(sorted_s_names) > 1 else ""
                all_inc = all(
                    len(pts) >= 2 and all(pts[k][0] <= pts[k + 1][0] for k in range(len(pts) - 1))
                    for pts in points_by_series.values()
                    if pts
                )
                all_dec = all(
                    len(pts) >= 2 and all(pts[k][0] >= pts[k + 1][0] for k in range(len(pts) - 1))
                    for pts in points_by_series.values()
                    if pts
                )
                top_pts = points_by_series.get(top_s, [])
                other_pts = points_by_series.get(other_s, [])
                always_higher = (
                    len(top_pts) == len(other_pts)
                    and len(top_pts) > 0
                    and all(top_pts[k][0] > other_pts[k][0] for k in range(len(top_pts)))
                )

                if all_inc:
                    if always_higher and len(series_data) == 2:
                        trend_sentence = (
                            f"Qua {len(cats)} năm, cả hai nhóm đều có xu hướng tăng nhẹ và ổn định, trong đó {top_s} luôn cao hơn {other_s}."
                        )
                    else:
                        trend_sentence = (
                            f"Qua {len(cats)} năm, các nhóm đều có xu hướng tăng, nổi bật là {top_s} duy trì mức cao nhất."
                        )
                elif all_dec:
                    trend_sentence = (
                        f"Qua {len(cats)} năm, các nhóm đều ghi nhận xu hướng giảm, trong đó {top_s} vẫn giữ mức cao nhất."
                    )
                else:
                    if always_higher and len(series_data) == 2:
                        trend_sentence = (
                            f"Qua {len(cats)} năm, diễn biến các nhóm có sự biến động, trong đó {top_s} luôn cao hơn {other_s}."
                        )
                    else:
                        trend_sentence = (
                            f"Qua {len(cats)} năm, các chuỗi có diễn biến biến động khác nhau, nổi bật nhất là {top_s}."
                        )
        elif series_names:
            main_s = series_names[0]
            pts = points_by_series.get(main_s, [])
            if len(pts) >= 2:
                v_start, v_end = pts[0][0], pts[-1][0]
                is_inc = all(pts[k][0] <= pts[k + 1][0] for k in range(len(pts) - 1))
                is_dec = all(pts[k][0] >= pts[k + 1][0] for k in range(len(pts) - 1))
                if is_inc:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị ghi nhận xu hướng tăng liên tục."
                elif is_dec:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị ghi nhận xu hướng giảm liên tục."
                elif v_end > v_start:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị có xu hướng tăng chung dù có nhịp dao động."
                elif v_end < v_start:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị có xu hướng giảm về cuối giai đoạn."
                else:
                    trend_sentence = f"Qua {len(cats)} năm, giá trị duy trì ở mức tương đối ổn định."
    elif c_type == "pie":
        if all_valid_points:
            top_pt = max(all_valid_points, key=lambda x: x[0])
            min_pt = min(all_valid_points, key=lambda x: x[0])
            trend_sentence = (
                f"Cơ cấu cho thấy {top_pt[2]} chiếm tỷ trọng cao nhất ({fmt_vn(top_pt[0])}{unit_suffix}), trong khi {min_pt[2]} chiếm tỷ trọng thấp nhất."
            )
        else:
            trend_sentence = "Biểu đồ phản ánh cơ cấu tỷ trọng giữa các nhóm thành phần."
    else:
        if all_valid_points:
            top_pt = max(all_valid_points, key=lambda x: x[0])
            min_pt = min(all_valid_points, key=lambda x: x[0])
            trend_sentence = (
                f"Số liệu cho thấy sự chênh lệch rõ nét giữa các nhóm, dẫn đầu là {top_pt[2]} và thấp nhất là {min_pt[2]}."
            )
        else:
            trend_sentence = "Biểu đồ thể hiện sự so sánh giá trị giữa các danh mục khảo sát."

    desc_5s_parts = [
        f"{c_type_label} thể hiện {clean_title} {scope_phrase}{unit_paren}.",
        trend_sentence,
    ]
    if has_un:
        desc_5s_parts.append(
            "Lưu ý: Một số giá trị trên biểu đồ chưa xác minh được chắc chắn do ảnh mờ hoặc thiếu thông tin."
        )
    desc_5s = " ".join(p for p in desc_5s_parts if p)

    # --------------------------------------------------------------------------
    # 2. CẤP 2: TÓM TẮT XU HƯỚNG 30 GIÂY
    # --------------------------------------------------------------------------
    desc_30s_parts: List[str] = []
    if is_time_series:
        if len(series_data) >= 2:
            all_inc = all(
                len(pts) >= 2 and all(pts[k][0] <= pts[k + 1][0] for k in range(len(pts) - 1))
                for pts in points_by_series.values()
                if pts
            )
            if all_inc and all_valid_points:
                desc_30s_parts.append(
                    f"Từ năm {cats[0]} đến năm {cats[-1]}, {clean_title} đều tăng dần qua các mốc khảo sát."
                )
            else:
                desc_30s_parts.append(
                    f"Từ năm {cats[0]} đến năm {cats[-1]}, {clean_title} ghi nhận sự biến chuyển qua {len(cats)} mốc khảo sát."
                )
        else:
            desc_30s_parts.append(
                f"Từ năm {cats[0]} đến năm {cats[-1]}, {clean_title} thay đổi qua {len(cats)} mốc thời gian."
            )
    elif c_type == "pie":
        desc_30s_parts.append(
            f"Xét về cơ cấu qua {len(cats)} nhóm thành phần, {clean_title} phân bổ không đồng đều giữa các đối tượng."
        )
    else:
        desc_30s_parts.append(
            f"So sánh qua {len(cats)} danh mục khảo sát, {clean_title} thể hiện sự chênh lệch rõ rệt về quy mô."
        )

    if all_valid_points:
        max_pt = max(all_valid_points, key=lambda x: x[0])
        min_pt = min(all_valid_points, key=lambda x: x[0])
        max_val, max_s, max_cat, _ = max_pt
        min_val, min_s, min_cat, _ = min_pt
        diff_val = round(max_val - min_val, 2)

        if len(series_data) >= 2:
            if is_time_series:
                max_where = f"năm {max_cat}" if max_cat != "mốc chưa khớp nhãn" else max_cat
                min_where = f"năm {min_cat}" if min_cat != "mốc chưa khớp nhãn" else min_cat
                desc_30s_parts.append(
                    f"Nhóm {max_s} duy trì mức cao hơn và đạt đỉnh ở {max_where} với {fmt_vn(max_val)}{unit_suffix}, trong khi nhóm {min_s} thấp nhất ở {min_where} với {fmt_vn(min_val)}{unit_suffix}."
                )
            else:
                desc_30s_parts.append(
                    f"Mức cao nhất thuộc về {max_cat} ở nhóm {max_s} đạt {fmt_vn(max_val)}{unit_suffix}, trong khi mức thấp nhất thuộc về {min_cat} ở nhóm {min_s} với {fmt_vn(min_val)}{unit_suffix}."
                )
        else:
            if is_time_series:
                max_where = f"năm {max_cat}" if max_cat != "mốc chưa khớp nhãn" else max_cat
                min_where = f"năm {min_cat}" if min_cat != "mốc chưa khớp nhãn" else min_cat
                desc_30s_parts.append(
                    f"Giá trị đạt đỉnh vào {max_where} với {fmt_vn(max_val)}{unit_suffix} và thấp nhất vào {min_where} với {fmt_vn(min_val)}{unit_suffix}."
                )
            else:
                desc_30s_parts.append(
                    f"Nhóm {max_cat} dẫn đầu với {fmt_vn(max_val)}{unit_suffix}, trong khi nhóm thấp nhất là {min_cat} đạt {fmt_vn(min_val)}{unit_suffix}."
                )

        if diff_val > 0:
            desc_30s_parts.append(
                f"Khoảng cách chênh lệch lớn nhất giữa giá trị cao nhất và thấp nhất trên biểu đồ là {fmt_vn(diff_val)}{unit_suffix}."
            )

        if is_time_series and series_names:
            main_s = series_names[0]
            pts = points_by_series.get(main_s, [])
            if len(pts) >= 2:
                v_first = pts[0][0]
                v_last = pts[-1][0]
                net_change = round(v_last - v_first, 2)
                start_where = f"năm {pts[0][2]}" if pts[0][2] != "mốc chưa khớp nhãn" else pts[0][2]
                end_where = f"năm {pts[-1][2]}" if pts[-1][2] != "mốc chưa khớp nhãn" else pts[-1][2]
                if net_change > 0:
                    desc_30s_parts.append(
                        f"Tính từ {start_where} đến {end_where}, chuỗi {main_s} tăng thêm {fmt_vn(net_change)}{unit_suffix} so với mốc ban đầu."
                    )
                elif net_change < 0:
                    desc_30s_parts.append(
                        f"Tính từ {start_where} đến {end_where}, chuỗi {main_s} giảm {fmt_vn(abs(net_change))}{unit_suffix} so với mốc ban đầu."
                    )

    un_locations: List[str] = []
    for s_name, vals in series_data.items():
        for i, v in enumerate(vals):
            if v is None or v == "[chưa chắc chắn]":
                c_lbl = cats[i] if i < len(cats) else "mốc chưa khớp nhãn"
                un_locations.append(f"chuỗi {s_name} tại {c_lbl}")

    if un_locations:
        desc_30s_parts.append(
            f"Lưu ý có các vị trí [chưa chắc chắn] chưa xác minh được số liệu ({', '.join(un_locations[:3])})."
        )
    elif has_un:
        desc_30s_parts.append(
            "Lưu ý: Bảng dữ liệu có dấu hiệu [chưa chắc chắn] về tính nhất quán giữa trục và giá trị."
        )

    desc_30s = " ".join(desc_30s_parts)

    # --------------------------------------------------------------------------
    # 3. CẤP 3: PHÂN TÍCH HỌC TẬP CHUYÊN SÂU
    # --------------------------------------------------------------------------
    def _clean_s(name: str) -> str:
        s_c = name.strip()
        if s_c.count("(") > s_c.count(")"):
            s_c += ")"
        return s_c

    def _extract_phases(pts_list: List[Tuple[float, str, str, int]]) -> List[Dict[str, Any]]:
        phases: List[Dict[str, Any]] = []
        if len(pts_list) < 2:
            return phases
        cur_dir = None
        start_idx = 0
        for k in range(1, len(pts_list)):
            d = round(pts_list[k][0] - pts_list[k - 1][0], 2)
            step_dir = "up" if d > 0 else ("down" if d < 0 else "flat")
            if cur_dir is None:
                cur_dir = step_dir
                start_idx = k - 1
            elif step_dir != cur_dir:
                phases.append(
                    {
                        "dir": cur_dir,
                        "start_c": pts_list[start_idx][2],
                        "end_c": pts_list[k - 1][2],
                        "start_v": pts_list[start_idx][0],
                        "end_v": pts_list[k - 1][0],
                        "delta": round(pts_list[k - 1][0] - pts_list[start_idx][0], 2),
                        "steps": (k - 1) - start_idx,
                    }
                )
                cur_dir = step_dir
                start_idx = k - 1
        phases.append(
            {
                "dir": cur_dir,
                "start_c": pts_list[start_idx][2],
                "end_c": pts_list[-1][2],
                "start_v": pts_list[start_idx][0],
                "end_v": pts_list[-1][0],
                "delta": round(pts_list[-1][0] - pts_list[start_idx][0], 2),
                "steps": (len(pts_list) - 1) - start_idx,
            }
        )
        return phases

    desc_study_sentences: List[str] = []
    unit_parts = [u.strip() for u in unit.split("|")] if "|" in unit else []

    if is_time_series:
        if len(series_names) == 1:
            s0 = series_names[0]
            vals0 = series_data[s0]
            pts0 = points_by_series.get(s0, [])
            max_v0 = max(p[0] for p in pts0) if pts0 else None
            min_v0 = min(p[0] for p in pts0) if pts0 else None

            seq_parts = []
            prev_v = None
            for i, v in enumerate(vals0):
                ck = cats[i] if i < len(cats) else "mốc chưa khớp nhãn"
                ck_phrase = f"năm {ck}" if ck != "mốc chưa khớp nhãn" else ck
                if i == 0:
                    seq_parts.append(
                        f"Qua giai đoạn {cats[0]}–{cats[-1]}, chuỗi dữ liệu bắt đầu ở mức {fmt_vn(v)}{unit_suffix} {ck_phrase}"
                    )
                elif v is None or v == "[chưa chắc chắn]":
                    seq_parts.append(f"chưa xác minh được giá trị tại {ck_phrase}")
                elif isinstance(prev_v, (int, float)) and isinstance(v, (int, float)):
                    d = round(float(v) - float(prev_v), 2)
                    if d == 0:
                        seq_parts.append(f"giữ nguyên mức {fmt_vn(v)}{unit_suffix} {ck_phrase}")
                    elif d > 0:
                        if max_v0 is not None and float(v) == max_v0 and i < len(vals0) - 1:
                            seq_parts.append(f"chạm đỉnh {fmt_vn(v)}{unit_suffix} {ck_phrase}")
                        elif (
                            i >= 2
                            and isinstance(vals0[i - 2], (int, float))
                            and float(prev_v) < float(vals0[i - 2])
                        ):
                            seq_parts.append(f"đảo chiều tăng lên {fmt_vn(v)}{unit_suffix} {ck_phrase}")
                        else:
                            seq_parts.append(f"{fmt_vn(v)}{unit_suffix} {ck_phrase}")
                    else:
                        if min_v0 is not None and float(v) == min_v0 and i < len(vals0) - 1:
                            seq_parts.append(f"giảm xuống đáy {fmt_vn(v)}{unit_suffix} {ck_phrase}")
                        elif i == len(vals0) - 1:
                            seq_parts.append(f"sau đó hạ xuống {fmt_vn(v)}{unit_suffix} {ck_phrase}")
                        else:
                            seq_parts.append(f"giảm xuống {fmt_vn(v)}{unit_suffix} {ck_phrase}")
                else:
                    seq_parts.append(f"{fmt_vn(v)}{unit_suffix} {ck_phrase}")
                prev_v = v

            if len(seq_parts) >= 2:
                s_timeline = (
                    seq_parts[0]
                    + ", "
                    + ", ".join(seq_parts[1:-1])
                    + (", " if len(seq_parts) > 2 else "")
                    + seq_parts[-1]
                    + "."
                )
                s_timeline = re.sub(r",\s+(sau đó|giữ nguyên|đảo chiều)\s+", r", \1 ", s_timeline)
                desc_study_sentences.append(s_timeline)

            if len(pts0) >= 2:
                phases = _extract_phases(pts0)
                phase_clauses = []
                for ph in phases:
                    if ph["dir"] == "up":
                        phase_clauses.append(
                            f"pha tăng từ {ph['start_c']} đến {ph['end_c']} (tăng {fmt_vn(abs(ph['delta']))}{unit_suffix})"
                        )
                    elif ph["dir"] == "down":
                        phase_clauses.append(
                            f"nhịp giảm giai đoạn {ph['start_c']}–{ph['end_c']} (hạ {fmt_vn(abs(ph['delta']))}{unit_suffix})"
                        )
                    else:
                        phase_clauses.append(
                            f"giai đoạn đi ngang {ph['start_c']}–{ph['end_c']} ở mức {fmt_vn(ph['start_v'])}{unit_suffix}"
                        )
                if phase_clauses:
                    desc_study_sentences.append(
                        f"Xét theo từng chặng, diễn biến gồm {', nối tiếp bởi '.join(phase_clauses)}."
                    )

                max_step = 0.0
                max_span = ("", "")
                max_dir = ""
                for k in range(len(pts0) - 1):
                    diff_s = round(pts0[k + 1][0] - pts0[k][0], 2)
                    if abs(diff_s) > abs(max_step):
                        max_step = diff_s
                        max_span = (pts0[k][2], pts0[k + 1][2])
                        max_dir = "tăng" if diff_s > 0 else "giảm"

                v_first, v_last = pts0[0][0], pts0[-1][0]
                net_0 = round(v_last - v_first, 2)
                net_clause = ""
                if net_0 > 0:
                    net_clause = f", giúp mặt bằng cuối kỳ vẫn cao hơn mốc khởi đầu {fmt_vn(net_0)}{unit_suffix}"
                elif net_0 < 0:
                    net_clause = f", khiến mặt bằng cuối kỳ thấp hơn mốc khởi đầu {fmt_vn(abs(net_0))}{unit_suffix}"

                if abs(max_step) > 0:
                    desc_study_sentences.append(
                        f"Đáng chú ý, bước biến động mạnh nhất diễn ra từ {max_span[0]} sang {max_span[1]} ({max_dir} {fmt_vn(abs(max_step))}{unit_suffix}){net_clause}."
                    )

                if net_0 > 0 and any(ph["dir"] == "down" for ph in phases):
                    overall_note = "xu hướng chung cả giai đoạn là đi lên dù xen kẽ nhịp suy giảm hoặc điều chỉnh"
                elif net_0 > 0:
                    overall_note = "xu hướng chủ đạo là tăng trưởng tích cực qua từng chặng"
                elif net_0 < 0:
                    overall_note = "xu hướng chung cả giai đoạn là đi xuống rõ rệt"
                else:
                    overall_note = "giá trị có dao động giữa kỳ nhưng kết thúc cân bằng với điểm xuất phát"
                desc_study_sentences.append(
                    f"Điều này cho thấy {overall_note}, là cơ sở để người học đối chiếu các điểm ngoặt và biên độ thay đổi giữa từng chặng."
                )
        else:
            year_clauses = []
            for i, ck in enumerate(cats):
                items_at_year = []
                for idx_s, s_name in enumerate(series_names):
                    u_s = (
                        f" {unit_parts[idx_s].lower()}"
                        if (unit_parts and idx_s < len(unit_parts) and unit_parts[idx_s])
                        else unit_suffix
                    )
                    vals_s = series_data[s_name]
                    v = vals_s[i] if i < len(vals_s) else None
                    s_lbl = _clean_s(s_name)
                    if (
                        i > 0
                        and isinstance(v, (int, float))
                        and isinstance(vals_s[i - 1], (int, float))
                        and round(float(v) - float(vals_s[i - 1]), 2) == 0
                    ):
                        items_at_year.append(f"{s_lbl} giữ nguyên {fmt_vn(v)}{u_s}")
                    else:
                        items_at_year.append(f"{s_lbl} {fmt_vn(v)}{u_s}")
                if i == 0:
                    year_clauses.append(
                        f"Qua giai đoạn {cats[0]}–{cats[-1]}, số liệu khởi đầu năm {ck} với {', '.join(items_at_year)}"
                    )
                else:
                    year_clauses.append(f"năm {ck} ghi nhận {', '.join(items_at_year)}")
            if year_clauses:
                desc_study_sentences.append("; ".join(year_clauses) + ".")

            phase_summaries = []
            for idx_s, s_name in enumerate(series_names):
                u_s = (
                    f" {unit_parts[idx_s].lower()}"
                    if (unit_parts and idx_s < len(unit_parts) and unit_parts[idx_s])
                    else unit_suffix
                )
                pts_s = points_by_series.get(s_name, [])
                if len(pts_s) >= 2:
                    net_s = round(pts_s[-1][0] - pts_s[0][0], 2)
                    flat_spans = [
                        f"{pts_s[k][2]}–{pts_s[k + 1][2]}"
                        for k in range(len(pts_s) - 1)
                        if round(pts_s[k + 1][0] - pts_s[k][0], 2) == 0
                        and pts_s[k][2] != "mốc chưa khớp nhãn"
                        and pts_s[k + 1][2] != "mốc chưa khớp nhãn"
                    ]
                    flat_str = f" (đi ngang chặng {', '.join(flat_spans)})" if flat_spans else ""
                    dir_str = (
                        f"tăng {fmt_vn(net_s)}{u_s}"
                        if net_s > 0
                        else (f"giảm {fmt_vn(abs(net_s))}{u_s}" if net_s < 0 else "không đổi")
                    )
                    phase_summaries.append(f"{_clean_s(s_name)} {dir_str}{flat_str}")

            if phase_summaries:
                desc_study_sentences.append(
                    f"Tính trên toàn chặng từ {cats[0]} đến {cats[-1]}, mức thay đổi ghi nhận ở {'; '.join(phase_summaries)}."
                )

            s_means = {
                s: (sum(p[0] for p in pts) / len(pts))
                for s, pts in points_by_series.items()
                if pts
            }
            sorted_s = sorted(s_means.keys(), key=lambda x: s_means[x], reverse=True)
            if len(sorted_s) >= 2:
                s_hi, s_lo = sorted_s[0], sorted_s[1]
                pts_hi, pts_lo = points_by_series.get(s_hi, []), points_by_series.get(s_lo, [])
                if len(pts_hi) >= 2 and len(pts_lo) >= 2:
                    gap_start = round(abs(pts_hi[0][0] - pts_lo[0][0]), 2)
                    gap_end = round(abs(pts_hi[-1][0] - pts_lo[-1][0]), 2)
                    u_comp = "" if unit_parts else unit_suffix
                    always_higher = len(pts_hi) == len(pts_lo) and all(
                        pts_hi[k][0] > pts_lo[k][0] for k in range(len(pts_hi))
                    )
                    if always_higher:
                        trend_gap = (
                            "nới rộng"
                            if gap_end > gap_start
                            else ("thu hẹp" if gap_end < gap_start else "giữ ổn định")
                        )
                        desc_study_sentences.append(
                            f"Xét tương quan giữa các chặng, {_clean_s(s_hi)} luôn cao hơn {_clean_s(s_lo)} tại mọi mốc, với khoảng cách {trend_gap} từ {fmt_vn(gap_start)}{u_comp} năm {pts_hi[0][2]} sang {fmt_vn(gap_end)}{u_comp} năm {pts_hi[-1][2]}."
                        )
                    else:
                        desc_study_sentences.append(
                            f"So sánh hai đầu giai đoạn, chênh lệch giữa {_clean_s(s_hi)} và {_clean_s(s_lo)} chuyển từ {fmt_vn(gap_start)}{u_comp} sang {fmt_vn(gap_end)}{u_comp}."
                        )

            desc_study_sentences.append(
                "Nhìn chung, việc đối chiếu song song từng mốc giúp làm rõ nhịp độ biến động và mức độ phân hóa giữa các đối tượng phục vụ ôn tập."
            )

    elif c_type == "pie":
        total_sum = round(sum(p[0] for p in all_valid_points), 2) if all_valid_points else 0.0
        s0 = series_names[0]
        vals0 = series_data[s0]
        item_strs = [
            f"{cats[i] if i < len(cats) else 'mục chưa khớp nhãn'} chiếm {fmt_vn(v)}{unit_suffix}"
            for i, v in enumerate(vals0)
        ]
        if item_strs:
            sum_clause = (
                f", đạt tổng tỷ trọng {fmt_vn(total_sum)}{unit_suffix}"
                if all_valid_points
                else ""
            )
            desc_study_sentences.append(
                f"Theo trình tự cơ cấu trên biểu đồ, {', '.join(item_strs)}{sum_clause}."
            )
        sorted_pts = sorted(all_valid_points, key=lambda x: x[0], reverse=True)
        if len(sorted_pts) >= 2:
            top_part, second_part, low_part = sorted_pts[0], sorted_pts[1], sorted_pts[-1]
            gap_12 = round(top_part[0] - second_part[0], 2)
            gap_pie = round(top_part[0] - low_part[0], 2)
            ratio_pie = round(top_part[0] / low_part[0], 1) if low_part[0] > 0 else None
            ratio_clause = f" (gấp {fmt_vn(ratio_pie)} lần)" if ratio_pie else ""
            desc_study_sentences.append(
                f"Xét thứ bậc cơ cấu, {top_part[2]} giữ vị trí chi phối lớn nhất, cao hơn nhóm đứng thứ hai là {second_part[2]} khoảng {fmt_vn(gap_12)}{unit_suffix}."
            )
            desc_study_sentences.append(
                f"Khoảng cách giữa hai thái cực lớn nhất ({top_part[2]}) và nhỏ nhất ({low_part[2]}) lên tới {fmt_vn(gap_pie)}{unit_suffix}{ratio_clause}."
            )
            desc_study_sentences.append(
                "Sự chênh lệch này cho thấy cơ cấu phân bổ tập trung rõ vào nhóm dẫn đầu, là trọng tâm cần ghi nhớ khi phân tích tỷ trọng."
            )
    else:
        cat_clauses = []
        for i, ck in enumerate(cats):
            if len(series_names) == 1:
                v = series_data[series_names[0]][i] if i < len(series_data[series_names[0]]) else None
                cat_clauses.append(f"{ck} đạt {fmt_vn(v)}{unit_suffix}")
            else:
                sub_items = []
                for idx_s, s_name in enumerate(series_names):
                    u_s = (
                        f" {unit_parts[idx_s].lower()}"
                        if (unit_parts and idx_s < len(unit_parts) and unit_parts[idx_s])
                        else unit_suffix
                    )
                    v = series_data[s_name][i] if i < len(series_data[s_name]) else None
                    sub_items.append(f"{_clean_s(s_name)} {fmt_vn(v)}{u_s}")
                cat_clauses.append(f"{ck} ({', '.join(sub_items)})")

        if cat_clauses:
            desc_study_sentences.append(
                f"Theo trình tự các mục dữ liệu, giá trị ghi nhận lần lượt ở {', '.join(cat_clauses)}."
            )
        sorted_pts = sorted(all_valid_points, key=lambda x: x[0], reverse=True)
        if len(sorted_pts) >= 2:
            top_pt, second_pt, low_pt = sorted_pts[0], sorted_pts[1], sorted_pts[-1]
            gap_12 = round(top_pt[0] - second_pt[0], 2)
            gap_max_min = round(top_pt[0] - low_pt[0], 2)
            desc_study_sentences.append(
                f"Xét tương quan giữa các mốc, {top_pt[2]} vượt lên trên vị trí kế tiếp ({second_pt[2]}) khoảng cách {fmt_vn(gap_12)}{unit_suffix}."
            )
            desc_study_sentences.append(
                f"So sánh hai đầu bảng xếp hạng, biên độ chênh lệch từ mức cao nhất ({fmt_vn(top_pt[0])}{unit_suffix}) đến mức thấp nhất ở {low_pt[2]} ({fmt_vn(low_pt[0])}{unit_suffix}) đạt {fmt_vn(gap_max_min)}{unit_suffix}."
            )
            desc_study_sentences.append(
                "Nhịp phân hóa này phản ánh sự khác biệt rõ rệt về quy mô giữa nhóm dẫn đầu và phần còn lại trong quá trình đối chiếu số liệu."
            )

    if un_locations:
        desc_study_sentences.append(
            f"Lưu ý về độ tin cậy: Các vị trí {', '.join(un_locations)} [chưa chắc chắn] do chưa xác minh được chính xác từ ảnh gốc."
        )
    elif has_un:
        desc_study_sentences.append(
            "Lưu ý về độ tin cậy: Dữ liệu đầu vào có cảnh báo [chưa chắc chắn] cần đối chiếu lại ảnh gốc."
        )

    desc_study = " ".join(desc_study_sentences)
    return {
        "desc_5s": desc_5s,
        "desc_30s": desc_30s,
        "desc_study": desc_study,
    }


def fact_check_vichartfact(
    desc_dict: Dict[str, str], flagged_matrix: Dict[str, Any]
) -> Dict[str, Any]:
    """
    ViChartFact Factuality Metric:
    Verify every numerical entity appearing in the generated descriptions against
    the verified data matrix, category/axis labels, metadata counts, and valid
    derived operations (differences, sums, ratios) within 5% relative / 0.05 abs tolerance.
    """
    title = flagged_matrix.get("chart_title", "")
    unit = flagged_matrix.get("unit", "")
    cats = flagged_matrix.get("categories", [])
    series_data = flagged_matrix.get("series_data", {})

    cell_pool = []
    all_numeric_vals: List[float] = []
    for s_name, vals in series_data.items():
        for i, v in enumerate(vals):
            if v is not None and isinstance(v, (int, float)):
                c_label = cats[i] if i < len(cats) else f"Cột {i+1}"
                cell_pool.append(
                    {"val": float(v), "series": str(s_name), "category": str(c_label)}
                )
                all_numeric_vals.append(float(v))

    cat_pool = []
    for c in cats:
        for n_str in re.findall(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", str(c)):
            n_val = clean_vietnamese_number(n_str)
            if n_val is not None:
                cat_pool.append({"val": n_val, "raw": n_str, "cat_name": str(c)})

    meta_pool = [
        {"val": float(len(cats)), "desc": f"Số lượng mốc danh mục ({len(cats)} mốc)"},
        {"val": float(len(series_data)), "desc": f"Số lượng chuỗi dữ liệu ({len(series_data)} chuỗi)"},
    ]
    if title:
        for t_n in re.findall(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", str(title)):
            t_val = clean_vietnamese_number(t_n)
            if t_val is not None:
                meta_pool.append({"val": t_val, "desc": f"Số trong tiêu đề biểu đồ ('{title}')"})
    if unit:
        for u_n in re.findall(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", str(unit)):
            u_val = clean_vietnamese_number(u_n)
            if u_val is not None:
                meta_pool.append({"val": u_val, "desc": f"Số trong đơn vị tính ('{unit}')"})
    for s_name in series_data.keys():
        for s_n in re.findall(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", str(s_name)):
            s_val = clean_vietnamese_number(s_n)
            if s_val is not None:
                meta_pool.append({"val": s_val, "desc": f"Số trong tên chuỗi ('{s_name}')"})

    derived_pool = []
    if all_numeric_vals:
        max_v = max(all_numeric_vals)
        min_v = min(all_numeric_vals)
        derived_pool.append(
            {
                "val": round(max_v - min_v, 2),
                "desc": f"Chênh lệch cực đại - cực tiểu ({max_v} - {min_v})",
            }
        )
        derived_pool.append(
            {"val": round(sum(all_numeric_vals), 2), "desc": "Tổng giá trị các ô dữ liệu"}
        )
        if min_v > 0.001:
            derived_pool.append(
                {
                    "val": round(max_v / min_v, 1),
                    "desc": f"Tỷ lệ gấp cực đại / cực tiểu ({max_v} / {min_v})",
                }
            )
            derived_pool.append(
                {
                    "val": round(max_v / min_v, 2),
                    "desc": f"Tỷ lệ gấp cực đại / cực tiểu ({max_v} / {min_v})",
                }
            )
        sorted_all = sorted(all_numeric_vals, reverse=True)
        if len(sorted_all) >= 2:
            derived_pool.append(
                {
                    "val": round(sorted_all[0] - sorted_all[1], 2),
                    "desc": f"Chênh lệch hạng nhất - hạng nhì ({sorted_all[0]} - {sorted_all[1]})",
                }
            )

        # Intra-series deltas (first-to-last, phase deltas, step deltas)
        for s_name, vals in series_data.items():
            num_pts = [(idx, float(v)) for idx, v in enumerate(vals) if isinstance(v, (int, float))]
            for a_idx in range(len(num_pts)):
                for b_idx in range(a_idx + 1, len(num_pts)):
                    delta = round(abs(num_pts[b_idx][1] - num_pts[a_idx][1]), 2)
                    derived_pool.append(
                        {
                            "val": delta,
                            "desc": f"Biến động trong chuỗi '{s_name}' ({num_pts[a_idx][1]} -> {num_pts[b_idx][1]})",
                        }
                    )

        # Cross-series comparisons at the same category index
        series_lists = list(series_data.items())
        if len(series_lists) >= 2:
            max_len = max(len(v) for _, v in series_lists)
            for c_idx in range(max_len):
                at_idx = [
                    (sn, float(vs[c_idx]))
                    for sn, vs in series_lists
                    if c_idx < len(vs) and isinstance(vs[c_idx], (int, float))
                ]
                for i in range(len(at_idx)):
                    for j in range(i + 1, len(at_idx)):
                        gap = round(abs(at_idx[i][1] - at_idx[j][1]), 2)
                        derived_pool.append(
                            {
                                "val": gap,
                                "desc": f"Chênh lệch cùng mốc giữa '{at_idx[i][0]}' và '{at_idx[j][0]}'",
                            }
                        )

    levels_config = [
        ("Cấp 1: Tổng quan 5s", desc_dict.get("desc_5s", "")),
        ("Cấp 2: Tóm tắt sư phạm 30s", desc_dict.get("desc_30s", "")),
        ("Cấp 3: Phân tích học tập chuyên sâu", desc_dict.get("desc_study", "")),
    ]

    matched_items = []
    unmatched_items = []

    for level_name, level_text in levels_config:
        if not level_text:
            continue
        matches = list(re.finditer(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", level_text))
        for m in matches:
            raw_str = m.group(1)
            start_pos, end_pos = m.span()
            clean_val = clean_vietnamese_number(raw_str)
            if clean_val is None:
                continue

            c_start = max(0, level_text.rfind("\n", 0, start_pos) + 1)
            dot_before = level_text.rfind(". ", 0, start_pos)
            if dot_before != -1 and dot_before + 2 > c_start:
                c_start = dot_before + 2

            c_end = level_text.find("\n", end_pos)
            if c_end == -1:
                c_end = len(level_text)
            dot_after = level_text.find(". ", end_pos)
            if dot_after != -1 and dot_after + 1 < c_end:
                c_end = dot_after + 1

            snippet = level_text[c_start:c_end].strip()
            if len(snippet) > 130:
                rel_s = max(0, start_pos - c_start - 30)
                rel_e = min(len(snippet), (end_pos - c_start) + 30)
                snippet = (
                    ("..." if rel_s > 0 else "")
                    + snippet[rel_s:rel_e]
                    + ("..." if rel_e < len(snippet) else "")
                )

            matched = False
            match_type = ""
            gt_ref = ""

            for c_item in cell_pool:
                g = c_item["val"]
                abs_diff = abs(clean_val - g)
                rel_diff = abs_diff / abs(g) if abs(g) > 1e-6 else abs_diff
                if abs_diff <= 0.05 or rel_diff <= 0.05:
                    matched = True
                    match_type = "Ô số liệu bảng gốc (Data Cell)"
                    gt_ref = (
                        f"Khớp chuỗi '{c_item['series']}', mốc '{c_item['category']}': "
                        f"{g} (sai số {rel_diff*100:.2f}%)"
                    )
                    break

            if not matched:
                for cat_item in cat_pool:
                    if abs(clean_val - cat_item["val"]) < 0.01:
                        matched = True
                        match_type = "Nhãn mốc thời gian / Trục hoành"
                        gt_ref = f"Khớp danh mục '{cat_item['cat_name']}'"
                        break

            if not matched:
                for m_item in meta_pool:
                    if abs(clean_val - m_item["val"]) < 0.01:
                        matched = True
                        match_type = "Số cấu trúc / Siêu dữ liệu biểu đồ"
                        gt_ref = f"Khớp {m_item['desc']}"
                        break

            if not matched:
                for d_item in derived_pool:
                    d_g = d_item["val"]
                    abs_d = abs(clean_val - d_g)
                    rel_d = abs_d / abs(d_g) if abs(d_g) > 1e-6 else abs_d
                    if abs_d <= 0.05 or rel_d <= 0.05:
                        matched = True
                        match_type = "Số tính toán phái sinh hợp lệ từ bảng gốc"
                        gt_ref = f"Khớp phép tính {d_item['desc']}"
                        break

            item_data = {
                "level": level_name,
                "raw_str": raw_str,
                "clean_val": clean_val,
                "sentence": snippet,
                "match_type": match_type,
                "gt_ref": gt_ref,
            }

            if matched:
                matched_items.append(item_data)
            else:
                closest_cell = None
                min_rel_err = float("inf")
                for c_item in cell_pool:
                    g = c_item["val"]
                    err = abs(clean_val - g) / (abs(g) if abs(g) > 1e-6 else 1.0)
                    if err < min_rel_err:
                        min_rel_err = err
                        closest_cell = c_item

                if closest_cell and min_rel_err <= 0.35:
                    classification = "Lệch giá trị / Sai khác đơn vị (> 5% so với bảng)"
                    gt_explanation = (
                        f"Gần với ô '{closest_cell['series']}' - {closest_cell['category']} "
                        f"({closest_cell['val']}) nhưng sai số là {min_rel_err*100:.1f}% (> 5%)."
                    )
                else:
                    classification = "Số ngoài bảng (Chưa đối chuẩn / Nghi vấn ảo giác)"
                    gt_explanation = (
                        "Không tìm thấy trong bảng số liệu, trục tọa độ hay siêu dữ liệu biểu đồ."
                    )

                item_data["classification"] = classification
                item_data["gt_ref"] = gt_explanation
                unmatched_items.append(item_data)

    total_checked = len(matched_items) + len(unmatched_items)
    accuracy = (len(matched_items) / total_checked * 100.0) if total_checked > 0 else 100.0
    status_title = (
        "Đạt chuẩn ViChartFact (Khớp 100% - Zero-Hallucination)"
        if len(unmatched_items) == 0
        else f"Phát hiện {len(unmatched_items)} số lạ / chưa đối chuẩn"
    )

    return {
        "accuracy": accuracy,
        "total_checked": total_checked,
        "matched_count": len(matched_items),
        "unmatched_count": len(unmatched_items),
        "status_title": status_title,
        "cell_pool_count": len(cell_pool),
        "cat_pool_count": len(cat_pool),
        "meta_pool_count": len(meta_pool),
        "derived_pool_count": len(derived_pool),
        "matched_items": matched_items,
        "unmatched_items": unmatched_items,
    }


def _build_gt_matrix(gt_record: Dict[str, Any]) -> Dict[str, Any]:
    """Build normalized flagged matrix directly from a Ground Truth Benchmark row."""
    gt_clean = {
        "chart_title": normalize_text_nfc(gt_record.get("chart_title", "")),
        "chart_type": normalize_text_nfc(gt_record.get("chart_type", "column")),
        "unit": normalize_text_nfc(gt_record.get("unit", "")),
        "categories": normalize_text_nfc(gt_record.get("categories", "")),
        "series_name": normalize_text_nfc(gt_record.get("series_name", "")),
        "values": normalize_text_nfc(gt_record.get("values", "")),
    }
    _, notes, parsed = validate_chart_data(gt_clean)
    return apply_uncertainty_flagging(parsed, notes)


def fact_check_against_ground_truth(
    desc_dict: Dict[str, str], gt_record: Dict[str, Any], has_uncertainty: bool = False
) -> Dict[str, Any]:
    """
    End-to-End ViChartFact Evaluation against Benchmark Ground Truth.
    Checks whether numbers stated in the descriptions match the real Ground Truth table
    and tracks whether uncertainty flags were emitted cleanly when extraction failed.
    """
    gt_matrix = _build_gt_matrix(gt_record)
    res = fact_check_vichartfact(desc_dict, gt_matrix)
    full_text = " ".join(
        [
            desc_dict.get("desc_5s", ""),
            desc_dict.get("desc_30s", ""),
            desc_dict.get("desc_study", ""),
        ]
    ).lower()
    has_flag_in_text = ("[chưa chắc chắn]" in full_text) or ("chưa xác minh" in full_text)
    res["has_uncertainty_flag"] = has_flag_in_text or has_uncertainty
    return res


def _extract_meaningful_tokens(text: str) -> List[str]:
    cleaned = re.sub(r"[^\w\s]", " ", normalize_text_nfc(text).lower())
    return [tok for tok in cleaned.split() if len(tok) >= 2 and tok not in VN_STOPWORDS]


def _normalize_unit_variants(unit: str) -> List[str]:
    u = normalize_text_nfc(unit).lower()
    if not u or u in {"không có", "thiếu dữ liệu", "none", "nan"}:
        return []
    variants = {u}
    replacements = {
        "%": ["%", "phần trăm"],
        "tỉ": ["tỉ", "tỷ"],
        "tỷ": ["tỷ", "tỉ"],
        "km2": ["km2", "km²", "ki-lô-mét vuông"],
        "km²": ["km²", "km2", "ki-lô-mét vuông"],
        "usd": ["usd", "đô la mỹ", "đô"],
        "đô la mỹ": ["đô la mỹ", "usd", "đô"],
        "nghìn ha": ["nghìn ha", "nghin ha", "nghìn héc-ta"],
        "triệu tấn": ["triệu tấn", "trieu tan"],
        "triệu người": ["triệu người", "trieu nguoi"],
        "nghìn tấn": ["nghìn tấn", "nghin tan"],
        "°c": ["°c", "độ c"],
    }
    for key, vals in replacements.items():
        if key in u:
            for v in vals:
                variants.add(u.replace(key, v))
                variants.add(v)
    return [v for v in variants if v]


def _match_number_in_list(target: float, candidates: List[float]) -> bool:
    for val in candidates:
        abs_diff = abs(target - val)
        rel_diff = abs_diff / abs(val) if abs(val) > 1e-6 else abs_diff
        if abs_diff <= 0.05 or rel_diff <= 0.05:
            return True
    return False


def evaluate_description_completeness(
    desc_dict: Dict[str, str],
    gt_record: Dict[str, Any],
    has_uncertainty: bool = False,
) -> Dict[str, Any]:
    """
    Evaluate pedagogical completeness (0-100%) of generated descriptions against Ground Truth.
    Dimensions (25 points each):
      1. subject_unit_score (25): Chart type (10) + Topic/title tokens (7.5) + Unit match (7.5)
      2. scope_series_score (25): Category/time coverage (15) + Series/legend coverage (10)
      3. extremes_values_score (25): Max & Min GT values w/ context (12.5) + GT cell coverage (12.5)
      4. trend_analysis_score (25): Valid trend/composition/comparison (15) + Groundedness/no external cause hallucination (10)
    """
    desc_5s = normalize_text_nfc(desc_dict.get("desc_5s", ""))
    desc_30s = normalize_text_nfc(desc_dict.get("desc_30s", ""))
    desc_study = normalize_text_nfc(desc_dict.get("desc_study", ""))
    full_text = " ".join(p for p in [desc_5s, desc_30s, desc_study] if p).strip()
    full_lower = full_text.lower()

    if not full_text:
        return {
            "completeness_score": 0.0,
            "subject_unit_score": 0.0,
            "scope_series_score": 0.0,
            "extremes_values_score": 0.0,
            "trend_analysis_score": 0.0,
            "category_coverage_pct": 0.0,
            "series_coverage_pct": 0.0,
            "cell_coverage_pct": 0.0,
            "missing_aspects": ["Không có nội dung mô tả"],
        }

    gt_matrix = _build_gt_matrix(gt_record)
    gt_type = gt_matrix["chart_type"]
    gt_title = gt_matrix["chart_title"]
    gt_unit = gt_matrix["unit"]
    gt_cats = gt_matrix["categories"]
    gt_series = gt_matrix["series_names"]

    gt_vals: List[float] = []
    gt_series_lists: List[List[float]] = []
    for s_name in gt_series:
        s_nums = [v for v in gt_matrix["series_data"].get(s_name, []) if isinstance(v, (int, float))]
        gt_vals.extend(float(x) for x in s_nums)
        if s_nums:
            gt_series_lists.append([float(x) for x in s_nums])

    missing_aspects: List[str] = []

    # 1. Subject, Chart Type & Unit (25 pts)
    type_keywords = CHART_TYPE_LABELS_VN.get(gt_type, ["biểu đồ"])
    type_ok = any(kw in full_lower for kw in type_keywords)
    type_pts = 10.0 if type_ok else 0.0
    if not type_ok:
        missing_aspects.append(f"Thiếu/sai loại biểu đồ ({gt_type})")

    title_tokens = _extract_meaningful_tokens(gt_title)
    meaningless_gt_titles = {"", "thiếu tên biểu đồ", "không có tên", "biểu đồ không có tên", "chưa rõ"}
    if gt_title.lower() in meaningless_gt_titles or not title_tokens:
        # Must still mention subject or series/unit
        title_pts = 7.5 if ("thể hiện" in full_lower or "cơ cấu" in full_lower or "diễn biến" in full_lower) else 0.0
    else:
        hit_tokens = sum(1 for tok in title_tokens if tok in full_lower)
        title_ratio = hit_tokens / len(title_tokens)
        title_pts = round(7.5 * min(1.0, title_ratio / 0.5), 2)
        if title_pts < 5.0:
            missing_aspects.append("Chủ đề/tiêu đề chưa sát với biểu đồ gốc")

    unit_variants = _normalize_unit_variants(gt_unit)
    if not unit_variants:
        unit_pts = 7.5
    else:
        unit_ok = any(uv in full_lower for uv in unit_variants)
        unit_pts = 7.5 if unit_ok else 0.0
        if not unit_ok:
            missing_aspects.append(f"Thiếu hoặc sai đơn vị đo ({gt_unit})")

    subject_unit_score = round(type_pts + title_pts + unit_pts, 2)

    # 2. Scope, Categories & Series Coverage (25 pts)
    if gt_cats:
        cat_hits = 0
        for cat in gt_cats:
            cat_l = normalize_text_nfc(cat).lower()
            if cat_l and cat_l in full_lower:
                cat_hits += 1
            else:
                # Fallback check token overlap for multi-word categories
                c_toks = _extract_meaningful_tokens(cat_l)
                if c_toks and sum(1 for t in c_toks if t in full_lower) / len(c_toks) >= 0.7:
                    cat_hits += 1
        cat_cov = cat_hits / len(gt_cats)
        scope_pts = round(15.0 * cat_cov, 2)
        if cat_cov < 0.8:
            missing_aspects.append(f"Bao phủ danh mục/mốc trục hoành đạt {cat_hits}/{len(gt_cats)}")
    else:
        cat_cov = 1.0
        scope_pts = 15.0

    meaningful_series = [
        s for s in gt_series if s.strip() and s.strip().lower() not in {"giá trị", "số liệu", "chưa rõ"}
    ]
    if len(meaningful_series) >= 2:
        s_hits = 0
        for s_name in meaningful_series:
            s_l = s_name.lower()
            if s_l in full_lower:
                s_hits += 1
            else:
                s_toks = _extract_meaningful_tokens(s_l)
                if s_toks and sum(1 for t in s_toks if t in full_lower) / len(s_toks) >= 0.6:
                    s_hits += 1
        series_cov = s_hits / len(meaningful_series)
        series_pts = round(10.0 * series_cov, 2)
        if series_cov < 1.0:
            missing_aspects.append(f"Thiếu tên chuỗi chú giải ({s_hits}/{len(meaningful_series)})")
    elif len(meaningful_series) == 1:
        s_l = meaningful_series[0].lower()
        s_toks = _extract_meaningful_tokens(s_l)
        s_hit = (s_l in full_lower) or (
            bool(s_toks) and sum(1 for t in s_toks if t in full_lower) / len(s_toks) >= 0.5
        )
        series_cov = 1.0 if s_hit else 0.5
        series_pts = 10.0 if s_hit else 5.0
    else:
        series_cov = 1.0
        series_pts = 10.0

    scope_series_score = round(scope_pts + series_pts, 2)

    # 3. Quantitative Values & Max/Min Extremes (25 pts)
    mentioned_nums = [
        v
        for v in (
            clean_vietnamese_number(m.group(1))
            for m in re.finditer(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)", full_text)
        )
        if v is not None
    ]

    if gt_vals:
        gt_max = max(gt_vals)
        gt_min = min(gt_vals)
        has_max_num = _match_number_in_list(gt_max, mentioned_nums)
        has_min_num = _match_number_in_list(gt_min, mentioned_nums)
        has_max_kw = any(k in full_lower for k in ["cao nhất", "lớn nhất", "đạt đỉnh", "chạm đỉnh", "dẫn đầu", "chi phối"])
        has_min_kw = any(k in full_lower for k in ["thấp nhất", "nhỏ nhất", "đáy", "ít nhất"])

        max_pts = (4.0 if has_max_num else 0.0) + (2.25 if has_max_kw else 0.0)
        min_pts = (4.0 if has_min_num else 0.0) + (2.25 if has_min_kw else 0.0)

        matched_cells = sum(1 for gv in gt_vals if _match_number_in_list(gv, mentioned_nums))
        cell_cov = matched_cells / len(gt_vals)
        cell_pts = round(12.5 * cell_cov, 2)

        if not has_max_num or not has_min_num:
            missing_aspects.append("Chưa nêu đủ giá trị cực đại/cực tiểu thực tế")
        if cell_cov < 0.7:
            missing_aspects.append(f"Bao phủ ô số liệu gốc đạt {matched_cells}/{len(gt_vals)}")
    else:
        max_pts, min_pts, cell_cov, cell_pts = 6.25, 6.25, 1.0, 12.5

    extremes_values_score = round(max_pts + min_pts + cell_pts, 2)

    # 4. Trend / Structure Analysis & Pedagogical Grounding (25 pts)
    is_time_gt = len(gt_cats) >= 2 and all(
        re.search(r"\b(19\d{2}|20\d{2})\b", str(c)) for c in gt_cats
    )

    direction_pts = 0.0
    quant_comp_pts = 0.0

    if is_time_gt and gt_series_lists:
        main_vals = gt_series_lists[0]
        if len(main_vals) >= 2:
            net_gt = main_vals[-1] - main_vals[0]
            has_inc = any(k in full_lower for k in ["tăng", "đi lên", "tăng trưởng"])
            has_dec = any(k in full_lower for k in ["giảm", "đi xuống", "hạ"])
            has_flat = any(k in full_lower for k in ["ổn định", "đi ngang", "giữ nguyên", "dao động", "biến động"])
            if (net_gt > 0 and has_inc) or (net_gt < 0 and has_dec) or (abs(net_gt) < 1e-6 and has_flat) or has_flat:
                direction_pts = 8.0
            elif has_inc or has_dec:
                direction_pts = 4.0
        else:
            direction_pts = 8.0
        if any(k in full_lower for k in ["chênh lệch", "biên độ", "chặng", "gấp", "tăng thêm", "giảm ", "khoảng cách"]):
            quant_comp_pts = 7.0
    elif gt_type == "pie":
        if any(k in full_lower for k in ["cơ cấu", "tỷ trọng", "tỉ trọng", "chiếm"]):
            direction_pts = 8.0
        if any(k in full_lower for k in ["chênh lệch", "gấp", "tổng", "khoảng cách", "thứ bậc"]):
            quant_comp_pts = 7.0
    else:
        if any(k in full_lower for k in ["dẫn đầu", "so sánh", "chênh lệch", "vượt", "cao hơn", "thấp hơn", "phân hóa"]):
            direction_pts = 8.0
        if any(k in full_lower for k in ["khoảng cách", "biên độ", "gấp", "chênh lệch"]):
            quant_comp_pts = 7.0

    if direction_pts < 8.0 or quant_comp_pts < 7.0:
        missing_aspects.append("Chưa đủ phân tích xu hướng/cơ cấu hoặc đối chiếu định lượng")

    has_hallucinated_cause = any(p in full_lower for p in HALLUCINATED_CAUSE_PHRASES)
    has_flag_text = ("[chưa chắc chắn]" in full_lower) or ("chưa xác minh" in full_lower)
    grounding_pts = 10.0
    if has_hallucinated_cause:
        grounding_pts -= 5.0
        missing_aspects.append("Chứa suy diễn nguyên nhân ngoài dữ liệu bảng")
    if has_uncertainty and not has_flag_text:
        grounding_pts -= 5.0
        missing_aspects.append("Dữ liệu thiếu/lỗi nhưng chưa có cảnh báo [chưa chắc chắn]")

    trend_analysis_score = round(direction_pts + quant_comp_pts + max(0.0, grounding_pts), 2)

    total_score = round(
        subject_unit_score + scope_series_score + extremes_values_score + trend_analysis_score,
        2,
    )

    return {
        "completeness_score": min(100.0, max(0.0, total_score)),
        "subject_unit_score": subject_unit_score,
        "scope_series_score": scope_series_score,
        "extremes_values_score": extremes_values_score,
        "trend_analysis_score": trend_analysis_score,
        "category_coverage_pct": round(cat_cov * 100.0, 2),
        "series_coverage_pct": round(series_cov * 100.0, 2),
        "cell_coverage_pct": round(cell_cov * 100.0, 2),
        "missing_aspects": missing_aspects,
    }


def render_vichartfact_html(
    fact_res: Dict[str, Any],
    completeness_res: Optional[Dict[str, Any]] = None,
) -> str:
    """Render HTML report for ViChartFact Factuality and Pedagogical Completeness."""
    acc = fact_res["accuracy"]
    tot = fact_res["total_checked"]
    m_cnt = fact_res["matched_count"]
    u_cnt = fact_res["unmatched_count"]
    cell_cnt = fact_res["cell_pool_count"]
    cat_cnt = fact_res["cat_pool_count"]
    unmatched_pct = max(0.0, 100.0 - acc)

    if u_cnt == 0:
        icon_box_bg = "#DEF7EC"
        icon_box_color = "#03543F"
        badge_bg = "#0E9F6E"
        badge_color = "#FFFFFF"
        badge_border = "#0E9F6E"
        badge_icon = "✓"
        badge_text = "100% Zero-Hallucination"
        conclusion_html = f"""
        <div style="background-color: #DEF7EC; border: 1px solid #BCF0DA; border-radius: 8px; padding: 14px 18px; display: flex; align-items: flex-start; gap: 12px; margin-top: 14px;">
            <span style="font-size: 20px; color: #03543F; line-height: 1.2; flex-shrink: 0;">✓</span>
            <p style="margin: 0; font-size: 13.5px; color: #03543F; line-height: 1.55;">
                <strong style="font-weight: 700;">Kết luận đối kiểm:</strong> Toàn bộ <b>{m_cnt}/{tot}</b> giá trị số xuất hiện trong cả 3 cấp mô tả đều khớp hoàn toàn với bảng số liệu đã kiểm chứng (sai số tối đa 5%) và nhãn trục biểu đồ. Không phát hiện bất kỳ số lạ hay hiện tượng ảo giác nào.
            </p>
        </div>
        """
        unmatched_table_html = ""
    else:
        icon_box_bg = "#FDE8E8"
        icon_box_color = "#9B1C1C"
        badge_bg = "#E02424"
        badge_color = "#FFFFFF"
        badge_border = "#E02424"
        badge_icon = "⚠️"
        badge_text = f"Cảnh báo: Phát hiện {u_cnt} số lạ"
        conclusion_html = f"""
        <div style="background-color: #FEF7E0; border: 1px solid #FAD2CF; border-left: 5px solid #C5221F; border-radius: 8px; padding: 14px 18px; display: flex; align-items: flex-start; gap: 12px; margin-top: 14px;">
            <span style="font-size: 20px; color: #C5221F; line-height: 1.2; flex-shrink: 0;">⚠️</span>
            <p style="margin: 0; font-size: 13.5px; color: #8A4B00; line-height: 1.55;">
                <strong style="font-weight: 700; color: #C5221F;">Kết luận đối kiểm:</strong> Phát hiện <b>{u_cnt} giá trị số</b> trong mô tả chưa đối chuẩn được với bảng số liệu gốc (Độ trung thực: <b>{acc:.1f}%</b>). <b>Tuyệt đối không xác nhận Zero-Hallucination</b> cho đến khi các số lạ này được rà soát và đối chuẩn. Vui lòng xem bảng chi tiết bên dưới.
            </p>
        </div>
        """
        rows_html = []
        for u in fact_res["unmatched_items"]:
            raw_esc = html.escape(u["raw_str"])
            sent_esc = html.escape(u["sentence"])
            highlighted_sent = sent_esc.replace(
                raw_esc,
                f"<mark style='background-color: #FAD2CF; color: #C5221F; font-weight: bold; padding: 1px 4px; border-radius: 3px;'>{raw_esc}</mark>",
            )
            lvl_display = html.escape(u["level"])
            if "Cấp 1" in lvl_display:
                lvl_display = "Cấp 1 (5s)"
            elif "Cấp 2" in lvl_display:
                lvl_display = "Cấp 2 (30s)"
            elif "Cấp 3" in lvl_display:
                lvl_display = "Cấp 3 (Chi tiết)"

            rows_html.append(
                f"""
            <tr style="border-bottom: 1px solid #FDE8E8; font-size: 12.5px;">
                <td style="padding: 9px 12px; font-weight: 700; color: #1A40C2; border-right: 1px solid #FDE8E8; white-space: nowrap;">{lvl_display}</td>
                <td style="padding: 9px 12px; border-right: 1px solid #FDE8E8; white-space: nowrap;"><code style="background: #FDE8E8; color: #9B1C1C; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-family: monospace;">{raw_esc}</code><br><span style="font-size: 11px; color: #6B7280;">(giá trị: {u['clean_val']})</span></td>
                <td style="padding: 9px 12px; border-right: 1px solid #FDE8E8; line-height: 1.45; color: #374151;">{highlighted_sent}</td>
                <td style="padding: 9px 12px; border-right: 1px solid #FDE8E8; font-size: 12px; color: #4B5563; line-height: 1.45;">{html.escape(u['gt_ref'])}</td>
                <td style="padding: 9px 12px; font-weight: 700; color: #C5221F; font-size: 12px;">{html.escape(u['classification'])}</td>
            </tr>
            """
            )
        unmatched_table_html = f"""
        <div style="margin-top: 14px; border: 1px solid #F8B4B4; border-radius: 8px; overflow: hidden; background: #FFFFFF;">
            <div style="padding: 10px 14px; background: #FDE8E8; border-bottom: 1px solid #F8B4B4; font-weight: 700; color: #9B1C1C; font-size: 13.5px; display: flex; align-items: center; gap: 8px;">
                <span>🔍</span>
                <span>Danh sách chi tiết các giá trị số lạ / chưa đối chuẩn ({u_cnt} mục):</span>
            </div>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; background: #FFFFFF; text-align: left;">
                    <thead>
                        <tr style="background-color: #FDF2F2; color: #9B1C1C; border-bottom: 1px solid #F8B4B4; font-size: 12px;">
                            <th style="padding: 8px 12px; border-right: 1px solid #F8B4B4; white-space: nowrap;">Cấp mô tả</th>
                            <th style="padding: 8px 12px; border-right: 1px solid #F8B4B4; white-space: nowrap;">Số bắt được</th>
                            <th style="padding: 8px 12px; border-right: 1px solid #F8B4B4;">Ngữ cảnh trong câu</th>
                            <th style="padding: 8px 12px; border-right: 1px solid #F8B4B4;">Kết quả đối chiếu bảng gốc</th>
                            <th style="padding: 8px 12px; white-space: nowrap;">Nguyên nhân &amp; Phân loại</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(rows_html)}
                    </tbody>
                </table>
            </div>
        </div>
        """

    completeness_html = ""
    if completeness_res is not None:
        comp_score = completeness_res["completeness_score"]
        comp_color = "#0E9F6E" if comp_score >= 85 else ("#D97706" if comp_score >= 60 else "#E02424")
        missing_list = completeness_res.get("missing_aspects", [])
        missing_note = (
            "Đạt đủ 4 tiêu chí sư phạm (chủ thể/đơn vị, phạm vi/chuỗi, cực trị/số liệu, phân tích xu hướng)."
            if not missing_list
            else "Điểm cần lưu ý: " + "; ".join(html.escape(m) for m in missing_list)
        )
        completeness_html = f"""
        <div style="margin-top: 14px; border: 1px solid #E2E6F0; border-radius: 8px; padding: 14px 16px; background: #F8F9FC;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <span style="font-weight: 700; font-size: 13.5px; color: #1E293B;">📐 Độ Đầy Đủ Mô Tả Sư Phạm (Completeness Score)</span>
                <span style="font-size: 18px; font-weight: 800; color: {comp_color};">{comp_score:.1f}%</span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; font-size: 12px;">
                <div style="background: #FFFFFF; border: 1px solid #E2E6F0; border-radius: 6px; padding: 8px 10px;">
                    <div style="color: #64748B;">Chủ thể &amp; Đơn vị</div>
                    <div style="font-weight: 700; color: #1E293B; font-size: 14px;">{completeness_res['subject_unit_score']:.1f} / 25</div>
                </div>
                <div style="background: #FFFFFF; border: 1px solid #E2E6F0; border-radius: 6px; padding: 8px 10px;">
                    <div style="color: #64748B;">Phạm vi &amp; Chuỗi</div>
                    <div style="font-weight: 700; color: #1E293B; font-size: 14px;">{completeness_res['scope_series_score']:.1f} / 25</div>
                </div>
                <div style="background: #FFFFFF; border: 1px solid #E2E6F0; border-radius: 6px; padding: 8px 10px;">
                    <div style="color: #64748B;">Cực trị &amp; Số liệu</div>
                    <div style="font-weight: 700; color: #1E293B; font-size: 14px;">{completeness_res['extremes_values_score']:.1f} / 25</div>
                </div>
                <div style="background: #FFFFFF; border: 1px solid #E2E6F0; border-radius: 6px; padding: 8px 10px;">
                    <div style="color: #64748B;">Xu hướng &amp; Sư phạm</div>
                    <div style="font-weight: 700; color: #1E293B; font-size: 14px;">{completeness_res['trend_analysis_score']:.1f} / 25</div>
                </div>
            </div>
            <div style="margin-top: 8px; font-size: 12.5px; color: #475569;">{missing_note}</div>
        </div>
        """

    matched_rows_html = []
    for m in fact_res["matched_items"]:
        lvl_display = html.escape(m["level"])
        if "Cấp 1" in lvl_display:
            lvl_display = "Cấp 1 (5s)"
        elif "Cấp 2" in lvl_display:
            lvl_display = "Cấp 2 (30s)"
        elif "Cấp 3" in lvl_display:
            lvl_display = "Cấp 3 (Chi tiết)"

        mtype_display = html.escape(m["match_type"])
        if "Ô số liệu" in mtype_display:
            mtype_display = "Ô số liệu bảng gốc"
        elif "Nhãn mốc" in mtype_display:
            mtype_display = "Mốc thời gian / Trục hoành"
        elif "Số cấu trúc" in mtype_display:
            mtype_display = "Cấu trúc biểu đồ"
        elif "Số tính toán" in mtype_display:
            mtype_display = "Phép tính suy luận"

        matched_rows_html.append(
            f"""
        <tr style="border-bottom: 1px solid #F1F5F9; font-size: 12.5px;">
            <td style="padding: 8px 14px; font-weight: 600; color: #1E293B; white-space: nowrap;">{lvl_display}</td>
            <td style="padding: 8px 14px; white-space: nowrap;">
                <code style="background: #DEF7EC; color: #03543F; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: monospace;">{html.escape(m['raw_str'])}</code>
            </td>
            <td style="padding: 8px 14px; color: #1A40C2; font-weight: 600; white-space: nowrap;">{mtype_display}</td>
            <td style="padding: 8px 14px; color: #475569; line-height: 1.45;">{html.escape(m['gt_ref'])}</td>
        </tr>
        """
        )

    matched_details_html = f"""
    <details open class="v-fact-details" style="border: 1px solid #E2E6F0; border-radius: 8px; background: #FFFFFF; overflow: hidden; margin-top: 14px;">
        <summary style="padding: 12px 16px; background-color: #F8F9FC; border-bottom: 1px solid #E2E6F0; display: flex; align-items: center; justify-content: space-between; cursor: pointer; user-select: none; font-weight: 700; font-size: 13.5px; color: #1E293B;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="color: #1A40C2; font-size: 16px;">📋</span>
                <span>Bảng đối chiếu chi tiết ({m_cnt} giá trị khớp hợp lệ)</span>
            </div>
            <span class="v-expand-icon">▼</span>
        </summary>
        <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 12.5px; text-align: left;">
                <thead style="background: #F8F9FC; border-bottom: 1px solid #E2E6F0; color: #475569;">
                    <tr>
                        <th style="padding: 10px 14px; font-weight: 700; white-space: nowrap;">Cấp mô tả</th>
                        <th style="padding: 10px 14px; font-weight: 700; white-space: nowrap;">Giá trị / Số bắt được</th>
                        <th style="padding: 10px 14px; font-weight: 700; white-space: nowrap;">Loại đối chiếu</th>
                        <th style="padding: 10px 14px; font-weight: 700;">Kết quả kiểm tra</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(matched_rows_html)}
                </tbody>
            </table>
        </div>
    </details>
    """

    rules_formula_html = """
    <details class="v-fact-details" style="border: 1px solid #E2E6F0; border-radius: 8px; background: #FFFFFF; overflow: hidden; margin-top: 14px;">
        <summary style="padding: 12px 16px; background-color: #F8F9FC; border-bottom: 1px solid #E2E6F0; display: flex; align-items: center; justify-content: space-between; cursor: pointer; user-select: none; font-weight: 700; font-size: 13.5px; color: #1E293B;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="color: #4F46E5; font-size: 16px;">📖</span>
                <span>Quy chuẩn &amp; Công thức kiểm định ViChartFact &amp; Độ đầy đủ</span>
            </div>
            <span class="v-expand-icon">▼</span>
        </summary>
        <div style="padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; font-size: 13.5px; color: #475569; line-height: 1.6; background: #FFFFFF;">
            <div>
                <h4 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 700; color: #0F172A;">
                    1. Độ trung thực số liệu (ViChartFact Factuality)
                </h4>
                <p style="margin: 0 0 6px 0;">
                    Tính bằng số giá trị số khớp bảng gốc (sai số tương đối ≤ 5% hoặc tuyệt đối ≤ 0,05) chia cho tổng số giá trị số đối chiếu trong mô tả:
                </p>
                <div style="display: inline-block; padding: 6px 12px; background: #F1F5F9; border-radius: 6px; font-weight: 700; color: #1E293B; font-size: 13px;">
                    ViChartFact = (Số giá trị khớp / Tổng số giá trị đối chiếu) × 100%
                </div>
            </div>
            <div style="border-top: 1px solid #F1F5F9; padding-top: 12px;">
                <h4 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 700; color: #0F172A;">
                    2. Độ đầy đủ mô tả sư phạm (Completeness Score)
                </h4>
                <p style="margin: 0;">
                    Đánh giá trên 4 trụ cột (mỗi trụ cột 25 điểm): (1) Loại biểu đồ, chủ đề và đơn vị; (2) Bao phủ các mốc trục hoành và chuỗi chú giải; (3) Nêu đúng cực trị Max/Min và tỷ lệ bao phủ ô số liệu; (4) Phân tích đúng xu hướng/cơ cấu và không suy diễn nguyên nhân ngoài dữ liệu.
                </p>
            </div>
        </div>
    </details>
    """

    return f"""
    <div style="background-color: #FFFFFF; border: 1px solid #E2E6F0; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; flex-direction: column; gap: 4px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; margin-bottom: 16px;">
            <div style="display: flex; align-items: flex-start; gap: 12px; min-width: 0;">
                <div style="width: 40px; height: 40px; border-radius: 8px; background-color: {icon_box_bg}; color: {icon_box_color}; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-size: 20px;">
                    🛡️
                </div>
                <div>
                    <h3 style="margin: 0; font-size: 18px; font-weight: 800; color: #1E293B; letter-spacing: -0.3px;">
                        3. Kiểm Định ViChartFact
                    </h3>
                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #64748B;">
                        Đánh giá độ trung thực số liệu và độ đầy đủ sư phạm của mô tả biểu đồ.
                    </p>
                </div>
            </div>
            <span style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 9999px; background-color: {badge_bg}; color: {badge_color}; border: 1px solid {badge_border}; font-size: 12.5px; font-weight: 700; white-space: nowrap;">
                <span>{badge_icon}</span>
                <span>{badge_text}</span>
            </span>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 6px;">
            <div style="border-radius: 8px; background: #F8F9FC; border: 1px solid #E2E6F0; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px;">
                <span style="font-size: 12px; font-weight: 600; color: #64748B; text-transform: uppercase;">Số liệu khớp bảng gốc</span>
                <span style="font-size: 26px; font-weight: 800; color: #1A40C2; font-variant-numeric: tabular-nums;">{m_cnt} / {tot}</span>
                <span style="font-size: 12px; color: #64748B;">{cell_cnt} ô số liệu, {cat_cnt} nhãn trục</span>
            </div>
            <div style="border-radius: 8px; background: #F8F9FC; border: 1px solid #E2E6F0; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px;">
                <span style="font-size: 12px; font-weight: 600; color: #64748B; text-transform: uppercase;">Độ trung thực Factuality</span>
                <span style="font-size: 26px; font-weight: 800; color: {'#0E9F6E' if acc >= 90 else '#D97706'}; font-variant-numeric: tabular-nums;">{acc:.1f}%</span>
                <span style="font-size: 12px; color: #64748B;">Sai số cho phép tối đa 5%</span>
            </div>
            <div style="border-radius: 8px; background: #F8F9FC; border: 1px solid #E2E6F0; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px;">
                <span style="font-size: 12px; font-weight: 600; color: #64748B; text-transform: uppercase;">Tỷ lệ sai lệch / số lạ</span>
                <span style="font-size: 26px; font-weight: 800; color: {'#0E9F6E' if u_cnt == 0 else '#E02424'}; font-variant-numeric: tabular-nums;">{unmatched_pct:.1f}%</span>
                <span style="font-size: 12px; color: #64748B;">{u_cnt} số lạ bị gắn cờ</span>
            </div>
        </div>

        {conclusion_html}
        {completeness_html}
        {unmatched_table_html}
        {matched_details_html}
        {rules_formula_html}
    </div>
    """
