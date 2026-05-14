import streamlit as st
import pandas as pd
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(__file__))

from modules.db import (init_db, generate_contract_no, save_order,
                         get_all_orders, get_order_items, update_order,
                         update_order_status, delete_order,
                         get_all_clients, save_client, update_client, delete_client)
from modules.parser import parse_excel, parse_image, parse_text, parse_pdf, apply_markup, flag_low_confidence
from modules.excel_gen import gen_upstream_inquiry, gen_customer_quote
from modules.contract_gen import gen_contract_pdf, amount_to_chinese
from config import SUPPLIER_INFO

st.set_page_config(page_title="QuoteFlow AI", layout="wide")
init_db()

# ── 解析上游Excel报价单（辅助函数）─────────────
def parse_upstream_excel(file_path):
    df_raw = pd.read_excel(file_path, header=None)
    header_row = 0
    for i, row in df_raw.iterrows():
        row_str = " ".join(str(v).lower() for v in row.values)
        if any(k in row_str for k in ["型号", "单价", "price", "货期", "含税"]):
            header_row = i
            break
    df = pd.read_excel(file_path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    def find_col(candidates):
        for name in candidates:
            for col in df.columns:
                if name.lower() in col.lower():
                    return col
        return None

    model_col    = find_col(["型号", "model", "part", "订货号"])
    price_col    = find_col(["含税单价", "单价", "price"])
    delivery_col = find_col(["货期", "delivery", "交期"])

    results = {}
    for _, row in df.iterrows():
        model = str(row[model_col]).strip() if model_col else ""
        if not model or model in ["nan", "合计", "小计", ""]:
            continue
        try:
            price = float(str(row[price_col]).replace(",","").replace("¥","").replace("￥","")) if price_col else 0.0
        except Exception:
            price = 0.0
        delivery = str(row[delivery_col]).strip() if delivery_col and str(row.get(delivery_col,"")) != "nan" else ""
        results[model] = {"purchase_price": price, "delivery_weeks": delivery}
    return results


# ── 导航 ─────────────────────────────────────
page = st.sidebar.selectbox(
    "功能导航",
    ["报价全流程", "生成合同", "订单看板", "客户档案"],
    label_visibility="collapsed"
)
st.sidebar.markdown("---")
st.sidebar.markdown(f"**{SUPPLIER_INFO['name'][:10]}**")
st.sidebar.caption(f"联系人：{SUPPLIER_INFO['contact']}")


# ══════════════════════════════════════════════
# 页面1：报价全流程（询价+上游报价合并）
# ══════════════════════════════════════════════
if page == "报价全流程":
    st.title("报价全流程")

    # ── Step 1：上传客户询价单 ─────────────────
    st.subheader("Step 1 | 上传客户询价单")
    input_method = st.radio("格式", ["Excel / PDF", "图片截图", "粘贴文字"], horizontal=True)

    items = []

    if input_method == "Excel / PDF":
        uploaded = st.file_uploader("上传询价单", type=["xlsx","xls","pdf"], key="inq")
        if uploaded:
            suffix = ".pdf" if uploaded.name.lower().endswith(".pdf") else ".xlsx"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded.read()); tmp_path = tmp.name
            try:
                with st.spinner("解析中..."):
                    items = parse_pdf(tmp_path, mode="inquiry") if suffix==".pdf" else parse_excel(tmp_path)
                    items = flag_low_confidence(items)
                st.success(f"识别到 {len(items)} 条产品")
                st.session_state["parsed_items"] = items
            except Exception as e:
                st.error(f"解析失败：{e}")
            finally:
                os.unlink(tmp_path)

    elif input_method == "图片截图":
        uploaded = st.file_uploader("上传图片", type=["png","jpg","jpeg"], key="img")
        if uploaded:
            st.image(uploaded, width=500)
            if st.button("AI识别图片", type="primary"):
                with st.spinner("识别中..."):
                    try:
                        items = parse_image(uploaded.getvalue(),
                                            "image/png" if uploaded.name.endswith(".png") else "image/jpeg")
                        items = flag_low_confidence(items)
                        st.session_state["parsed_items"] = items
                        st.success(f"识别到 {len(items)} 条产品")
                    except Exception as e:
                        st.error(f"识别失败：{e}")

    elif input_method == "粘贴文字":
        raw = st.text_area("粘贴询价内容", height=180)
        if st.button("AI解析", type="primary") and raw:
            with st.spinner("解析中..."):
                try:
                    items = parse_text(raw)
                    items = flag_low_confidence(items)
                    st.session_state["parsed_items"] = items
                    st.success(f"解析到 {len(items)} 条产品")
                except Exception as e:
                    st.error(f"解析失败：{e}")

    if not items and "parsed_items" in st.session_state:
        items = st.session_state["parsed_items"]

    if not items:
        st.stop()

    # ── Step 2：核对明细 ───────────────────────
    st.markdown("---")
    st.subheader("Step 2 | 核对产品明细")

    if any(i.get("needs_review") for i in items):
        st.warning(f"{sum(1 for i in items if i.get('needs_review'))} 条置信度偏低，请确认")

    edited_df = st.data_editor(pd.DataFrame([{
        "完整型号": i.get("model_full",""),
        "订货号":   i.get("model_short",""),
        "描述":     i.get("description",""),
        "数量":     i.get("qty",0),
        "单位":     i.get("unit","只"),
        "品牌":     i.get("brand","BALLUFF"),
        "状态":     "需确认" if i.get("needs_review") else "正常",
    } for i in items]), use_container_width=True, num_rows="dynamic")

    for idx, row in edited_df.iterrows():
        if idx < len(items):
            items[idx].update({
                "model_full": row["完整型号"], "model_short": row["订货号"],
                "description": row["描述"],
                "qty": int(row["数量"]) if str(row["数量"]).isdigit() else items[idx]["qty"],
                "unit": row["单位"], "brand": row["品牌"],
            })
    st.session_state["confirmed_items"] = items

    # ── Step 3：生成上游询价单 ─────────────────
    st.markdown("---")
    st.subheader("Step 3 | 生成上游询价单（发给厂商）")
    col_a, col_b = st.columns([3,1])
    brand = col_a.text_input("品牌", value=items[0].get("brand","BALLUFF"))
    if col_b.button("生成并下载", key="gen_inq"):
        path = gen_upstream_inquiry(items, brand)
        with open(path,"rb") as f:
            st.download_button("下载询价Excel", f.read(),
                file_name=os.path.basename(path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ── Step 4：导入厂商报价（同页面）─────────
    st.markdown("---")
    st.subheader("Step 4 | 导入厂商报价单（收到回复后操作）")

    up2 = st.file_uploader("上传厂商报价单（Excel或PDF）", type=["xlsx","xls","pdf"], key="upstream")
    quote_data = st.session_state.get("quote_data", {})

    if up2:
        suffix2 = ".pdf" if up2.name.lower().endswith(".pdf") else ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix2) as tmp2:
            tmp2.write(up2.read()); tmp2_path = tmp2.name
        try:
            with st.spinner("解析厂商报价..."):
                quote_data = parse_pdf(tmp2_path, mode="quote") if suffix2==".pdf" else parse_upstream_excel(tmp2_path)
            st.session_state["quote_data"] = quote_data
            st.success(f"解析到 {len(quote_data)} 条厂商报价")
        except Exception as e:
            st.error(f"解析失败：{e}")
        finally:
            os.unlink(tmp2_path)

    # ── Step 5：设置加价系数，预览报价 ────────
    st.markdown("---")
    st.subheader("Step 5 | 设置加价系数 & 确认报价")

    col1, col2, col3 = st.columns([2,1,1])
    client_name  = col1.text_input("客户名称", placeholder="如：上海科致电气自动化股份有限公司")
    markup_rate  = col2.number_input("默认加价率", min_value=1.0, max_value=3.0, value=1.30, step=0.05)

    imported_prices  = st.session_state.get("imported_prices", {})
    imported_markups = st.session_state.get("imported_markups", {})

    # 自动从quote_data填入进价
    if quote_data and not imported_prices:
        for item in items:
            mk = item.get("model_short") or item.get("model_full","")
            if mk in quote_data:
                imported_prices[mk]  = quote_data[mk]
                imported_markups[mk] = markup_rate

    cols_h = st.columns([3,2,2,1])
    cols_h[0].markdown("**型号**"); cols_h[1].markdown("**含税进价**")
    cols_h[2].markdown("**货期**"); cols_h[3].markdown("**系数**")

    for i, item in enumerate(items):
        mk = item.get("model_short") or item.get("model_full","")
        cm1, cm2, cm3, cm4 = st.columns([3,2,2,1])
        cm1.text(mk[:28])
        default_p = imported_prices.get(mk, {}).get("purchase_price", 0.0)
        default_d = imported_prices.get(mk, {}).get("delivery_weeks", "")
        default_m = imported_markups.get(mk, markup_rate)

        price    = cm2.number_input(f"p{i}", min_value=0.0, step=1.0, value=float(default_p),
                                    key=f"price_{i}", label_visibility="collapsed")
        delivery = cm3.text_input(f"d{i}", value=default_d, key=f"delivery_{i}",
                                   label_visibility="collapsed", placeholder="如：现货/4周")
        sku_rate = cm4.number_input(f"r{i}", min_value=1.0, max_value=3.0, value=float(default_m),
                                    step=0.05, key=f"rate_{i}", label_visibility="collapsed")
        items[i].update({"purchase_price": price, "delivery_weeks": delivery, "sku_markup_rate": sku_rate})

    # 计算报价
    for item in items:
        p = item.get("purchase_price", 0.0)
        r = item.get("sku_markup_rate", markup_rate)
        if p > 0:
            s = round(p * r, 2)
            item["sale_price"]  = s
            item["total_price"] = round(s * item.get("qty",0), 2)
        else:
            item["sale_price"] = item["total_price"] = 0.0

    filled = [i for i in items if i.get("purchase_price",0) > 0]
    if filled:
        total  = sum(i["total_price"] for i in filled)
        cost   = sum(i["purchase_price"] * i["qty"] for i in filled)
        profit = total - cost
        c1,c2,c3 = st.columns(3)
        c1.metric("含税报价总额", f"¥{total:,.2f}")
        c2.metric("预计毛利",     f"¥{profit:,.2f}")
        c3.metric("毛利率",       f"{profit/total*100:.1f}%" if total else "—")

    col_x, col_y = st.columns(2)
    if col_x.button("生成客户报价Excel", type="primary"):
        if not client_name:
            st.error("请填写客户名称")
        else:
            path = gen_customer_quote(items, client_name, markup_rate)
            st.session_state["quote_items"]  = items
            st.session_state["quote_client"] = client_name
            with open(path,"rb") as f:
                st.download_button("下载报价单", f.read(),
                    file_name=os.path.basename(path),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.success("报价单生成！客户确认后前往「生成合同」")

    if col_y.button("客户已确认，直接去生成合同"):
        if not client_name:
            st.error("请填写客户名称")
        else:
            st.session_state["quote_items"]  = items
            st.session_state["quote_client"] = client_name
            st.success("已保存，请点击左侧「生成合同」")


# ══════════════════════════════════════════════
# 页面2：生成合同
# ══════════════════════════════════════════════
elif page == "生成合同":
    st.title("生成合同")

    items          = st.session_state.get("quote_items", [])
    default_client = st.session_state.get("quote_client", "")

    if items:
        st.success(f"已读取报价：{default_client}，{len(items)} 条产品")
    else:
        st.info("请先在「报价全流程」页面完成报价")

    st.subheader("客户信息")
    clients      = get_all_clients()
    client_names = [c["name"] for c in clients]
    selected     = st.selectbox("选择客户", ["手动输入..."] + client_names)

    if selected == "手动输入...":
        c1,c2 = st.columns(2)
        cn  = c1.text_input("客户名称", value=default_client)
        ca  = c2.text_input("地址")
        c3,c4 = st.columns(2)
        cb  = c3.text_input("开户银行")
        cac = c4.text_input("账号")
        c5,c6 = st.columns(2)
        ct  = c5.text_input("税号")
        cp  = c6.text_input("电话")
        cc  = st.text_input("委托代理人")
        client_info = {"name":cn,"address":ca,"bank":cb,"account":cac,
                       "tax_no":ct,"phone":cp,"contact":cc}
        if st.button("保存客户档案"):
            save_client(cn,ca,cb,cac,ct,cc,cp)
            st.success("已保存")
    else:
        client_info = dict(next(c for c in clients if c["name"]==selected))
        st.json(client_info, expanded=False)

    st.subheader("合同参数")
    c1,c2 = st.columns(2)
    contract_no = c1.text_input("合同编号", value=generate_contract_no())
    sign_date   = c2.text_input("签订日期（空则自动填今天）", value="")

    payment_opts = {
        "款到发货":           "款到发货",
        "现货款到发货":       "现货 款到发货",
        "30%预付+余款到发货": "合同签订后需方支付30%预付，余款款到发货",
        "自定义":             ""
    }
    pay_choice    = st.selectbox("付款方式", list(payment_opts.keys()))
    payment_terms = st.text_area("自定义", height=50) if pay_choice=="自定义" else payment_opts[pay_choice]

    if items:
        total = sum(i.get("sale_price",0)*i.get("qty",0) for i in items)
        st.subheader("产品明细预览")
        st.dataframe(pd.DataFrame([{
            "型号":     i.get("model_short") or i.get("model_full",""),
            "单位":     i.get("unit","只"),
            "数量":     i.get("qty",0),
            "含税单价": i.get("sale_price",0),
            "总价":     round(i.get("sale_price",0)*i.get("qty",0),2),
            "货期":     i.get("delivery_weeks",""),
        } for i in items]), use_container_width=True)
        st.markdown(f"**含税合计：¥{total:,.2f}（{amount_to_chinese(total)}）**")

    if st.button("生成PDF合同", type="primary"):
        if not items:
            st.error("请先完成报价")
        elif not client_info.get("name"):
            st.error("请填写客户名称")
        else:
            with st.spinner("生成中..."):
                try:
                    path = gen_contract_pdf(contract_no, client_info, items,
                                            payment_terms, sign_date or None)
                    save_order(contract_no, client_info["name"], items, 1.3, notes=payment_terms)
                    with open(path,"rb") as f:
                        st.download_button("下载合同PDF", f.read(),
                            file_name=os.path.basename(path), mime="application/pdf")
                    st.success("合同已生成，订单已录入看板")
                except Exception as e:
                    st.error(f"失败：{e}"); st.exception(e)


# ══════════════════════════════════════════════
# 页面3：订单看板（支持编辑删除）
# ══════════════════════════════════════════════
elif page == "订单看板":
    st.title("订单看板")
    orders = get_all_orders()

    if not orders:
        st.info("暂无订单")
    else:
        import datetime
        month        = datetime.datetime.now().strftime("%Y-%m")
        month_orders = [o for o in orders if o["created_at"].startswith(month)]
        pending      = [o for o in orders if o["status"] not in ["回款完成"]]

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("总订单数", len(orders))
        c2.metric("本月新增", len(month_orders))
        c3.metric("本月金额", f"¥{sum(o['total_amount'] or 0 for o in month_orders):,.0f}")
        c4.metric("待回款",   f"¥{sum(o['total_amount'] or 0 for o in pending):,.0f}")

        st.markdown("---")
        STATUS_LIST   = ["询价中","已报价","合同签订","采购备货","已发货","回款完成"]
        status_filter = st.selectbox("筛选状态", ["全部"]+STATUS_LIST)
        filtered = orders if status_filter=="全部" else [o for o in orders if o["status"]==status_filter]

        for order in filtered:
            oid = order["id"]
            with st.expander(f"{order['contract_no']} | {order['client_name']} | ¥{order['total_amount']:,.2f} | {order['status']}"):
                tab1, tab2 = st.tabs(["查看 / 状态", "编辑 / 删除"])

                with tab1:
                    st.write(f"**客户：** {order['client_name']}")
                    st.write(f"**合同号：** {order['contract_no']}")
                    st.write(f"**金额：** ¥{order['total_amount']:,.2f}")
                    st.write(f"**创建：** {order['created_at']}")
                    if order["notes"]:
                        st.write(f"**付款：** {order['notes']}")
                    new_status = st.selectbox("更新状态", STATUS_LIST,
                        index=STATUS_LIST.index(order["status"]) if order["status"] in STATUS_LIST else 0,
                        key=f"st_{oid}")
                    if st.button("更新状态", key=f"upd_{oid}"):
                        update_order_status(oid, new_status)
                        st.rerun()

                with tab2:
                    e_contract = st.text_input("合同编号", value=order["contract_no"], key=f"ec_{oid}")
                    e_client   = st.text_input("客户名称", value=order["client_name"],  key=f"ecl_{oid}")
                    e_amount   = st.number_input("金额", value=float(order["total_amount"] or 0), key=f"ea_{oid}")
                    e_notes    = st.text_input("备注", value=order["notes"] or "", key=f"en_{oid}")
                    e_status   = st.selectbox("状态", STATUS_LIST,
                        index=STATUS_LIST.index(order["status"]) if order["status"] in STATUS_LIST else 0,
                        key=f"es_{oid}")

                    col_save, col_del = st.columns(2)
                    if col_save.button("保存修改", key=f"save_{oid}"):
                        update_order(oid, e_contract, e_client, e_amount, e_status, e_notes)
                        st.success("已保存")
                        st.rerun()

                    if col_del.button("删除此订单", key=f"del_{oid}", type="primary"):
                        st.session_state[f"confirm_del_{oid}"] = True

                    if st.session_state.get(f"confirm_del_{oid}"):
                        st.warning("确认删除？此操作不可恢复")
                        cc1, cc2 = st.columns(2)
                        if cc1.button("确认删除", key=f"yes_{oid}"):
                            delete_order(oid)
                            st.success("已删除")
                            st.rerun()
                        if cc2.button("取消", key=f"no_{oid}"):
                            st.session_state[f"confirm_del_{oid}"] = False
                            st.rerun()


# ══════════════════════════════════════════════
# 页面4：客户档案（支持编辑删除）
# ══════════════════════════════════════════════
elif page == "客户档案":
    st.title("客户档案")
    clients = get_all_clients()

    with st.form("add_client"):
        st.subheader("新增客户")
        c1,c2   = st.columns(2)
        name    = c1.text_input("客户名称 *")
        contact = c2.text_input("委托代理人")
        c3,c4   = st.columns(2)
        phone   = c3.text_input("电话")
        address = c4.text_input("地址")
        c5,c6   = st.columns(2)
        bank    = c5.text_input("开户银行")
        account = c6.text_input("账号")
        tax_no  = st.text_input("税号")
        if st.form_submit_button("保存") and name:
            save_client(name, address, bank, account, tax_no, contact, phone)
            st.success(f"{name} 已保存")
            st.rerun()

    st.markdown("---")
    st.subheader(f"已有客户（{len(clients)}）")

    for client in clients:
        cid = client["id"]
        with st.expander(f"{client['name']} | {client.get('phone','')}"):
            tab1, tab2 = st.tabs(["查看", "编辑 / 删除"])

            with tab1:
                st.write(f"**名称：** {client['name']}")
                st.write(f"**地址：** {client.get('address','')}")
                st.write(f"**联系人：** {client.get('contact','')}  电话：{client.get('phone','')}")
                st.write(f"**开户银行：** {client.get('bank','')}  账号：{client.get('account','')}")
                st.write(f"**税号：** {client.get('tax_no','')}")

            with tab2:
                e_name    = st.text_input("名称",   value=client["name"],              key=f"cn_{cid}")
                e_addr    = st.text_input("地址",   value=client.get("address",""),    key=f"ca_{cid}")
                e_contact = st.text_input("联系人", value=client.get("contact",""),    key=f"cc_{cid}")
                e_phone   = st.text_input("电话",   value=client.get("phone",""),      key=f"cp_{cid}")
                e_bank    = st.text_input("开户银行", value=client.get("bank",""),     key=f"cb_{cid}")
                e_account = st.text_input("账号",   value=client.get("account",""),    key=f"cac_{cid}")
                e_tax     = st.text_input("税号",   value=client.get("tax_no",""),     key=f"ct_{cid}")

                col_s, col_d = st.columns(2)
                if col_s.button("保存修改", key=f"csave_{cid}"):
                    update_client(cid, e_name, e_addr, e_bank, e_account, e_tax, e_contact, e_phone)
                    st.success("已保存")
                    st.rerun()

                if col_d.button("删除客户", key=f"cdel_{cid}", type="primary"):
                    st.session_state[f"confirm_cdel_{cid}"] = True

                if st.session_state.get(f"confirm_cdel_{cid}"):
                    st.warning("确认删除？")
                    cd1, cd2 = st.columns(2)
                    if cd1.button("确认", key=f"cyes_{cid}"):
                        delete_client(cid)
                        st.success("已删除")
                        st.rerun()
                    if cd2.button("取消", key=f"cno_{cid}"):
                        st.session_state[f"confirm_cdel_{cid}"] = False
                        st.rerun()