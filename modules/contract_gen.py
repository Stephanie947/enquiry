"""
合同生成模块 — Workflow + LLM混合方案

策略：
- 结构化字段（型号、金额、日期、客户信息）：纯代码填充，100%准确
- 自然语言字段（货期描述、金额大写）：纯代码处理（有成熟算法）
- LLM只在需要时处理"货期付款方式"的自然语言整合

这样设计的原因：合同是法律文件，任何LLM幻觉都是风险。
能用代码写死的绝不用LLM。
"""

import os
import re
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from config import SUPPLIER_INFO

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")


# ─────────────────────────────────────────────
# 金额转大写（纯代码，100%准确）
# ─────────────────────────────────────────────

def amount_to_chinese(amount: float) -> str:
    """将金额转换为中文大写，如 57348.00 → 伍万柒仟叁佰肆拾捌元整"""
    digits = ["零", "壹", "贰", "叁", "肆", "伍", "陆", "柴", "捌", "玖"]
    digits[7] = "柒"
    units = ["", "拾", "佰", "仟"]
    big_units = ["", "万", "亿"]

    if amount == 0:
        return "零元整"

    # 处理整数部分
    int_part = int(amount)
    fen_part = round((amount - int_part) * 100)

    def convert_section(n):
        """转换4位以内的数字"""
        if n == 0:
            return ""
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
                result += digits[digit] + units[3 - i]
                has_zero = False
        return result

    # 分段处理亿、万、元
    yi = int_part // 100000000
    wan = (int_part % 100000000) // 10000
    yuan = int_part % 10000

    result = ""
    if yi:
        result += convert_section(yi) + "亿"
    if wan:
        if yi and wan < 1000:
            result += "零"
        result += convert_section(wan) + "万"
    if yuan:
        if (yi or wan) and yuan < 1000:
            result += "零"
        result += convert_section(yuan)

    result += "元"

    if fen_part == 0:
        result += "整"
    else:
        jiao = fen_part // 10
        fen = fen_part % 10
        if jiao:
            result += digits[jiao] + "角"
        if fen:
            result += digits[fen] + "分"

    return result


# ─────────────────────────────────────────────
# 注册中文字体（reportlab默认不支持中文）
# ─────────────────────────────────────────────

def _register_fonts():
    """尝试注册系统中文字体"""
    font_candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in font_candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("ChineseFont", path))
                return "ChineseFont"
            except Exception:
                continue
    return "Helvetica"  # fallback


# ─────────────────────────────────────────────
# 生成PDF合同（Workflow模式）
# ─────────────────────────────────────────────

def gen_contract_pdf(
    contract_no: str,
    client_info: dict,
    items: list[dict],
    payment_terms: str = "合同签订时需方支付30%预付，余款款到发货",
    sign_date: str = None,
) -> str:
    """
    生成PDF格式合同。
    所有字段都是程序化填充，格式与现有合同完全一致。
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    font_name = _register_fonts()

    if sign_date is None:
        sign_date = datetime.now().strftime("%Y年%m月%d日")

    filename = f"合同_{contract_no}_{client_info.get('name', '')}_{datetime.now().strftime('%Y%m%d')}.pdf"
    path = os.path.join(OUTPUT_DIR, filename)

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )

    # 样式
    styles = getSampleStyleSheet()
    style_normal = ParagraphStyle(
        "cn_normal", fontName=font_name, fontSize=10, leading=16,
        wordWrap="CJK"
    )
    style_title = ParagraphStyle(
        "cn_title", fontName=font_name, fontSize=16, leading=24,
        alignment=1, spaceAfter=12, wordWrap="CJK"
    )
    style_bold = ParagraphStyle(
        "cn_bold", fontName=font_name, fontSize=10, leading=16,
        wordWrap="CJK"
    )

    story = []

    # 顶部联系人
    story.append(Paragraph(f"联系人：{SUPPLIER_INFO['contact']}/{SUPPLIER_INFO['mobile']}", style_normal))
    story.append(Spacer(1, 0.3*cm))

    # 合同标题
    story.append(Paragraph("产  品  购  销  合  同", style_title))

    # 基本信息
    story.append(Paragraph(f"供方：{SUPPLIER_INFO['name']}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;合同编号：{contract_no}", style_normal))
    story.append(Paragraph(f"需方：{client_info.get('name', '')}  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;签订地点：上海", style_normal))
    story.append(Paragraph(f"一：产品名称、商标、型号、厂家、数量、金额、货期&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;签订时间：{sign_date}", style_normal))
    story.append(Spacer(1, 0.3*cm))

    # 产品明细表
    total_amount = sum(item.get("sale_price", 0) * item.get("qty", 0) for item in items)

    table_data = [["型号", "制造商", "单位", "数量", "含税单价", "含税总价", "货期及付款方式"]]
    for i, item in enumerate(items):
        sale_price = item.get("sale_price", 0)
        qty = item.get("qty", 0)
        total = round(sale_price * qty, 2)
        row = [
            item.get("model_short") or item.get("model_full", ""),
            item.get("brand", "巴鲁夫"),
            item.get("unit", "个"),
            str(qty),
            f"{sale_price:.0f}" if sale_price else "待定",
            f"{total:.0f}" if sale_price else "待定",
            payment_terms if i == 0 else "",
        ]
        table_data.append(row)

    # 合计行
    table_data.append([
        f"含税合计：{total_amount:.2f}（{amount_to_chinese(total_amount)}）",
        "", "", "", "", "", ""
    ])

    col_widths = [3.2*cm, 1.8*cm, 1.2*cm, 1.2*cm, 1.8*cm, 1.8*cm, 5.5*cm]

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -2), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.84, 0.89, 0.94)),
        ("ALIGN", (2, 0), (5, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("SPAN", (0, -1), (-1, -1)),  # 合计行合并
        ("FONTNAME", (0, -1), (-1, -1), font_name),
        ("ROWBACKGROUND", (0, -1), (-1, -1), colors.Color(0.95, 0.95, 0.95)),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.4*cm))

    # 合同条款（固定文本）
    clauses = [
        "二：价格：本合同总价已包含增值税。",
        "三：交货期：具体货期见（一）",
        "四：运输方式及费用负担：卖方承担运费。",
        "五：验收标准、方法及提出异意期限：按原厂家标准验收，如有产品质量问题，需方应在收到货后一周内提出异议，逾期提出异议则视为卖方提供的产品符合双方的约定。",
        "六：风险转移：货物丢失与破损的责任风险自买方或其承运人收到货物时转移到买方或承运人",
        "七：保修期：按原厂家提供的质保条例",
        "八：合同纠纷：按《合同法》协商解决；协商不成应向卖方所在地法院起诉。",
        "九：其他约定事项：",
        "　　1) 合同货物中所有型号已经买方确认，卖方不承担因型号误差所造成的任何责任。",
        "　　2) 本合同签约之产品为纯销售性质，不包含技术服务费用。",
        "　　3）卖方不承担因交货、质量等问题所引起的买方或任何第三方的直接或间接的责任。",
        "　　4）本合同一式二份，供方一份，需方一份。传真件与原件具有同等法律效率，双方签字盖章即刻生效",
    ]
    for clause in clauses:
        story.append(Paragraph(clause, style_normal))
    story.append(Spacer(1, 0.5*cm))

    # 签字栏
    sign_data = [
        ["供方", "需方"],
        [f"单位名称（章）{SUPPLIER_INFO['name']}", f"单位名称（章）{client_info.get('name', '')}"],
        [f"单位地址：{SUPPLIER_INFO['address']}", f"单位地址：{client_info.get('address', '')}"],
        ["法定代表人：", "法定代表人："],
        [f"委托代理人：{SUPPLIER_INFO['contact']}", f"委托代理人：{client_info.get('contact', '')}"],
        [f"电话：{SUPPLIER_INFO['phone']}", f"电话：{client_info.get('phone', '')}"],
        [f"开户银行：{SUPPLIER_INFO['bank']}", f"开户银行：{client_info.get('bank', '')}"],
        [f"帐号：{SUPPLIER_INFO['account']}", f"帐号：{client_info.get('account', '')}"],
        [f"税号：{SUPPLIER_INFO['tax_no']}", f"税号：{client_info.get('tax_no', '')}"],
    ]

    sign_table = Table(sign_data, colWidths=[8*cm, 8*cm])
    sign_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.84, 0.89, 0.94)),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWHEIGHT", (0, 0), (-1, -1), 0.7*cm),
    ]))
    story.append(sign_table)

    doc.build(story)
    return path
