import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "quoteflow.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_conn()
    c = conn.cursor()

    # 客户档案表
    c.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            address TEXT,
            bank TEXT,
            account TEXT,
            tax_no TEXT,
            contact TEXT,
            phone TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 订单主表
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_no TEXT UNIQUE,
            client_name TEXT,
            total_amount REAL,
            status TEXT DEFAULT '询价中',
            order_type TEXT DEFAULT '零散',
            markup_rate REAL DEFAULT 1.30,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 订单明细表
    c.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            model_short TEXT,
            model_full TEXT,
            description TEXT,
            unit TEXT DEFAULT '个',
            qty INTEGER,
            purchase_price REAL,
            sale_price REAL,
            total_price REAL,
            delivery_weeks TEXT,
            brand TEXT DEFAULT 'BALLUFF',
            confidence REAL DEFAULT 1.0,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)

    # 预置常用客户（从合同文件提取）
    c.execute("""
        INSERT OR IGNORE INTO clients (name, address, bank, account, tax_no, contact, phone)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "上海科致电气自动化股份有限公司",
        "上海市闵行区新骏环路138号3幢301室",
        "中国工商银行上海市浦江高科技园支行",
        "1001119809000013309",
        "913100007622394 64T",
        "",
        "34637140"
    ))

    conn.commit()
    conn.close()


def generate_contract_no():
    """生成合同编号：YM + 年月日 + 序号"""
    today = datetime.now().strftime("%Y%m%d")
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) FROM orders WHERE contract_no LIKE ?",
        (f"YM{today}%",)
    )
    count = c.fetchone()[0] + 1
    conn.close()
    return f"YM{today}{count:02d}"


def save_order(contract_no, client_name, items, markup_rate, order_type="零散", notes=""):
    """保存订单到数据库，返回order_id"""
    conn = get_conn()
    c = conn.cursor()

    total = sum(item.get("total_price", 0) for item in items)

    c.execute("""
        INSERT INTO orders (contract_no, client_name, total_amount, order_type, markup_rate, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (contract_no, client_name, total, order_type, markup_rate, notes))

    order_id = c.lastrowid

    for item in items:
        c.execute("""
            INSERT INTO order_items
            (order_id, model_short, model_full, description, unit, qty,
             purchase_price, sale_price, total_price, delivery_weeks, brand, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            item.get("model_short", ""),
            item.get("model_full", ""),
            item.get("description", ""),
            item.get("unit", "个"),
            item.get("qty", 0),
            item.get("purchase_price", 0),
            item.get("sale_price", 0),
            item.get("total_price", 0),
            item.get("delivery_weeks", ""),
            item.get("brand", "BALLUFF"),
            item.get("confidence", 1.0),
        ))

    conn.commit()
    conn.close()
    return order_id


def get_all_orders():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM orders ORDER BY created_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def update_order_status(order_id, status):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE orders SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
        (status, order_id)
    )
    conn.commit()
    conn.close()


def get_all_clients():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM clients ORDER BY name")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def save_client(name, address="", bank="", account="", tax_no="", contact="", phone=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO clients (name, address, bank, account, tax_no, contact, phone)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (name, address, bank, account, tax_no, contact, phone))
    conn.commit()
    conn.close()