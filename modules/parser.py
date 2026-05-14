import google.generativeai as genai
import pandas as pd
import json
import re
import pdfplumber
import os
import PIL.Image
import io
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
_model = genai.GenerativeModel("gemini-2.0-flash-lite")

CONFIDENCE_THRESHOLD = 0.85


def _clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _call_llm(prompt: str) -> str:
    response = _model.generate_content(prompt)
    return response.text


def _call_llm_vision(prompt: str, image: PIL.Image.Image) -> str:
    response = _model.generate_content([prompt, image])
    return response.text


EXTRACT_PROMPT = """你是工业品代理公司的报价助手，专门处理传感器、电缆等产品的询价单。
请从以下内容中提取产品信息，严格按照JSON格式输出，不要输出任何其他内容：

{
  "items": [
    {
      "model_full": "完整型号，如 BCC A335-0000-10-000-51X5A5-000",
      "model_short": "短订货号，如 BCC070E，没有则为空字符串",
      "description": "产品中文描述",
      "qty": 数量整数,
      "unit": "单位，默认个",
      "brand": "品牌，如 BALLUFF、Pepperl+Fuchs、SIEMENS",
      "confidence": 置信度0.0到1.0
    }
  ]
}

规则：数量为0的行不包含，合计行标题行不包含，型号模糊则confidence设低，只输出JSON。

"""


def parse_excel(file_path: str) -> list[dict]:
    df_raw = pd.read_excel(file_path, header=None)
    first_row_str = " ".join(str(v).lower() for v in df_raw.iloc[0].values)
    has_header = any(k in first_row_str for k in ["型号", "model", "part", "数量", "qty", "品牌"])

    if has_header:
        header_row = 0
        for i, row in df_raw.iterrows():
            row_str = " ".join(str(v).lower() for v in row.values)
            if any(k in row_str for k in ["型号", "model", "part", "数量", "qty"]):
                header_row = i
                break
        df = pd.read_excel(file_path, header=header_row)
        df.columns = [str(c).strip() for c in df.columns]
        col_aliases = {
            "model_full":  ["型号", "model", "part number", "partnumber", "产品型号"],
            "model_short": ["订货号", "order no", "item no", "短型号"],
            "description": ["描述", "description", "产品描述", "名称"],
            "qty":         ["数量", "qty", "quantity", "件数"],
            "unit":        ["单位", "unit"],
            "brand":       ["品牌", "brand", "制造商", "manufacturer"],
        }
        def find_col(candidates):
            for name in candidates:
                for col in df.columns:
                    if name.lower() in col.lower():
                        return col
            return None
        model_col = find_col(col_aliases["model_full"])
        short_col = find_col(col_aliases["model_short"])
        desc_col  = find_col(col_aliases["description"])
        qty_col   = find_col(col_aliases["qty"])
        unit_col  = find_col(col_aliases["unit"])
        brand_col = find_col(col_aliases["brand"])
        items = []
        for _, row in df.iterrows():
            model = str(row[model_col]).strip() if model_col else ""
            if not model or model in ["nan", "合计", "小计", "总计"]:
                continue
            try:
                qty = int(float(str(row[qty_col]).replace(",", ""))) if qty_col else 0
            except Exception:
                qty = 0
            if qty == 0:
                continue
            items.append({
                "model_full":     model,
                "model_short":    str(row[short_col]).strip() if short_col and str(row.get(short_col, "")) != "nan" else "",
                "description":    str(row[desc_col]).strip()  if desc_col  and str(row.get(desc_col,  "")) != "nan" else "",
                "qty":            qty,
                "unit":           str(row[unit_col]).strip()  if unit_col  and str(row.get(unit_col,  "")) != "nan" else "个",
                "brand":          str(row[brand_col]).strip() if brand_col and str(row.get(brand_col, "")) != "nan" else "BALLUFF",
                "purchase_price": 0.0, "sale_price": 0.0, "total_price": 0.0,
                "delivery_weeks": "", "confidence": 1.0, "source": "excel",
            })
        return items
    else:
        items = []
        for _, row in df_raw.iterrows():
            vals = [str(v).strip() for v in row.values]
            model = ""; desc = ""; qty = 0; unit = "个"; brand = "BALLUFF"
            for v in vals:
                if v in ["nan", "", "合计", "小计"]:
                    continue
                try:
                    n = int(float(v))
                    if 0 < n < 100000 and model:
                        qty = n; continue
                except Exception:
                    pass
                if (v and len(v) < 50 and v[0].isalpha()
                        and any(c.isdigit() for c in v)
                        and not any('\u4e00' <= c <= '\u9fff' for c in v)):
                    if not model:
                        model = v
                    continue
                if v.isupper() and v.isalpha() and len(v) < 20:
                    brand = v; continue
                if v in ["个", "件", "套", "根", "米", "m", "pcs", "PCS", "EA"]:
                    unit = v; continue
                if len(v) > 5 and not desc:
                    desc = v
            if model and qty > 0:
                items.append({
                    "model_full": model, "model_short": "", "description": desc,
                    "qty": qty, "unit": unit, "brand": brand,
                    "purchase_price": 0.0, "sale_price": 0.0, "total_price": 0.0,
                    "delivery_weeks": "", "confidence": 1.0, "source": "excel",
                })
        return items


def parse_image(image_bytes: bytes, mime_type: str = "image/png") -> list[dict]:
    img = PIL.Image.open(io.BytesIO(image_bytes))
    prompt = EXTRACT_PROMPT + "请从这张询价单图片中提取所有产品信息："
    response_text = _call_llm_vision(prompt, img)
    data = json.loads(_clean_json(response_text))
    items = data.get("items", [])
    for item in items:
        item.setdefault("purchase_price", 0.0)
        item.setdefault("sale_price", 0.0)
        item.setdefault("total_price", 0.0)
        item.setdefault("delivery_weeks", "")
        item["source"] = "image"
    return items


def parse_text(raw_text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT + f"以下是询价内容：\n\n{raw_text}"
    response_text = _call_llm(prompt)
    data = json.loads(_clean_json(response_text))
    items = data.get("items", [])
    for item in items:
        item.setdefault("purchase_price", 0.0)
        item.setdefault("sale_price", 0.0)
        item.setdefault("total_price", 0.0)
        item.setdefault("delivery_weeks", "")
        item["source"] = "text"
    return items


def flag_low_confidence(items: list[dict]) -> list[dict]:
    for item in items:
        item["needs_review"] = item.get("confidence", 1.0) < CONFIDENCE_THRESHOLD
    return items


def apply_markup(items: list[dict], markup_rate: float = 1.30) -> list[dict]:
    for item in items:
        purchase = item.get("purchase_price", 0.0)
        if purchase > 0:
            sale = round(purchase * markup_rate, 2)
            item["sale_price"]  = sale
            item["total_price"] = round(sale * item.get("qty", 0), 2)
        else:
            item["sale_price"]  = 0.0
            item["total_price"] = 0.0
    return items

def parse_pdf(file_path: str, mode: str = "inquiry") -> list[dict]:
    """
    解析PDF文件，支持两种模式：
    mode="inquiry"  → 解析客户询价单，提取型号+数量
    mode="quote"    → 解析上游报价单，提取型号+含税单价+货期
    """
    rows = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # 清洗每个单元格
                    cleaned = [str(c).strip() if c else "" for c in row]
                    if any(cleaned):
                        rows.append(cleaned)

    if not rows:
        return []

    # 找表头行
    header_idx = 0
    for i, row in enumerate(rows):
        row_str = " ".join(row).lower()
        if any(k in row_str for k in ["型号", "model", "数量", "单价", "货期"]):
            header_idx = i
            break

    headers = rows[header_idx]
    data_rows = rows[header_idx + 1:]

    def find_col(candidates):
        for name in candidates:
            for i, h in enumerate(headers):
                if name.lower() in h.lower():
                    return i
        return None

    if mode == "inquiry":
        # 询价单：提取型号+数量
        model_col = find_col(["型号", "model", "part"])
        qty_col   = find_col(["数量", "qty", "quantity"])
        desc_col  = find_col(["描述", "description", "名称"])
        unit_col  = find_col(["单位", "unit"])

        items = []
        for row in data_rows:
            if len(row) <= max(filter(None, [model_col, qty_col]), default=0):
                continue
            model = row[model_col].strip() if model_col is not None else ""
            if not model or model in ["合计", "小计", "总计", ""]:
                continue
            try:
                qty = int(float(row[qty_col].replace(",", ""))) if qty_col is not None else 0
            except Exception:
                qty = 0
            if qty == 0:
                continue
            items.append({
                "model_full":     model,
                "model_short":    "",
                "description":    row[desc_col].strip() if desc_col is not None else "",
                "qty":            qty,
                "unit":           row[unit_col].strip() if unit_col is not None else "个",
                "brand":          "BALLUFF",
                "purchase_price": 0.0,
                "sale_price":     0.0,
                "total_price":    0.0,
                "delivery_weeks": "",
                "confidence":     1.0,
                "source":         "pdf",
            })
        return items

    elif mode == "quote":
        # 上游报价单：提取型号+含税单价+货期
        model_col    = find_col(["型号", "model", "part"])
        price_col    = find_col(["含税单价", "单价", "price", "unit price"])
        delivery_col = find_col(["货期", "delivery", "lead time", "交期"])
        qty_col      = find_col(["数量", "qty"])

        results = {}
        for row in data_rows:
            if not row:
                continue
            model = row[model_col].strip() if model_col is not None and model_col < len(row) else ""
            if not model or model in ["合计", "小计", ""]:
                continue
            try:
                price = float(row[price_col].replace(",", "").replace("¥", "").replace("￥", "")) if price_col is not None and price_col < len(row) else 0.0
            except Exception:
                price = 0.0
            delivery = row[delivery_col].strip() if delivery_col is not None and delivery_col < len(row) else ""
            try:
                qty = int(float(row[qty_col])) if qty_col is not None and qty_col < len(row) else 0
            except Exception:
                qty = 0

            results[model] = {
                "purchase_price":  price,
                "delivery_weeks":  delivery,
                "qty":             qty,
            }
        return results  # 返回字典，key是型号