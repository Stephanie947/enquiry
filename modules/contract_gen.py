"""
合同生成模块 — 严格按照真实合同格式
基于：日照东方2026_04_30.pdf 和 盐城市斯壮格2024_12_06.pdf
"""

import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

SUPPLIER_INFO = {
    "name": "上海库胜自动化工程有限公司",
    "address": "上海市青浦赵巷民实路91号",
    "contact": "罗静",
    "phone": "021-34553766",
    "fax": "021-54782619",
    "bank": "中行上海市梅陇支行",
    "account": "454660228802",
    "tax_no": "91310118691641586X",
    "postcode": "201101",
    "mobile": "13641756769",
}

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")


def amount_to_chinese(amount: float) -> str:
    digits = ["零","壹","贰","叁","肆","伍","陆","柒","捌","玖"]
    units  = ["","拾","佰","仟"]
    if amount == 0:
        return "零元整"
    int_part = int(amount)
    fen_part = round((amount - int_part) * 100)

    def convert_section(n):
        if n == 0: return ""
        result = ""
        n_str = str(n).zfill(4)
        has_zero = False
        for i, d in enumerate(n_str):
            digit = int(d)
            if digit == 0:
                has_zero = True
            else:
                if has_zero and result:
                    result += "零"
                result += digits[digit] + units[3-i]
                has_zero = False
        return result

    yi  = int_part // 100000000
    wan = (int_part % 100000000) // 10000
    yuan= int_part % 10000
    result = ""
    if yi:  result += convert_section(yi) + "亿"
    if wan:
        if yi and wan < 1000: result += "零"
        result += convert_section(wan) + "万"
    if yuan:
        if (yi or wan) and yuan < 1000: result += "零"
        result += convert_section(yuan)
    result += "元"
    if fen_part == 0:
        result += "整"
    else:
        jiao = fen_part // 10
        fen  = fen_part % 10
        if jiao: result += digits[jiao] + "角"
        if fen:  result += digits[fen]  + "分"
    return result


def _register_fonts():
    """
    注册中文字体，优先级：
    1. reportlab 内置 CID 字体 STSong-Light（零依赖，不需要系统字体文件，Streamlit Cloud 可用）
    2. 系统 TTF 字体（wqy-zenhei 等，本地开发时回退）

    旧版只找系统路径，Streamlit Cloud Linux 环境路径不同时找不到字体 → 黑块
    新版改为优先用 CID 字体，完全绕开系统字体依赖
    """
    # 方案1：reportlab 内置 CID 宋体（推荐，无需任何字体文件）
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light"
    except Exception:
        pass

    # 方案2：系统 TTF 字体（兜底）
    candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        os.path.join(os.path.dirname(__file__), "..", "wqy-zenhei.ttc"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("CN", path))
                return "CN"
            except Exception:
                continue

    return "Helvetica"  # 最终兜底（中文会乱码，但不会崩溃）


def gen_contract_pdf(contract_no, client_info, items, payment_terms="款到发货", sign_date=None):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    fn = _register_fonts()

    if sign_date is None:
        sign_date = datetime.now().strftime("%Y年%m月%d日")

    # 从日期提取年月日
    import re
    m = re.search(r"(\d+)年(\d+)月(\d+)日", sign_date)
    year  = m.group(1) if m else datetime.now().strftime("%Y")
    month = m.group(2) if m else datetime.now().strftime("%m")
    day   = m.group(3) if m else datetime.now().strftime("%d")

    filename = f"合同_{contract_no}_{client_info.get('name','')}.pdf"
    path = os.path.join(OUTPUT_DIR, filename)

    doc = SimpleDocTemplate(path, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)

    sn = ParagraphStyle("sn", fontName=fn, fontSize=9,  leading=14, wordWrap="CJK")
    sb = ParagraphStyle("sb", fontName=fn, fontSize=9,  leading=14, wordWrap="CJK")
    st = ParagraphStyle("st", fontName=fn, fontSize=15, leading=24, alignment=1, wordWrap="CJK")
    sm = ParagraphStyle("sm", fontName=fn, fontSize=9,  leading=16, wordWrap="CJK")

    story = []

    # 标题
    story.append(Paragraph("产  品  购  销  合  同", st))
    story.append(Spacer(1, 0.3*cm))

    # 基本信息
    story.append(Paragraph(f"卖方：{SUPPLIER_INFO['name']}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;合同编号：{contract_no}", sn))
    story.append(Paragraph(f"买方：{client_info.get('name','')}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;签订地点：上海", sn))
    story.append(Paragraph(f"一：产品名称、商标、型号、厂家、数量、金额、货期&nbsp;&nbsp;&nbsp;&nbsp;签订时间：{year}年{month}月{day}日", sn))
    story.append(Spacer(1, 0.2*cm))

    # 产品明细表（含未税单价列）
    total_amount = 0.0
    table_data = [["产品名称", "单位", "数量", "未税单价", "含税单价", "总金额", "货期及付款方式"]]
    VAT_RATE = 1.13  # 增值税率13%

    for i, item in enumerate(items):
        sale_price     = item.get("sale_price", 0)
        qty            = item.get("qty", 0)
        total          = round(sale_price * qty, 2)
        untaxed_price  = round(sale_price / VAT_RATE, 2) if sale_price else 0
        total_amount  += total

        row = [
            item.get("model_short") or item.get("model_full", ""),
            item.get("unit", "只"),
            str(qty),
            f"{untaxed_price:.2f}" if sale_price else "待定",
            f"{sale_price:.0f}"    if sale_price else "待定",
            f"{total:.2f}"         if sale_price else "待定",
            payment_terms if i == 0 else "",
        ]
        table_data.append(row)

    # 合计行
    table_data.append([f"合计：{total_amount:.2f}", "", "", "", "", "", ""])
    table_data.append([f"合计人民币金额（大写）：{amount_to_chinese(total_amount)}", "", "", "", "", "", ""])

    col_widths = [4.0*cm, 1.2*cm, 1.2*cm, 2.0*cm, 2.0*cm, 2.0*cm, 4.1*cm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME",    (0,0), (-1,-1), fn),
        ("FONTSIZE",    (0,0), (-1,-1), 8),
        ("GRID",        (0,0), (-1,-3), 0.5, colors.black),
        ("BACKGROUND",  (0,0), (-1,0),  colors.Color(0.88,0.88,0.88)),
        ("ALIGN",       (1,0), (5,-1),  "CENTER"),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("SPAN",        (0,-2), (-1,-2)),
        ("SPAN",        (0,-1), (-1,-1)),
        ("FONTNAME",    (0,-2), (-1,-1), fn),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.3*cm))

    # 条款
    clauses = [
        "二：价格：本合同总价已包含增值税和运费。",
        "三：交货期：具体货期见（一）预付款到账之日计起，因厂家原因导致的货期延迟则我方承诺的货期将相应延长。",
        "四：运输方式及费用负担：卖方承担运费。",
        "五：验收标准、方法及提出异议期限：按原厂家标准验收，如有产品质量问题，需方应在收到货后一周内提出异议，逾期提出异议则视为卖方提供的产品符合双方的约定。",
        "六：保修期：按原厂家提供的质保条例。",
        "七：合同纠纷：按《合同法》协商解决；协商不成应向卖方所在地法院起诉。",
        "八：其他约定事项：",
        "　　1) 合同货物中所有型号已经买方确认，卖方不承担因型号误差所造成的任何责任。",
        "　　2) 卖方不承担因交货、质量等问题所引起的买方或任何第三方的直接或间接的责任。",
        "　　3) 本合同一式二份，供方一份，需方一份。传真件与原件具有同等法律效率，双方签字盖章即刻生效。",
    ]
    for clause in clauses:
        story.append(Paragraph(clause, sm))
    story.append(Spacer(1, 0.4*cm))

    # 签字栏
    sign_data = [
        ["卖方", "买方"],
        [f"单位名称（章）{SUPPLIER_INFO['name']}", f"单位名称（章）{client_info.get('name','')}"],
        [f"单位地址：{SUPPLIER_INFO['address']}", f"单位地址：{client_info.get('address','')}"],
        ["法定代表人：", "法定代表人："],
        [f"委托代理人：{SUPPLIER_INFO['contact']}", f"委托代理人：{client_info.get('contact','')}"],
        [f"电话：{SUPPLIER_INFO['phone']}", f"电话：{client_info.get('phone','')}"],
        [f"传真：{SUPPLIER_INFO['fax']}", "传真："],
        [f"开户银行：{SUPPLIER_INFO['bank']}", f"开户银行：{client_info.get('bank','')}"],
        [f"帐号：{SUPPLIER_INFO['account']}", f"帐号：{client_info.get('account','')}"],
        [f"税号：{SUPPLIER_INFO['tax_no']}", f"税号：{client_info.get('tax_no','')}"],
        [f"邮政编码：{SUPPLIER_INFO['postcode']}", "邮政编码："],
    ]
    sign_table = Table(sign_data, colWidths=[8.25*cm, 8.25*cm])
    sign_table.setStyle(TableStyle([
        ("FONTNAME",   (0,0), (-1,-1), fn),
        ("FONTSIZE",   (0,0), (-1,-1), 8),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.black),
        ("BACKGROUND", (0,0), (-1,0),  colors.Color(0.88,0.88,0.88)),
        ("ALIGN",      (0,0), (-1,0),  "CENTER"),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUND", (0,1), (-1,-1), colors.white),
    ]))
    story.append(sign_table)
    doc.build(story)
    return path