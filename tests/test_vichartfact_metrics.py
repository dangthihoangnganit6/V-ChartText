import pandas as pd
import pytest

from vichartfact_metrics import (
    apply_uncertainty_flagging,
    clean_vietnamese_number,
    evaluate_description_completeness,
    fact_check_against_ground_truth,
    fact_check_vichartfact,
    generate_3level_descriptions,
    normalize_chart_type,
    validate_chart_data,
)


def test_clean_vietnamese_number_thousands_and_decimals():
    assert clean_vietnamese_number("1.200") == 1200.0
    assert clean_vietnamese_number("19.257") == 19257.0
    assert clean_vietnamese_number("12,5%") == 12.5
    assert clean_vietnamese_number("0,8") == 0.8
    assert clean_vietnamese_number("[chưa chắc chắn]") is None
    assert clean_vietnamese_number("{'category': '2021', 'value': 2478}") is None


def test_validate_pie_sum_and_year_monotonicity():
    pie_bad = {
        "chart_title": "Cơ cấu nguồn điện",
        "chart_type": "pie",
        "unit": "%",
        "categories": "Thủy điện | Nhiệt điện | Khác",
        "series_name": "Tỷ trọng",
        "values": "30 | 40 | 10",
    }
    status, notes, parsed = validate_chart_data(pie_bad)
    flagged = apply_uncertainty_flagging(parsed, notes)
    assert status == "Cần kiểm tra"
    assert flagged["has_uncertainty"] is True

    line_bad_years = {
        "chart_title": "Xu hướng",
        "chart_type": "line",
        "unit": "triệu tấn",
        "categories": "2020 | 2015 | 2022",
        "series_name": "Sản lượng",
        "values": "10 | 20 | 30",
    }
    status2, notes2, _ = validate_chart_data(line_bad_years)
    assert status2 == "Cần kiểm tra"
    assert "không tăng dần" in notes2


def test_dict_formatted_values_and_empty_series_no_crash():
    rec = {
        "chart_title": "Xuất - Nhập Khẩu Hàng Hóa qua Các Năm",
        "chart_type": "cột ghép",
        "unit": "tỷ đô la Mỹ",
        "categories": "2000 | 2002 | 2005 | 2007",
        "series_name": "Xuất Khẩu | Nhập Khẩu | Nhập Siêu",
        "values": (
            "{'series_name': 'Xuất Khẩu', 'values': [{'year': '2000', 'value': 14.5}, "
            "{'year': '2002', 'value': 15.6}, {'year': '2005', 'value': 32.4}, {'year': '2007', 'value': 62.8}]} | "
            "{'series_name': 'Nhập Khẩu', 'values': [{'year': '2000', 'value': 14.5}, "
            "{'year': '2002', 'value': 19.7}, {'year': '2005', 'value': 36.8}, {'year': '2007', 'value': 48.6}]} | "
            "{'series_name': 'Nhập Siêu', 'values': [{'year': '2000', 'value': 14.5}, "
            "{'year': '2002', 'value': 14.5}, {'year': '2005', 'value': 14.5}, {'year': '2007', 'value': 14.5}]}"
        ),
    }
    _, notes, parsed = validate_chart_data(rec)
    flagged = apply_uncertainty_flagging(parsed, notes)
    descs = generate_3level_descriptions(flagged)
    fc = fact_check_vichartfact(descs, flagged)
    assert fc["accuracy"] == 100.0
    assert fc["unmatched_count"] == 0

    # All-None multi-series time chart should not raise IndexError
    all_missing = {
        "chart_title": "Biểu đồ mờ",
        "chart_type": "line",
        "unit": "%",
        "categories": "2010 | 2015 | 2020",
        "series_name": "A | B",
        "values": "None | None | None || None | None | None",
    }
    _, n_m, p_m = validate_chart_data(all_missing)
    f_m = apply_uncertainty_flagging(p_m, n_m)
    d_m = generate_3level_descriptions(f_m)
    assert "[chưa chắc chắn]" in d_m["desc_30s"] or "chưa xác minh" in d_m["desc_5s"]


def test_vichartfact_detects_hallucination_and_series_numbers():
    gt = {
        "chart_title": "Cơ cấu GDP",
        "chart_type": "pie",
        "unit": "%",
        "categories": "Nông nghiệp | Công nghiệp | Dịch vụ",
        "series_name": "Năm 2005 || Năm 2015",
        "values": "20 | 40 | 40 || 17 | 38 | 45",
    }
    _, notes, parsed = validate_chart_data(gt)
    flagged = apply_uncertainty_flagging(parsed, notes)
    descs = generate_3level_descriptions(flagged)
    fc = fact_check_vichartfact(descs, flagged)
    assert fc["accuracy"] == 100.0

    hallucinated = {
        "desc_5s": "Biểu đồ tròn cơ cấu GDP năm 2005 (đơn vị: %).",
        "desc_30s": "Dịch vụ đạt 999% do kinh tế phát triển.",
        "desc_study": "",
    }
    fc_bad = fact_check_against_ground_truth(hallucinated, gt)
    assert fc_bad["unmatched_count"] >= 1
    assert fc_bad["accuracy"] < 100.0

    comp_bad = evaluate_description_completeness(hallucinated, gt)
    comp_good = evaluate_description_completeness(descs, gt)
    assert comp_good["completeness_score"] > comp_bad["completeness_score"]
    assert comp_good["completeness_score"] >= 90.0


def test_all_213_extracted_rows_pass_grounded_vichartfact():
    df = pd.read_csv("data/vcharttext_extracted_results.csv")
    failures = []
    for _, r in df.iterrows():
        step1 = {
            k: ("" if pd.isna(r.get(k)) else str(r.get(k)))
            for k in ["chart_title", "chart_type", "unit", "x_axis_label", "categories", "series_name", "values"]
        }
        _, notes, parsed = validate_chart_data(step1)
        flagged = apply_uncertainty_flagging(parsed, notes)
        descs = generate_3level_descriptions(flagged)
        fc = fact_check_vichartfact(descs, flagged)
        if fc["unmatched_count"] > 0:
            failures.append((r["image_name"], fc["unmatched_items"]))
    assert failures == []
