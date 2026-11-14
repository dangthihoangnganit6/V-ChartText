"""Gán nhãn bằng Excel thay vì sửa JSON bằng tay.

  python src/labeling_xlsx.py export            # data/labels/*.json -> data/labeling/nhan_<người>.xlsx
  python src/labeling_xlsx.py import            # data/labeling/*.xlsx -> data/labels/*.json (ảnh "xong" / "bỏ")
  python eval/validate_labels.py                # luôn chạy sau import

export KHÔNG ghi đè file Excel đã có (tránh mất công gán); thêm --force nếu thật sự muốn tạo lại.
Mỗi người một file nên không bị xung đột khi đẩy lên GitHub. Cần: pip install openpyxl
"""
import argparse
import json
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
from vn_number import parse_vn  # noqa: E402

LABELS = Path("data/labels")
OUTDIR = Path("data/labeling")
N_POINT_ROWS = 2000          # số dòng trống định dạng sẵn trong sheet DiemDuLieu

TYPES = ["bar", "line", "pie", "combo", "area", "other"]
STATUS = ["chưa", "xong", "bỏ"]
SUBJECTS = ["dia_li", "lich_su", "khac"]
SOURCES = ["sgk", "sbt", "on_thi", "atlat", "khac"]
YESNO = ["có", "không"]
REVIEW = ["chưa", "đạt", "đã sửa"]

# (khoá, tiêu đề cột, độ rộng, ô nhập?, gợi ý)
CHART_COLS = [
    ("id", "id", 11, False, "Không sửa"),
    ("img", "Ảnh", 9, False, "Bấm để mở ảnh (file phải nằm trong thư mục data/labeling của repo)"),
    ("chart_type", "Loại", 8, True, "bar | line | pie | combo | area | other. Đã điền theo thư mục Drive, sửa nếu sai"),
    ("status", "Trạng thái", 10, True, "chưa / xong / bỏ. Chỉ dòng 'xong' và 'bỏ' được import"),
    ("subject", "Môn", 9, True, "dia_li / lich_su / khac"),
    ("src_type", "Nguồn", 9, True, "sgk / sbt / on_thi / atlat / khac"),
    ("book", "Sách", 22, True, "Vd: Địa lí 12 - Kết nối tri thức"),
    ("page", "Trang", 7, True, "Số trang"),
    ("url", "URL", 18, True, "Link nếu lấy từ web"),
    ("title", "Tiêu đề", 40, True, "Chép nguyên văn; bỏ phần 'Hình 34.3.' ở đầu; ảnh không có tiêu đề thì để trống"),
    ("x_label", "Trục x: tên", 12, True, "Tên đại lượng ghi ở trục hoành, vd 'Năm', 'Nước'. Không có thì để trống"),
    ("x_unit", "Trục x: đơn vị", 10, True, "Thường để trống"),
    ("y_label", "Trục y: tên", 14, True, "Vd 'Tỉ trọng'. Trục chỉ ghi đơn vị thì để trống"),
    ("y_unit", "Trục y: đơn vị", 12, True, "Chép đúng như ảnh: 'Nghìn km', 'Tỉ đồng', '%'. Biểu đồ tròn: '%'"),
    ("y2_label", "Trục y2: tên", 12, True, "Chỉ cho biểu đồ 2 trục tung (trục phải)"),
    ("y2_unit", "Trục y2: đơn vị", 12, True, "Chỉ cho biểu đồ 2 trục tung (trục phải)"),
    ("legend", "Chú giải (cách nhau bởi |)", 30, True, "Vd: Khai thác | Nuôi trồng. Biểu đồ một chuỗi không có chú giải: để trống"),
    ("values_shown", "Có ghi số trên hình?", 10, True, "có: số in trên cột/điểm; không: phải đọc theo vạch chia"),
    ("notes", "Ghi chú", 30, True, "Điều gì bất thường: ảnh mờ, số khó đọc, ước lượng..."),
    ("reviewer", "Người kiểm tra chéo", 11, True, "ngan / nhi / giang (người KHÁC người gán)"),
    ("review", "Kết quả kiểm tra", 10, True, "chưa / đạt / đã sửa"),
    ("n_points", "Số điểm", 7, False, "Tự đếm từ sheet DiemDuLieu"),
    ("warn", "Cảnh báo", 24, False, "Tự kiểm tra; phải trống trước khi import"),
    ("original_file", "Tệp gốc trên Drive", 36, False, "Không sửa"),
]
POINT_COLS = [
    ("id", "id", 11, True, "Chọn id biểu đồ (danh sách thả xuống)"),
    ("series", "series", 28, True, "Tên chuỗi = một mục trong chú giải. Một chuỗi không chú giải: tên đại lượng (vd 'Sản lượng lúa'). "
                                    "Tròn 1 vòng: để trống (tự lấy bằng x)"),
    ("x", "x", 16, True, "Nhãn trục hoành (năm, tên nước...). Tròn: tên phần"),
    ("y_raw", "y_raw (như trên ảnh)", 14, True, "Chép ĐÚNG như ảnh, kiểu Việt Nam: 1.200 ; 12,5 ; 6 586,6. Ô đã để dạng chữ"),
    ("axis", "Trục (y/y2)", 8, True, "Chỉ cho biểu đồ 2 trục tung; để trống = y"),
    ("estimated", "Ước lượng?", 9, True, "'có' nếu ảnh không ghi số, phải đọc theo vạch chia"),
    ("y", "y (tự tính)", 12, False, "Số máy hiểu được, để soát. 'LỖI' = y_raw viết sai"),
]

ARIAL = "Arial"
F_BODY = Font(name=ARIAL, size=10)
F_HEAD = Font(name=ARIAL, size=10, bold=True)
FILL_IN = PatternFill("solid", fgColor="FFF2CC")       # ô cần nhập
FILL_LOCK = PatternFill("solid", fgColor="E7E6E6")     # ô không sửa / tự tính
FILL_HEAD_IN = PatternFill("solid", fgColor="FFD966")
FILL_HEAD_LOCK = PatternFill("solid", fgColor="BFBFBF")
THIN = Border(bottom=Side(style="thin", color="BFBFBF"))


def col_letter(i):
    from openpyxl.utils import get_column_letter
    return get_column_letter(i)


def header(ws, cols):
    for j, (_, title, width, is_in, tip) in enumerate(cols, 1):
        c = ws.cell(row=1, column=j, value=title)
        c.font = F_HEAD
        c.fill = FILL_HEAD_IN if is_in else FILL_HEAD_LOCK
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.comment = Comment(tip, "V-ChartText")
        ws.column_dimensions[col_letter(j)].width = width
    ws.row_dimensions[1].height = 42
    ws.freeze_panes = "C2" if cols is CHART_COLS else "B2"


def add_list(ws, values, rng, title):
    dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True,
                        showErrorMessage=True, errorTitle=title, error="Chọn một giá trị trong danh sách")
    dv.add(rng)
    ws.add_data_validation(dv)


def chart_row(rec):
    src = rec.get("source") or {}
    xa, ya, y2 = rec.get("x_axis") or {}, rec.get("y_axis") or {}, rec.get("y2_axis") or {}
    vs = rec.get("values_shown_on_chart")
    review = rec.get("review") or {}
    if rec.get("status") == "todo":
        st = "chưa"
    elif rec.get("status") == "excluded":
        st = "bỏ"
    else:
        st = "xong"
    return {
        "id": rec["id"], "chart_type": rec.get("chart_type"), "status": st, "subject": rec.get("subject"),
        "src_type": src.get("type"), "book": src.get("book"), "page": src.get("page"), "url": src.get("url"),
        "title": rec.get("title") or None, "x_label": xa.get("label"), "x_unit": xa.get("unit"),
        "y_label": ya.get("label"), "y_unit": ya.get("unit"), "y2_label": y2.get("label"), "y2_unit": y2.get("unit"),
        "legend": " | ".join(rec.get("legend") or []) or None,
        "values_shown": None if vs is None else ("có" if vs else "không"),
        "notes": rec.get("notes") or None, "reviewer": review.get("by"), "review": review.get("result"),
        "original_file": src.get("original_file"),
    }


def build(name, recs, path):
    wb = Workbook()
    guide = wb.active
    guide.title = "Huong_dan"
    ws = wb.create_sheet("BieuDo")
    wp = wb.create_sheet("DiemDuLieu")
    header(ws, CHART_COLS)
    header(wp, POINT_COLS)
    key_c = {k: j for j, (k, *_rest) in enumerate(CHART_COLS, 1)}
    key_p = {k: j for j, (k, *_rest) in enumerate(POINT_COLS, 1)}
    L = lambda cols, k: col_letter(cols[k])  # noqa: E731

    # ---- sheet BieuDo
    n = len(recs)
    last_c = n + 1
    for i, rec in enumerate(recs, 2):
        vals = chart_row(rec)
        for k, j in key_c.items():
            c = ws.cell(row=i, column=j)
            is_in = CHART_COLS[j - 1][3]
            if k == "img":
                img = Path(rec["image"]).name
                c.value = "mở ảnh"
                c.hyperlink = f"../images/{img}"
                c.font = Font(name=ARIAL, size=10, color="0563C1", underline="single")
            elif k == "n_points":
                pid = f"DiemDuLieu!${L(key_p, 'id')}:${L(key_p, 'id')}"
                c.value = f"=COUNTIF({pid},{L(key_c, 'id')}{i})"
                c.font = F_BODY
            elif k == "warn":
                c.value = _warn_formula(i, key_c, key_p, L)
                c.font = Font(name=ARIAL, size=10, color="C00000")
            else:
                c.value = vals.get(k)
                c.font = F_BODY
                c.number_format = "@" if k not in ("page",) else "General"
            c.fill = FILL_IN if is_in else FILL_LOCK
            c.border = THIN
    rng = lambda k: f"{L(key_c, k)}2:{L(key_c, k)}{last_c}"  # noqa: E731
    add_list(ws, TYPES, rng("chart_type"), "Loại biểu đồ")
    add_list(ws, STATUS, rng("status"), "Trạng thái")
    add_list(ws, SUBJECTS, rng("subject"), "Môn")
    add_list(ws, SOURCES, rng("src_type"), "Nguồn")
    add_list(ws, YESNO, rng("values_shown"), "Có ghi số")
    add_list(ws, ["ngan", "nhi", "giang"], rng("reviewer"), "Người kiểm tra")
    add_list(ws, REVIEW, rng("review"), "Kết quả kiểm tra")
    st = rng("status")
    first = f"${L(key_c, 'status')}2"
    ws.conditional_formatting.add(st, FormulaRule(formula=[f'{first}="xong"'], fill=PatternFill("solid", fgColor="C6EFCE")))
    ws.conditional_formatting.add(st, FormulaRule(formula=[f'{first}="bỏ"'], fill=PatternFill("solid", fgColor="D9D9D9")))
    ws.auto_filter.ref = f"A1:{col_letter(len(CHART_COLS))}{last_c}"

    # ---- sheet DiemDuLieu
    pts = [(rec["id"], d) for rec in recs if rec.get("status") not in ("todo",) for d in rec.get("data") or []]
    last_p = len(pts) + N_POINT_ROWS + 1
    for i in range(2, last_p + 1):
        cid, d = pts[i - 2] if i - 2 < len(pts) else (None, {})
        series = d.get("series")
        if series is not None and d.get("x") is not None and str(series) == str(d.get("x")):
            series = None if _is_pie(recs, cid) else series   # tròn 1 vòng: để trống, import tự lấy = x
        vals = {"id": cid, "series": series, "x": None if d.get("x") is None else str(d.get("x")),
                "y_raw": d.get("y_raw", None if "y" not in d else str(d["y"]).replace(".", ",")),
                "axis": d.get("axis"), "estimated": "có" if d.get("estimated") else None}
        for k, j in key_p.items():
            c = wp.cell(row=i, column=j)
            if k == "y":
                yr = f"{L(key_p, 'y_raw')}{i}"
                c.value = f'=IF({yr}="","",IFERROR(_xlfn.NUMBERVALUE({yr},",","."),"LỖI"))'
                c.number_format = "#,##0.###"
                c.fill = FILL_LOCK
            else:
                c.value = vals.get(k)
                c.number_format = "@"
                c.fill = FILL_IN
            c.font = F_BODY
    idref = f"BieuDo!${L(key_c, 'id')}$2:${L(key_c, 'id')}${last_c}"
    dv = DataValidation(type="list", formula1=idref, allow_blank=True, showErrorMessage=True,
                        errorTitle="id", error="id phải có trong sheet BieuDo")
    dv.add(f"{L(key_p, 'id')}2:{L(key_p, 'id')}{last_p}")
    wp.add_data_validation(dv)
    add_list(wp, ["y", "y2"], f"{L(key_p, 'axis')}2:{L(key_p, 'axis')}{last_p}", "Trục")
    add_list(wp, ["có"], f"{L(key_p, 'estimated')}2:{L(key_p, 'estimated')}{last_p}", "Ước lượng")
    ycol = f"{L(key_p, 'y')}2:{L(key_p, 'y')}{last_p}"
    wp.conditional_formatting.add(ycol, CellIsRule(operator="equal", formula=['"LỖI"'],
                                                   fill=PatternFill("solid", fgColor="FFC7CE")))
    wp.auto_filter.ref = f"A1:{col_letter(len(POINT_COLS))}{last_p}"

    _guide(guide, name, n)
    wb.active = 1
    from openpyxl.workbook.properties import CalcProperties
    wb.calculation = CalcProperties(fullCalcOnLoad=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _is_pie(recs, cid):
    return any(r["id"] == cid and r.get("chart_type") == "pie" for r in recs)


def _warn_formula(i, key_c, key_p, L):
    st, n = f"{L(key_c, 'status')}{i}", f"{L(key_c, 'n_points')}{i}"
    subj, typ, y2u = f"{L(key_c, 'subject')}{i}", f"{L(key_c, 'chart_type')}{i}", f"{L(key_c, 'y2_unit')}{i}"
    yu, cid = f"{L(key_c, 'y_unit')}{i}", f"{L(key_c, 'id')}{i}"
    pid = f"DiemDuLieu!${L(key_p, 'id')}:${L(key_p, 'id')}"
    py = f"DiemDuLieu!${L(key_p, 'y')}:${L(key_p, 'y')}"
    return (f'=IF({st}<>"xong","",IF({n}=0,"chưa có điểm dữ liệu",'
            f'IF({subj}="","thiếu Môn",'
            f'IF(COUNTIFS({pid},{cid},{py},"LỖI")>0,"có y_raw viết sai",'
            f'IF(AND({typ}="pie",{yu}="%",ABS(SUMIF({pid},{cid},{py})-100)>1.5),"tròn: tổng khác 100%",'
            f'IF(AND({typ}="combo",{y2u}=""),"combo: kiểm tra trục y2",""))))))')


def _guide(ws, name, n):
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 96
    rows = [
        ("V-ChartText: phiếu gán nhãn", None),
        ("Người gán", f"{name} ({n} biểu đồ)"),
        ("", None),
        ("CÁCH LÀM", None),
        ("1", "Sheet BieuDo: mỗi dòng 1 biểu đồ. Bấm 'mở ảnh' ở cột Ảnh để xem ảnh."),
        ("2", "Điền các ô NỀN VÀNG. Ô nền xám là ô không sửa hoặc tự tính. Rê chuột lên tiêu đề cột để xem hướng dẫn."),
        ("3", "Sheet DiemDuLieu: mỗi dòng 1 điểm số liệu (1 cột, 1 điểm trên đường, 1 phần của hình tròn). "
              "Chọn id ở cột A, điền series, x, y_raw. Kiểm tra cột y (tự tính) khớp với ảnh."),
        ("4", "Gán xong một biểu đồ: đổi Trạng thái thành 'xong' và xem cột Cảnh báo phải trống."),
        ("5", "Ảnh hỏng, trùng, không phải biểu đồ: Trạng thái 'bỏ' và ghi lý do ở Ghi chú."),
        ("6", "Cuối buổi: lưu file, chạy  python src/labeling_xlsx.py import  rồi  python eval/validate_labels.py, "
              "sửa hết lỗi rồi mới commit và push (đẩy cả file Excel lẫn data/labels)."),
        ("7", "Mở file trong thư mục data/labeling của repo (không chép đi nơi khác) để link 'mở ảnh' hoạt động."),
        ("", None),
        ("QUY ƯỚC SỐ (quan trọng nhất)", None),
        ("y_raw", "Chép ĐÚNG như trên ảnh, kiểu Việt Nam: 1.200 (một nghìn hai trăm), 12,5 (mười hai phẩy năm), 6 586,6. "
                  "Ô đã để dạng chữ nên Excel không tự đổi số."),
        ("Đơn vị", "KHÔNG đổi đơn vị: ảnh ghi 'nghìn tấn' và cột ghi 1.200 thì y_raw = 1.200, đơn vị trục y = 'nghìn tấn'."),
        ("Không ghi số", "Đọc theo vạch chia, làm tròn đến nửa vạch nhỏ nhất, cột 'Ước lượng?' = có; "
                         "cột 'Có ghi số trên hình?' ở BieuDo = không."),
        ("Biểu đồ tròn", "x = tên phần, y_raw = phần trăm (không cần dấu %). Một vòng: để trống series. "
                         "Nhiều vòng (nhiều năm): series = năm."),
        ("Biểu đồ kết hợp", "Mỗi chuỗi một series; chuỗi theo trục phải: cột 'Trục' = y2 và điền Trục y2 ở BieuDo."),
        ("Một chuỗi", "Không có chú giải: để trống Chú giải; series = tên đại lượng, giống nhau cho mọi điểm."),
        ("", None),
        ("VÍ DỤ (1 điểm)", "id = bar_001 | series = Chiều dài đường ô tô | x = Hoa Kỳ | y_raw = 6 586,6 | Trục: trống | "
                           "Ước lượng?: trống  ->  y (tự tính) = 6586,6"),
        ("", "Các biểu đồ đã gán sẵn (trạng thái 'xong') là ví dụ đầy đủ."),
        ("", None),
        ("KIỂM TRA CHÉO", "Sau khi gán xong, mỗi người kiểm tra ≥ 20% file của người khác: điền 'Người kiểm tra chéo' "
                          "và 'Kết quả kiểm tra' (đạt / đã sửa) ngay trong file của người được kiểm tra."),
    ]
    for i, (a, b) in enumerate(rows, 1):
        ca, cb = ws.cell(row=i, column=1, value=a), ws.cell(row=i, column=2, value=b)
        bold = b is None and a or a in ("Người gán",)
        ca.font = Font(name=ARIAL, size=12 if i == 1 else 10, bold=bool(bold) or i == 1)
        cb.font = F_BODY
        cb.alignment = Alignment(wrap_text=True, vertical="top")
        ca.alignment = Alignment(vertical="top")
    ws["A30"], ws["B30"] = "Màu ô", "Nền vàng = cần điền   |   Nền xám = không sửa / tự tính"
    ws["A30"].font = F_HEAD
    ws["B30"].font = F_BODY
    ws["A30"].fill = FILL_IN


# ----------------------------------------------------------------- import
def _s(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def read_sheet(ws, cols):
    title_to_key = {title: k for k, title, *_ in cols}
    heads = [title_to_key.get(c.value) for c in ws[1]]
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        r = {k: v for k, v in zip(heads, row) if k}
        if r.get("id"):
            out.append(r)
    return out


def do_import(paths):
    n_ok = n_skip = n_bad = 0
    for path in paths:
        wb = load_workbook(path)          # đọc giá trị người nhập, không cần công thức
        charts = read_sheet(wb["BieuDo"], CHART_COLS)
        points = read_sheet(wb["DiemDuLieu"], POINT_COLS)
        by_id = {}
        for p in points:
            by_id.setdefault(_s(p["id"]), []).append(p)
        print(f"\n{path.name}: {len(charts)} biểu đồ, {len(points)} điểm")
        for r in charts:
            cid, st = _s(r["id"]), _s(r.get("status")) or "chưa"
            jp = LABELS / f"{cid}.json"
            if st == "chưa" or not jp.exists():
                n_skip += 1
                continue
            rec = json.loads(jp.read_text(encoding="utf-8"))
            if st == "bỏ":
                rec["status"] = "excluded"
                rec["notes"] = _s(r.get("notes")) or ""
                _write(jp, rec)
                n_ok += 1
                continue
            try:
                new = build_record(rec, r, by_id.get(cid, []))
            except ValueError as e:
                print(f"  [LỖI] {cid}: {e}  -> chưa ghi")
                n_bad += 1
                continue
            _write(jp, new)
            n_ok += 1
    print(f"\nĐã ghi {n_ok} file nhãn, bỏ qua {n_skip} (trạng thái 'chưa'), lỗi {n_bad}.")
    print("Tiếp theo: python eval/validate_labels.py")


def build_record(rec, r, pts):
    typ = _s(r.get("chart_type"))
    legend = [x.strip() for x in (_s(r.get("legend")) or "").split("|") if x.strip()]
    src = dict(rec.get("source") or {})
    page = _s(r.get("page"))
    src.update({"type": _s(r.get("src_type")), "book": _s(r.get("book")),
                "page": int(page) if page and page.isdigit() else page, "url": _s(r.get("url"))})
    vs = _s(r.get("values_shown"))
    data = []
    for k, p in enumerate(pts, 1):
        x, raw, series = _s(p.get("x")), _s(p.get("y_raw")), _s(p.get("series"))
        if raw is None and x is None and series is None:
            continue
        if x is None or raw is None:
            raise ValueError(f"điểm thứ {k}: thiếu x hoặc y_raw")
        if series is None:
            if typ == "pie":
                series = x
            elif len(legend) == 1:
                series = legend[0]
            else:
                raise ValueError(f"điểm thứ {k} (x={x}): thiếu series")
        try:
            y = parse_vn(raw.replace("%", ""))
        except ValueError:
            raise ValueError(f"điểm thứ {k} (x={x}): y_raw '{raw}' không đọc được") from None
        d = {"series": series, "x": x, "y": int(y) if y.is_integer() else y, "y_raw": raw.replace("%", "").strip()}
        axis = _s(p.get("axis"))
        if _s(r.get("y2_label")) or _s(r.get("y2_unit")):
            d["axis"] = axis or "y"           # biểu đồ 2 trục: mọi điểm ghi rõ trục
        elif axis == "y2":
            raise ValueError(f"điểm thứ {k} (x={x}): Trục = y2 nhưng BieuDo chưa điền Trục y2")
        if _s(p.get("estimated")) == "có":
            d["estimated"] = True
        data.append(d)
    if not data:
        raise ValueError("chưa có điểm dữ liệu nào trong sheet DiemDuLieu")
    new = {
        "id": rec["id"], "image": rec["image"], "source": src, "annotator": rec.get("annotator"),
        "subject": _s(r.get("subject")), "chart_type": typ, "title": _s(r.get("title")) or "",
        "x_axis": {"label": _s(r.get("x_label")), "unit": _s(r.get("x_unit"))},
        "y_axis": {"label": _s(r.get("y_label")), "unit": _s(r.get("y_unit"))},
    }
    if _s(r.get("y2_label")) or _s(r.get("y2_unit")):
        new["y2_axis"] = {"label": _s(r.get("y2_label")), "unit": _s(r.get("y2_unit"))}
    new.update({"legend": legend, "values_shown_on_chart": None if vs is None else vs == "có", "data": data})
    if _s(r.get("reviewer")) or _s(r.get("review")):
        new["review"] = {"by": _s(r.get("reviewer")), "result": _s(r.get("review"))}
    if _s(r.get("notes")):
        new["notes"] = _s(r.get("notes"))
    return new


def _write(path, rec):
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["export", "import"])
    ap.add_argument("--force", action="store_true", help="export: ghi đè file Excel đã có")
    args = ap.parse_args()
    if args.cmd == "export":
        recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(LABELS.glob("*.json"))
                if not p.name.startswith("example_")]
        for name in sorted({r.get("annotator") for r in recs if r.get("annotator")}):
            path = OUTDIR / f"nhan_{name}.xlsx"
            if path.exists() and not args.force:
                print(f"BỎ QUA {path} (đã có; dùng --force để tạo lại, sẽ MẤT phần đã gán trong Excel)")
                continue
            mine = [r for r in recs if r.get("annotator") == name]
            build(name, mine, path)
            print(f"Đã tạo {path}: {len(mine)} biểu đồ")
    else:
        paths = sorted(OUTDIR.glob("nhan_*.xlsx"))
        if not paths:
            raise SystemExit(f"Không thấy file nào trong {OUTDIR}")
        do_import([p for p in paths if not p.name.startswith("~$")])


if __name__ == "__main__":
    main()
