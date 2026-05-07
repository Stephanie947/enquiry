"""
QuoteFlow AI — 主应用入口
工业品代理商智能报价与订单管理系统
"""

import streamlit as st
import pandas as pd
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from modules.db import init_db, generate_contract_no, save_order, get_all_orders, update_order_status, get_all_clients, save_client
from modules.parser import parse_excel, parse_image, parse_text, apply_markup, flag_low_confidence
from modules.excel_gen import gen_upstream_inquiry, gen_customer_quote
from modules.contract_gen import gen_contract_pdf, amount_to_chinese
from config import MARKUP_CONFIG, SUPPLIER_INFO

st.set_page_config(page_title="QuoteFlow AI", page_icon="⚡", layout="wide")
init_db()

page = st.sidebar.selectbox(
    "功能导航",
    ["📋 询价解析 & 报价", "📄 生成合同", "📊 订单看板", "👥 客户档案"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**{SUPPLIER_INFO['name'][:8]}...**")
st.sidebar.caption(f"联系人：{SUPPLIER_INFO['contact']}")


# ══════════════════════════════════════════════
# 页面 1：询价解析 & 报价
# ══════════════════════════════════════════════

if page == "📋 询价解析 & 报价":
    st.title("⚡ 询价解析 & 报价生成")

    st.subheader("Step 1｜上传询价单")

    input_method = st.radio(
        "询价单来源",
        ["📊 Excel文件", "🖼️ 图片/截图", "📝 粘贴文字"],
        horizontal=True
    )

    items = []

    if input_method == "📊 Excel文件":
        uploaded = st.file_uploader("上传询价Excel", type=["xlsx", "xls"])
        if uploaded:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name
            try:
                with st.spinner("正在解析Excel..."):
                    items = parse_excel(tmp_path)
                    items = flag_low_confidence(items)
                st.success(f"✅ 识别到 {len(items)} 条产品，纯代码解析，置信度100%")
                st.session_state["parsed_items"] = items
            except Exception as e:
                st.error(f"解析失败：{e}")
            finally:
                os.unlink(tmp_path)

    elif input_method == "🖼️ 图片/截图":
        uploaded = st.file_uploader("上传图片", type=["png", "jpg", "jpeg"])
        if uploaded:
            st.image(uploaded, caption="上传的询价图片", width=500)
            img_bytes = uploaded.getvalue()
            mime = "image/png" if uploaded.name.endswith(".png") else "image/jpeg"
            if st.button("🔍 AI识别图片内容", type="primary"):
                with st.spinner("Claude Vision 正在识别..."):
                    try:
                        items = parse_image(img_bytes, mime)
                        items = flag_low_confidence(items)
                        st.session_state["parsed_items"] = items
                        st.success(f"✅ AI识别到 {len(items)} 条产品")
                    except Exception as e:
                        st.error(f"识别失败：{e}")

    elif input_method == "📝 粘贴文字":
        raw_text = st.text_area("粘贴询价内容（微信聊天记录等）", height=200)
        if st.button("🔍 AI解析文字", type="primary") and raw_text:
            with st.spinner("Claude 正在解析..."):
                try:
                    items = parse_text(raw_text)
                    items = flag_low_confidence(items)
                    st.session_state["parsed_items"] = items
                    st.success(f"✅ 解析到 {len(items)} 条产品")
                except Exception as e:
                    st.error(f"解析失败：{e}")

    if not items and "parsed_items" in st.session_state:
        items = st.session_state["parsed_items"]

    if items:
        st.markdown("---")
        st.subheader("Step 2｜核对产品明细")

        needs_review = [i for i in items if i.get("needs_review")]
        if needs_review:
            st.warning(f"⚠️ {len(needs_review)} 条型号置信度偏低，请人工确认后再继续")

        df = pd.DataFrame([{
            "完整型号": i.get("model_full", ""),
            "订货号": i.get("model_short", ""),
            "产品描述": i.get("description", ""),
            "数量": i.get("qty", 0),
            "单位": i.get("unit", "个"),
            "品牌": i.get("brand", "BALLUFF"),
            "状态": "⚠️需确认" if i.get("needs_review") else "✅正常",
        } for i in items])

        edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")

        for idx, row in edited_df.iterrows():
            if idx < len(items):
                items[idx]["model_full"] = row["完整型号"]
                items[idx]["model_short"] = row["订货号"]
                items[idx]["description"] = row["产品描述"]
                items[idx]["qty"] = int(row["数量"]) if str(row["数量"]).isdigit() else items[idx]["qty"]
                items[idx]["unit"] = row["单位"]
                items[idx]["brand"] = row["品牌"]

        st.session_state["confirmed_items"] = items

        st.markdown("---")
        st.subheader("Step 3｜生成上游询价单（发给厂商）")
        brand = st.text_input("品牌", value=items[0].get("brand", "BALLUFF") if items else "BALLUFF")
        if st.button("📥 生成询价Excel"):
            path = gen_upstream_inquiry(items, brand)
            with open(path, "rb") as f:
                st.download_button(
                    "⬇️ 下载询价单",
                    f.read(),
                    file_name=os.path.basename(path),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        st.markdown("---")
        st.subheader("Step 4｜录入进价 → 生成客户报价单")

        col1, col2 = st.columns([2, 1])
        with col1:
            client_name = st.text_input("客户名称", placeholder="如：上海科致电气自动化股份有限公司")
        with col2:
            markup_rate = st.number_input("加价率", min_value=1.0, max_value=3.0, value=1.30, step=0.05)

        st.caption("录入厂商回复的含税单价和货期（有几条填几条，未填的显示为待定）：")

        cols_header = st.columns([3, 2, 2])
        cols_header[0].markdown("**型号**")
        cols_header[1].markdown("**含税进价（元）**")
        cols_header[2].markdown("**货期**")

        for i, item in enumerate(items):
            col_m, col_p, col_d = st.columns([3, 2, 2])
            col_m.text(item.get("model_short") or item.get("model_full", "")[:25])
            price = col_p.number_input(
                f"p{i}", min_value=0.0, step=1.0, key=f"price_{i}",
                label_visibility="collapsed"
            )
            delivery = col_d.text_input(
                f"d{i}", key=f"delivery_{i}",
                label_visibility="collapsed", placeholder="如：4周"
            )
            items[i]["purchase_price"] = price
            items[i]["delivery_weeks"] = delivery

        items_priced = apply_markup(items, markup_rate)

        filled = [i for i in items_priced if i.get("purchase_price", 0) > 0]
        if filled:
            total = sum(i.get("total_price", 0) for i in filled)
            cost = sum(i.get("purchase_price", 0) * i.get("qty", 0) for i in filled)
            profit = total - cost
            c1, c2, c3 = st.columns(3)
            c1.metric("含税报价总额", f"¥{total:,.2f}")
            c2.metric("预计毛利", f"¥{profit:,.2f}")
            c3.metric("毛利率", f"{profit/total*100:.1f}%" if total else "—")

        if st.button("📊 生成客户报价单", type="primary"):
            if not client_name:
                st.error("请填写客户名称")
            else:
                path = gen_customer_quote(items_priced, client_name, markup_rate)
                st.session_state["quote_items"] = items_priced
                st.session_state["quote_client"] = client_name
                with open(path, "rb") as f:
                    st.download_button(
                        "⬇️ 下载客户报价单",
                        f.read(),
                        file_name=os.path.basename(path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                st.success("✅ 报价单已生成！客户确认后前往「生成合同」页面")


# ══════════════════════════════════════════════
# 页面 2：生成合同
# ══════════════════════════════════════════════

elif page == "📄 生成合同":
    st.title("📄 合同生成")

    has_prev = "quote_items" in st.session_state
    if has_prev:
        st.success(f"已读取报价：{st.session_state.get('quote_client','')}，{len(st.session_state['quote_items'])} 条产品")
        items = st.session_state["quote_items"]
        default_client = st.session_state.get("quote_client", "")
    else:
        st.info("请先在「询价解析」页完成报价，数据将自动带入")
        items = []
        default_client = ""

    st.subheader("客户信息")
    clients = get_all_clients()
    client_names = [c["name"] for c in clients]

    selected_client = st.selectbox("选择客户", ["手动输入..."] + client_names)

    if selected_client == "手动输入...":
        c1, c2 = st.columns(2)
        client_name = c1.text_input("客户名称", value=default_client)
        client_address = c2.text_input("地址")
        c3, c4 = st.columns(2)
        client_bank = c3.text_input("开户银行")
        client_account = c4.text_input("账号")
        c5, c6 = st.columns(2)
        client_tax = c5.text_input("税号")
        client_phone = c6.text_input("电话")
        client_info = {
            "name": client_name, "address": client_address,
            "bank": client_bank, "account": client_account,
            "tax_no": client_tax, "phone": client_phone, "contact": ""
        }
        if st.button("💾 保存此客户档案"):
            save_client(client_name, client_address, client_bank, client_account, client_tax, "", client_phone)
            st.success("已保存")
    else:
        client_data = next(c for c in clients if c["name"] == selected_client)
        client_info = dict(client_data)
        st.json(client_info, expanded=False)

    st.subheader("合同参数")
    c1, c2 = st.columns(2)
    contract_no = c1.text_input("合同编号", value=generate_contract_no())
    sign_date = c2.text_input("签订日期（空则自动填今天）", value="")

    payment_options = {
        "30%预付+余款到发货": "合同签订时需方支付30%预付，余款款到发货",
        "款到发货": "款到发货",
        "月结30天": "月结30天，发票开具后30天内付款",
        "自定义": ""
    }
    pay_choice = st.selectbox("付款方式", list(payment_options.keys()))
    if pay_choice == "自定义":
        payment_terms = st.text_area("自定义条款", height=60)
    else:
        payment_terms = payment_options[pay_choice]

    if items:
        st.subheader("产品明细")
        total = sum(i.get("sale_price", 0) * i.get("qty", 0) for i in items)
        st.dataframe(pd.DataFrame([{
            "型号": i.get("model_short") or i.get("model_full", ""),
            "制造商": i.get("brand", "巴鲁夫"),
            "数量": i.get("qty", 0),
            "含税单价": i.get("sale_price", 0),
            "总价": round(i.get("sale_price", 0) * i.get("qty", 0), 2),
            "货期": i.get("delivery_weeks", ""),
        } for i in items]), use_container_width=True)
        st.markdown(f"**含税合计：¥{total:,.2f}（{amount_to_chinese(total)}）**")

    if st.button("📄 生成PDF合同", type="primary"):
        if not items:
            st.error("无产品数据，请先完成报价流程")
        elif not client_info.get("name"):
            st.error("请填写客户名称")
        else:
            with st.spinner("生成中..."):
                try:
                    path = gen_contract_pdf(
                        contract_no=contract_no,
                        client_info=client_info,
                        items=items,
                        payment_terms=payment_terms,
                        sign_date=sign_date or None,
                    )
                    save_order(contract_no, client_info["name"], items, 1.3, notes=payment_terms)
                    with open(path, "rb") as f:
                        st.download_button(
                            "⬇️ 下载合同PDF",
                            f.read(),
                            file_name=os.path.basename(path),
                            mime="application/pdf"
                        )
                    st.success("✅ 合同生成，订单已录入看板")
                except Exception as e:
                    st.error(f"失败：{e}")
                    st.exception(e)


# ══════════════════════════════════════════════
# 页面 3：订单看板
# ══════════════════════════════════════════════

elif page == "📊 订单看板":
    st.title("📊 订单看板")
    orders = get_all_orders()

    if not orders:
        st.info("暂无订单。完成报价并生成合同后自动录入。")
    else:
        import datetime
        month = datetime.datetime.now().strftime("%Y-%m")
        month_orders = [o for o in orders if o["created_at"].startswith(month)]
        pending = [o for o in orders if o["status"] not in ["回款完成"]]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("总订单数", len(orders))
        c2.metric("本月新增", len(month_orders))
        c3.metric("本月金额", f"¥{sum(o['total_amount'] or 0 for o in month_orders):,.0f}")
        c4.metric("待回款", f"¥{sum(o['total_amount'] or 0 for o in pending):,.0f}")

        st.markdown("---")
        STATUS_LIST = ["询价中", "已报价", "合同签订", "采购备货", "已发货", "回款完成"]
        status_filter = st.selectbox("筛选", ["全部"] + STATUS_LIST)
        filtered = orders if status_filter == "全部" else [o for o in orders if o["status"] == status_filter]

        for order in filtered:
            with st.expander(f"📋 {order['contract_no']} | {order['client_name']} | ¥{order['total_amount']:,.2f} | {order['status']}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**客户：** {order['client_name']}")
                    st.write(f"**时间：** {order['created_at']}")
                    if order["notes"]:
                        st.write(f"**付款：** {order['notes']}")
                with col2:
                    new_status = st.selectbox(
                        "状态", STATUS_LIST,
                        index=STATUS_LIST.index(order["status"]) if order["status"] in STATUS_LIST else 0,
                        key=f"s_{order['id']}"
                    )
                    if st.button("更新", key=f"u_{order['id']}"):
                        update_order_status(order["id"], new_status)
                        st.rerun()


# ══════════════════════════════════════════════
# 页面 4：客户档案
# ══════════════════════════════════════════════

elif page == "👥 客户档案":
    st.title("👥 客户档案")
    clients = get_all_clients()

    with st.form("add_client"):
        st.subheader("新增客户")
        c1, c2 = st.columns(2)
        name = c1.text_input("客户名称 *")
        contact = c2.text_input("联系人")
        c3, c4 = st.columns(2)
        phone = c3.text_input("电话")
        address = c4.text_input("地址")
        c5, c6 = st.columns(2)
        bank = c5.text_input("开户银行")
        account = c6.text_input("账号")
        tax_no = st.text_input("税号")
        if st.form_submit_button("保存") and name:
            save_client(name, address, bank, account, tax_no, contact, phone)
            st.success(f"✅ {name} 已保存")
            st.rerun()

    st.markdown("---")
    st.subheader(f"已有客户（{len(clients)}）")
    if clients:
        st.dataframe(
            pd.DataFrame(clients)[["name", "contact", "phone", "address", "tax_no"]].rename(
                columns={"name": "名称", "contact": "联系人", "phone": "电话",
                         "address": "地址", "tax_no": "税号"}
            ),
            use_container_width=True
        )
