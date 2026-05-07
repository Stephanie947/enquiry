import os
from dotenv import load_dotenv

load_dotenv()

SUPPLIER_INFO = {
    "name": "上海库胜自动化工程有限公司",
    "address": "上海市闵行区罗锦路55号B栋305",
    "contact": "罗静",
    "phone": "021-33583656",
    "fax": "021-54782619",
    "bank": "中行上海市梅陇支行",
    "account": "454660228802",
    "tax_no": "91310118691641586X",
    "postcode": "201101",
    "mobile": "13641756769",
}

MARKUP_CONFIG = {
    "default": 1.30,
    "vip_client": 1.20,
    "project_order": 1.25,
}

CONFIDENCE_THRESHOLD = 0.85
CONTRACT_PREFIX = "YM"