import streamlit as st
import json, os, io
import pandas as pd
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

st.set_page_config(page_title="Property Cost Calculator", layout="wide", page_icon="🏠")

# ── Constants ──────────────────────────────────────────────────────────────────
COST_ITEMS = [
    ("Legal Fees",            "purchase"),
    ("Property Transfer Tax", "purchase"),
    ("Registration Duty",     "purchase"),
    ("Notary Fee",            "purchase"),
    ("Agent Fee",             "purchase"),
    ("Stamp Duty",            "purchase"),
    ("Property Registration", "purchase"),
    ("Bank Fee",              "loan"),
    ("Court Fee",             "loan"),
]
DEFAULT_RATES = {
    "Legal Fees": 1.5, "Property Transfer Tax": 3.5, "Registration Duty": 1.1,
    "Notary Fee": 1.0, "Agent Fee": 3.0, "Stamp Duty": 1.0,
    "Property Registration": 1.1, "Bank Fee": 1.0, "Court Fee": 1.2,
}
DEFAULT_VATS = {"Legal Fees": 20.0, "Notary Fee": 20.0, "Agent Fee": 20.0}
DEFAULT_MONTHLY = [
    {"name": "Betriebskosten",    "amount": 223.10},
    {"name": "Reparaturrücklage", "amount": 145.50},
    {"name": "Sonstige Kosten",   "amount":  43.46},
    {"name": "VAT",               "amount":  26.66},
]

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_analyses.json")

# ── Storage ────────────────────────────────────────────────────────────────────
def load_analyses():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def persist(analyses):
    with open(DATA_FILE, "w") as f:
        json.dump(analyses, f, indent=2)

def upsert_analysis(data):
    analyses = load_analyses()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for i, a in enumerate(analyses):
        if a.get("id") and a["id"] == data.get("id"):
            data["saved_at"] = now
            analyses[i] = data
            persist(analyses)
            return
    data["saved_at"] = now
    data["id"] = datetime.now().strftime("%Y%m%d%H%M%S%f")
    analyses.append(data)
    persist(analyses)

def delete_analysis(aid):
    persist([a for a in load_analyses() if a.get("id") != aid])

# ── Compute ────────────────────────────────────────────────────────────────────
def compute(data):
    pp   = data["purchase_price"]
    dp   = data["down_payment"]
    loan = max(0, pp - dp)
    item_costs = {}
    for item, applies in COST_ITEMS:
        slug = item.lower().replace(" ", "_")
        rate = data["rates"].get(slug, DEFAULT_RATES.get(item, 1.0)) / 100
        vat  = data["vats"].get(slug,  DEFAULT_VATS.get(item, 0.0))  / 100
        base = pp if applies == "purchase" else loan
        item_costs[item] = base * rate * (1 + vat)
    if data.get("is_new_build") and data["rates"].get("new_build_vat", 0) > 0:
        item_costs["VAT (New Build)"] = pp * data["rates"]["new_build_vat"] / 100
    total   = sum(item_costs.values())
    monthly = sum(c["amount"] for c in data.get("monthly_costs", [
        {"name": k, "amount": data.get(v, d)}
        for k, v, d in [("Betriebskosten","betriebskosten",223.10),
                        ("Reparaturrücklage","ruecklage",145.50),
                        ("Sonstige Kosten","sonstiges",43.46),
                        ("VAT","vat_monthly",26.66)]
    ]))
    return {
        "loan_amount": loan, "monthly_total": monthly,
        "item_costs": item_costs, "total_costs": total,
        "final_purchase_price": pp + total,
        "cash_needed": dp + total,
        "cost_pct": (total / pp * 100) if pp else 0,
    }

def monthly_repayment(principal, annual_rate_pct, years):
    if annual_rate_pct == 0 or years == 0:
        return principal / (years * 12) if years else 0
    r = annual_rate_pct / 100 / 12
    n = years * 12
    return principal * r * (1 + r)**n / ((1 + r)**n - 1)

# ── PDF ────────────────────────────────────────────────────────────────────────
def generate_pdf(data, r, mortgage):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles  = getSampleStyleSheet()
    title_s = ParagraphStyle("t", fontSize=18, fontName="Helvetica-Bold", spaceAfter=4,  alignment=TA_CENTER)
    sub_s   = ParagraphStyle("s", fontSize=10, fontName="Helvetica", textColor=colors.grey, alignment=TA_CENTER, spaceAfter=16)
    head_s  = ParagraphStyle("h", fontSize=12, fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6)
    normal  = styles["Normal"]

    def tbl2(rows):
        t = Table(rows, colWidths=[10*cm, 6*cm])
        t.setStyle(TableStyle([
            ("FONTSIZE",       (0,0),(-1,-1), 9),
            ("ROWBACKGROUNDS", (0,0),(-1,-1), [colors.whitesmoke, colors.white]),
            ("GRID",           (0,0),(-1,-1), 0.3, colors.lightgrey),
            ("ALIGN",          (1,0),(1,-1),  "RIGHT"),
            ("BOTTOMPADDING",  (0,0),(-1,-1), 5),
            ("TOPPADDING",     (0,0),(-1,-1), 5),
        ]))
        return t

    pp = data["purchase_price"]; dp = data["down_payment"]
    label = data.get("label","Property"); url = data.get("url","")
    story = [
        Paragraph("Property Cost Summary", title_s),
        Paragraph(f"{label}  |  {data.get('saved_at', datetime.now().strftime('%Y-%m-%d %H:%M'))}", sub_s),
        HRFlowable(width="100%", thickness=1, color=colors.lightgrey), Spacer(1,10),
    ]
    if url:
        story += [Paragraph(f'Listing: <a href="{url}">{url}</a>', normal), Spacer(1,8)]

    story += [Paragraph("Key Figures", head_s), tbl2([
        ["Purchase Price",         f"EUR {pp:,.2f}"],
        ["Down Payment",           f"EUR {dp:,.2f}"],
        ["Loan Amount",            f"EUR {r['loan_amount']:,.2f}"],
        ["Total Additional Costs", f"EUR {r['total_costs']:,.2f}"],
        ["Final Purchase Price",   f"EUR {r['final_purchase_price']:,.2f}"],
        ["Cash Needed",            f"EUR {r['cash_needed']:,.2f}"],
        ["Monthly Running Costs",  f"EUR {r['monthly_total']:,.2f}"],
    ])]

    sqm = data.get("sqm",0); rating = data.get("rating",0); notes = data.get("notes","")
    extras = []
    if sqm:    extras += [["Size", f"{sqm} m²"], ["Price per m²", f"EUR {pp/sqm:,.0f}"]]
    if rating: extras.append(["Rating", "★"*rating+"☆"*(5-rating)])
    if data.get("is_new_build"): extras.append(["New Build","Yes"])
    if extras:
        story += [Paragraph("Property Details", head_s), tbl2(extras)]

    cost_rows = [["Item","Basis","Cost"]]
    for item, cost in r["item_costs"].items():
        applies = dict(COST_ITEMS).get(item,"purchase")
        basis = "Purchase Price" if applies=="purchase" or item=="VAT (New Build)" else "Loan Amount"
        cost_rows.append([item, basis, f"EUR {cost:,.2f}"])
    cost_rows.append(["TOTAL","",f"EUR {r['total_costs']:,.2f}"])
    ct = Table(cost_rows, colWidths=[7*cm,5*cm,4*cm])
    ct.setStyle(TableStyle([
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[colors.whitesmoke,colors.white]),
        ("GRID",(0,0),(-1,-1),0.3,colors.lightgrey),("ALIGN",(2,0),(2,-1),"RIGHT"),
        ("LINEABOVE",(0,-1),(-1,-1),1,colors.grey),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),("TOPPADDING",(0,0),(-1,-1),5),
    ]))
    story += [Paragraph("Cost Breakdown", head_s), ct]

    if mortgage and mortgage.get("monthly"):
        story += [Paragraph("Mortgage", head_s), tbl2([
            ["Interest Rate",       f"{mortgage['rate']:.2f}%"],
            ["Term",                f"{mortgage['years']} years"],
            ["Monthly Repayment",   f"EUR {mortgage['monthly']:,.2f}"],
            ["Total Interest Paid", f"EUR {mortgage['total_interest']:,.2f}"],
            ["Total Amount Repaid", f"EUR {mortgage['total_repaid']:,.2f}"],
        ])]
    if notes:
        story += [Paragraph("Notes", head_s), Paragraph(notes, normal)]

    doc.build(story)
    buf.seek(0)
    return buf

# ── Session state ──────────────────────────────────────────────────────────────
if "preload" not in st.session_state:
    st.session_state.preload = None

def _v(preload, key, default):
    if preload and key in preload:
        val = preload[key]
        try:    return type(default)(val)
        except: return val
    return default

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_calc, tab_mort, tab_decision, tab_saved = st.tabs([
    "🏠 Calculator", "🏦 Mortgage", "📐 Decision Support", "📊 Saved Analyses"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CALCULATOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_calc:
    preload = st.session_state.preload
    def v(key, default): return _v(preload, key, default)

    # Sync preload into widget session state keys exactly once when it first arrives
    last_synced = st.session_state.get("_preload_synced_id")
    current_id  = preload.get("id") if preload else None
    if preload and current_id != last_synced:
        st.session_state["sb_label"] = preload.get("label", "")
        st.session_state["sb_url"]   = preload.get("url", "")
        for item, _ in COST_ITEMS:
            slug = item.lower().replace(" ", "_")
            st.session_state[slug + "_rate"] = float(preload.get("rates", {}).get(slug, DEFAULT_RATES.get(item, 1.0)))
            st.session_state[slug + "_vat"]  = float(preload.get("vats",  {}).get(slug, DEFAULT_VATS.get(item, 0.0)))
        if "new_build_vat" in preload.get("rates", {}):
            st.session_state["new_build_vat_rate"] = float(preload["rates"]["new_build_vat"])
        st.session_state["_preload_synced_id"] = current_id

    # ── Sidebar: summary + save ────────────────────────────────────────────────
    with st.sidebar:
        st.header("💾 Save Analysis")
        label  = st.text_input("Label / Name", value=v("label",""), placeholder="e.g. Vienna Apt 3BR",  key="sb_label")
        url_sb = st.text_input("Listing URL",  value=v("url",""),   placeholder="https://willhaben.at/...", key="sb_url")
        st.caption("Paste a willhaben.at or immoscout24.at link")

        if preload:
            st.info(f"✏️ Editing: **{preload.get('label','')}**", icon="📂")
            if st.button("✖ Start fresh", use_container_width=True):
                st.session_state.preload = None
                st.session_state.pop("monthly_costs", None)
                st.session_state.pop("_preload_synced_id", None)
                st.rerun()

        st.divider()
        st.caption("**Quick Summary**")
        _live = st.session_state.get("_live", {})
        _pp  = _live.get("purchase_price", v("purchase_price", 339_000))
        _dp  = _live.get("down_payment",   v("down_payment",   150_000))
        _tc  = _live.get("total_costs",    0)
        _cn  = _live.get("cash_needed",    _dp)
        st.metric("Purchase Price",    f"€{_pp:,.0f}")
        st.metric("Down Payment",      f"€{_dp:,.0f}")
        st.metric("Loan Amount",       f"€{max(0,_pp-_dp):,.0f}")
        st.metric("Additional Costs",  f"€{_tc:,.2f}")
        st.metric("Cash Needed",       f"€{_cn:,.2f}")

        st.divider()
        _save_btn = st.button("💾 Save", type="primary", use_container_width=True, key="sb_save")

    # ── Main content ───────────────────────────────────────────────────────────
    st.title("🏠 Property Cost Calculator")
    st.caption("Full acquisition cost breakdown including fees, taxes & duties")

    # Re-read label/url from sidebar widgets
    label = st.session_state.get("sb_label", v("label",""))
    url   = st.session_state.get("sb_url",   v("url",""))

    # Two-column layout: left = inputs, right = costs + summary
    left_col, right_col = st.columns([1, 1], gap="large")

    with left_col:
        # ── Property ──────────────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("#### 🏡 Property Details")
            c1, c2, c3 = st.columns(3)
            sqm    = c1.number_input("Size (m²)", value=v("sqm",0), step=1, min_value=0)
            rating = c2.select_slider("Rating", options=[0,1,2,3,4,5], value=v("rating",0),
                                       format_func=lambda x: "☆ Not rated" if x==0 else "★"*x+"☆"*(5-x))
            c3.write("")
            is_new_build = c3.checkbox("🏗 New Build", value=v("is_new_build", False))
            notes = st.text_area("Notes", value=v("notes",""), height=68,
                                  placeholder="Impressions, pros/cons…", label_visibility="collapsed")

        # ── Base inputs ────────────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("#### 💶 Base Inputs")
            c1, c2 = st.columns(2)
            purchase_price = c1.number_input("Purchase Price (€)", value=v("purchase_price",339_000), step=1_000)
            down_payment   = c2.number_input("Down Payment (€)",   value=v("down_payment",  150_000), step=1_000)

            min_down = purchase_price * 0.20
            if down_payment < min_down:
                st.error(f"⚠️ Minimum 20% required — **€{min_down:,.0f}**")
                down_payment = min_down

            loan_amount = max(0, purchase_price - down_payment)
            c1, c2, c3 = st.columns(3)
            c1.metric("Purchase Price", f"€{purchase_price:,.0f}")
            c2.metric("Down Payment",   f"€{down_payment:,.0f}")
            c3.metric("Loan Amount",    f"€{loan_amount:,.0f}")
            if sqm:
                st.metric("Price / m²", f"€{purchase_price/sqm:,.0f}")

        # ── Monthly costs ──────────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("#### 📅 Monthly Costs")

            if "monthly_costs" not in st.session_state:
                saved_mc = v("monthly_costs", None)
                st.session_state.monthly_costs = [dict(r) for r in saved_mc] if saved_mc else [dict(r) for r in DEFAULT_MONTHLY]
            if preload:
                saved_mc = preload.get("monthly_costs")
                if saved_mc and st.session_state.monthly_costs != saved_mc:
                    st.session_state.monthly_costs = [dict(r) for r in saved_mc]

            mc_rows = st.session_state.monthly_costs
            edited = st.data_editor(
                pd.DataFrame(mc_rows),
                column_config={
                    "name":   st.column_config.TextColumn("Description",  width="medium"),
                    "amount": st.column_config.NumberColumn("Amount (€)", width="small", format="€%.2f", step=1.0),
                },
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key="mc_editor",
            )
            # Sync edits back to session state
            st.session_state.monthly_costs = edited.to_dict("records")
            mc_rows = st.session_state.monthly_costs
            monthly_total = sum(float(r.get("amount") or 0) for r in mc_rows)
            st.metric("Total Monthly", f"€{monthly_total:,.2f}")

    with right_col:
        # ── Purchase cost items ────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("#### ⚖️ Purchase Cost Items")
            saved_rates = v("rates", {})
            saved_vats  = v("vats",  {})
            rates, vats, results = {}, {}, {}

            for grp_label, grp_applies in [("📋 Purchase Price","purchase"),("🏦 Loan Amount","loan")]:
                with st.expander(grp_label, expanded=True):
                    # Header row
                    hc1, hc2, hc3, hc4 = st.columns([3, 2, 2, 2])
                    hc1.caption("Item"); hc2.caption("Rate (%)"); hc3.caption("VAT (%)"); hc4.caption("Cost")

                    grp_total = 0.0
                    for item, applies in COST_ITEMS:
                        if applies != grp_applies:
                            continue
                        slug = item.lower().replace(" ","_")
                        base = purchase_price if applies == "purchase" else loan_amount
                        c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                        c1.write(f"**{item}**")
                        rate_e = c2.number_input(
                            "Rate", key=slug+"_rate", format="%.2f", step=0.1,
                            value=float(saved_rates.get(slug, DEFAULT_RATES.get(item, 1.0))),
                            label_visibility="collapsed"
                        )
                        vat_e = c3.number_input(
                            "VAT", key=slug+"_vat", format="%.2f", step=0.1,
                            value=float(saved_vats.get(slug, DEFAULT_VATS.get(item, 0.0))),
                            label_visibility="collapsed"
                        )
                        cost = base * (rate_e / 100) * (1 + vat_e / 100)
                        rates[slug] = rate_e
                        vats[slug]  = vat_e
                        results[item] = cost
                        grp_total += cost
                        c4.metric("cost", f"€{cost:,.2f}", label_visibility="collapsed")

                    if grp_applies == "purchase" and is_new_build:
                        st.divider()
                        nb1, nb2, nb3, nb4 = st.columns([3, 2, 2, 2])
                        nb1.write("**VAT — New Build Only**")
                        nb_rate = nb2.number_input(
                            "Rate %", key="new_build_vat_rate", format="%.1f", step=0.5,
                            value=float(saved_rates.get("new_build_vat", 20.0)),
                            label_visibility="collapsed"
                        )
                        nb3.caption("on Purchase Price")
                        nb_cost = purchase_price * (nb_rate / 100)
                        results["VAT (New Build)"] = nb_cost
                        rates["new_build_vat"] = nb_rate
                        grp_total += nb_cost
                        nb4.metric("cost", f"€{nb_cost:,.2f}", label_visibility="collapsed")
                        st.caption("ℹ️ Reclaimable if renting")

                    st.caption(f"Subtotal: **€{grp_total:,.2f}**")

        # ── Summary ────────────────────────────────────────────────────────────
        total_costs          = sum(results.values())
        final_purchase_price = purchase_price + total_costs
        cash_needed          = down_payment + total_costs
        cost_pct             = (total_costs / purchase_price * 100) if purchase_price else 0

        with st.container(border=True):
            st.markdown("#### 📊 Summary")
            c1, c2, c3 = st.columns(3)
            c1.metric("Additional Costs",     f"€{total_costs:,.2f}",    delta=f"{cost_pct:.1f}% of price", delta_color="inverse")
            c2.metric("Final Purchase Price", f"€{final_purchase_price:,.2f}")
            c3.metric("Cash Needed",          f"€{cash_needed:,.2f}",    delta=f"€{down_payment:,.0f} down + costs", delta_color="off")

        # Persist live values so Mortgage and Decision Support tabs stay in sync
        st.session_state["_live"] = {
            "purchase_price": purchase_price,
            "down_payment":   down_payment,
            "loan_amount":    loan_amount,
            "monthly_costs":  mc_rows,
            "rates":          rates,
            "vats":           vats,
            "is_new_build":   is_new_build,
            "total_costs":    total_costs,
            "cash_needed":    cash_needed,
            "monthly_total":  monthly_total,
        }

    # ── Sidebar save action ────────────────────────────────────────────────────
    if _save_btn:
        if not label:
            st.sidebar.error("Add a label before saving.")
        else:
            record = {
                "id": preload.get("id","") if preload else "",
                "label": label, "url": url,
                "purchase_price": purchase_price, "down_payment": down_payment,
                "is_new_build": is_new_build, "sqm": sqm, "rating": rating, "notes": notes,
                "monthly_costs": mc_rows, "monthly_total": monthly_total,
                "rates": rates, "vats": vats,
                "total_costs": total_costs, "final_purchase_price": final_purchase_price,
                "cash_needed": cash_needed,
                "mort_rate":           v("mort_rate", 3.5),
                "mort_years":          v("mort_years", 25),
                "gross_income":        v("gross_income", 5_000),
                "monthly_rent":        v("monthly_rent", 1_500),
                "annual_appreciation": v("annual_appreciation", 2.0),
                "expected_rent":       v("expected_rent", 1_200),
                "mgmt_cost_pct":       v("mgmt_cost_pct", 10.0),
            }
            upsert_analysis(record)
            st.session_state.preload = None
            st.session_state.pop("monthly_costs", None)
            st.session_state.pop("_preload_synced_id", None)
            st.sidebar.success(f"✅ **{label}** saved!")

    st.caption("Costs calculated based on purchase price or loan amount depending on fee type.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — MORTGAGE
# ══════════════════════════════════════════════════════════════════════════════
with tab_mort:
    preload = st.session_state.preload
    def vm(key, default): return _v(preload, key, default)

    st.title("🏦 Mortgage Calculator")
    st.caption("Annuity mortgage repayment and debt-to-income analysis")
    if preload:
        st.info(f"Figures for: **{preload.get('label','')}**", icon="📂")

    _live_m = st.session_state.get("_live", {})
    pp_m    = float(_live_m.get("purchase_price", vm("purchase_price", 339_000)))
    dp_m    = float(_live_m.get("down_payment",   vm("down_payment",   150_000)))
    loan_m  = float(_live_m.get("loan_amount",    max(0.0, pp_m - dp_m)))
    r_m     = compute({
        "purchase_price": pp_m, "down_payment": dp_m,
        "monthly_costs":  _live_m.get("monthly_costs", vm("monthly_costs", [])),
        "rates":          _live_m.get("rates",          vm("rates", {})),
        "vats":           _live_m.get("vats",           vm("vats",  {})),
        "is_new_build":   _live_m.get("is_new_build",   vm("is_new_build", False)),
    })

    left, right = st.columns([1,1], gap="large")

    with left:
        with st.container(border=True):
            st.markdown("#### 🔢 Loan Details")
            c1, c2 = st.columns(2)
            c1.metric("Loan Amount",    f"€{loan_m:,.0f}")
            c2.metric("Purchase Price", f"€{pp_m:,.0f}")

        with st.container(border=True):
            st.markdown("#### ⚙️ Parameters")
            c1, c2 = st.columns(2)
            mort_rate  = c1.number_input("Interest Rate (%)", value=vm("mort_rate",3.5),  step=0.05, format="%.2f", min_value=0.0)
            mort_years = c2.number_input("Term (years)",      value=vm("mort_years",25),  step=1, min_value=1, max_value=40)
            mort_monthly      = monthly_repayment(loan_m, mort_rate, mort_years)
            mort_total_repaid = mort_monthly * mort_years * 12
            mort_total_int    = mort_total_repaid - loan_m

            st.metric("Monthly Repayment", f"€{mort_monthly:,.2f}")
            c1, c2 = st.columns(2)
            c1.metric("Total Interest Paid", f"€{mort_total_int:,.2f}",
                      delta=f"{(mort_total_int/loan_m*100):.1f}% of loan" if loan_m else None,
                      delta_color="inverse")
            c2.metric("Total Amount Repaid", f"€{mort_total_repaid:,.2f}")

    with right:
        with st.container(border=True):
            st.markdown("#### 📊 Debt-to-Income Check")
            gross_income     = st.number_input("Monthly Gross Income (€)", value=vm("gross_income",5_000), step=100)
            total_obligation = mort_monthly + r_m["monthly_total"]
            dti              = (total_obligation / gross_income * 100) if gross_income else 0

            c1, c2, c3 = st.columns(3)
            c1.metric("Mortgage + Running Costs", f"€{total_obligation:,.2f}")
            c2.metric("Gross Income",             f"€{gross_income:,.2f}")
            c3.metric("DTI Ratio",                f"{dti:.1f}%")

            if dti <= 30:
                st.success(f"✅ {dti:.1f}% — healthy range (≤ 30%)")
            elif dti <= 35:
                st.warning(f"⚠️ {dti:.1f}% — acceptable but high (30–35%)")
            else:
                st.error(f"🚨 {dti:.1f}% — exceeds 35% threshold")

    st.caption("Update property figures in the Calculator tab, then return here.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — DECISION SUPPORT
# ══════════════════════════════════════════════════════════════════════════════
with tab_decision:
    preload = st.session_state.preload
    def vd(key, default): return _v(preload, key, default)

    st.title("📐 Decision Support")
    st.caption("Buy vs. rent analysis and rental yield calculator")
    if preload:
        st.info(f"Figures for: **{preload.get('label','')}**", icon="📂")

    _live_d = st.session_state.get("_live", {})
    pp_d    = float(_live_d.get("purchase_price", vd("purchase_price", 339_000)))
    dp_d    = float(_live_d.get("down_payment",   vd("down_payment",   150_000)))
    loan_d  = float(_live_d.get("loan_amount",    max(0.0, pp_d - dp_d)))
    r_d     = compute({
        "purchase_price": pp_d, "down_payment": dp_d,
        "monthly_costs":  _live_d.get("monthly_costs", vd("monthly_costs", [])),
        "rates":          _live_d.get("rates",          vd("rates", {})),
        "vats":           _live_d.get("vats",           vd("vats",  {})),
        "is_new_build":   _live_d.get("is_new_build",   vd("is_new_build", False)),
    })
    cn_d = r_d["cash_needed"]; mt_d = r_d["monthly_total"]
    mort_rate_d  = float(vd("mort_rate", 3.5))
    mort_years_d = int(vd("mort_years", 25))
    mort_m_d     = monthly_repayment(loan_d, mort_rate_d, mort_years_d)

    c1, c2 = st.columns(2)
    c1.metric("Purchase Price", f"€{pp_d:,.0f}")
    c2.metric("Cash Needed",    f"€{cn_d:,.0f}")
    st.divider()

    ds_tab1, ds_tab2 = st.tabs(["🏢 Buy vs. Rent", "💰 Rental Yield"])

    with ds_tab1:
        left, right = st.columns([1,1], gap="large")
        with left:
            with st.container(border=True):
                st.markdown("#### ⚙️ Assumptions")
                monthly_rent        = st.number_input("Equivalent Monthly Rent (€)", value=vd("monthly_rent",1_500), step=50)
                annual_appreciation = st.number_input("Annual Property Appreciation (%)", value=vd("annual_appreciation",2.0), step=0.5, format="%.1f")

                if mort_m_d > 0 and monthly_rent > 0:
                    break_even_year = None
                    for yr in range(1, 51):
                        cum_rent = monthly_rent * 12 * yr
                        cum_own  = cn_d + (mort_m_d + mt_d) * 12 * yr
                        n_months = yr * 12
                        if mort_rate_d > 0:
                            rm2 = mort_rate_d / 100 / 12
                            equity = loan_d * (((1+rm2)**n_months-1)/((1+rm2)**(mort_years_d*12)-1))
                        else:
                            equity = mort_m_d * n_months
                        appre   = pp_d * ((1+annual_appreciation/100)**yr) - pp_d
                        net_own = cum_own - equity - appre
                        if net_own <= cum_rent and break_even_year is None:
                            break_even_year = yr

                    if break_even_year:
                        st.metric("Estimated Break-even", f"Year {break_even_year}",
                                  delta=f"Buying cheaper after {break_even_year} years")
                    else:
                        st.info("Break-even beyond 50 years.")
                else:
                    st.info("Set mortgage details in the Mortgage tab.")

        with right:
            with st.container(border=True):
                st.markdown("#### 📅 15-Year Comparison")
                if mort_m_d > 0 and monthly_rent > 0:
                    rows_bvr = []
                    for yr in range(1, 16):
                        cum_rent = monthly_rent * 12 * yr
                        cum_own  = cn_d + (mort_m_d + mt_d) * 12 * yr
                        n_months = yr * 12
                        if mort_rate_d > 0:
                            rm2 = mort_rate_d / 100 / 12
                            equity = loan_d * (((1+rm2)**n_months-1)/((1+rm2)**(mort_years_d*12)-1))
                        else:
                            equity = mort_m_d * n_months
                        appre   = pp_d * ((1+annual_appreciation/100)**yr) - pp_d
                        net_own = cum_own - equity - appre
                        rows_bvr.append({
                            "Year": yr,
                            "Cumulative Rent": f"€{cum_rent:,.0f}",
                            "Net Cost of Owning": f"€{net_own:,.0f}",
                            "Better": "🏠 Buy" if net_own < cum_rent else "🏢 Rent",
                        })
                    st.dataframe(pd.DataFrame(rows_bvr), hide_index=True, use_container_width=True)

    with ds_tab2:
        left, right = st.columns([1,1], gap="large")
        with left:
            with st.container(border=True):
                st.markdown("#### ⚙️ Assumptions")
                expected_rent = st.number_input("Expected Monthly Rent (€)", value=vd("expected_rent",1_200), step=50)
                mgmt_cost_pct = st.number_input("Mgmt & Vacancy Cost (%)",   value=vd("mgmt_cost_pct",10.0), step=0.5, format="%.1f")

        with right:
            with st.container(border=True):
                st.markdown("#### 📊 Yield Metrics")
                annual_gross = expected_rent * 12
                annual_net   = annual_gross * (1 - mgmt_cost_pct/100)
                gross_yield  = (annual_gross / pp_d * 100) if pp_d else 0
                net_yield    = (annual_net   / pp_d * 100) if pp_d else 0

                c1, c2 = st.columns(2)
                c1.metric("Gross Annual Rent", f"€{annual_gross:,.0f}")
                c2.metric("Net Annual Rent",   f"€{annual_net:,.0f}")
                c1.metric("Gross Yield", f"{gross_yield:.2f}%",
                          delta="Good (> 4%)" if gross_yield >= 4 else "Below 4%",
                          delta_color="normal" if gross_yield >= 4 else "inverse")
                c2.metric("Net Yield", f"{net_yield:.2f}%",
                          delta="Good (> 3%)" if net_yield >= 3 else "Below 3%",
                          delta_color="normal" if net_yield >= 3 else "inverse")

                if expected_rent > 0 and mort_m_d > 0:
                    cashflow = expected_rent - mort_m_d - mt_d
                    st.metric("Monthly Cashflow",  f"€{cashflow:,.2f}",
                              delta="Positive" if cashflow >= 0 else "Negative",
                              delta_color="normal" if cashflow >= 0 else "inverse")

    st.caption("Update property and mortgage figures in their respective tabs, then return here.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SAVED ANALYSES
# ══════════════════════════════════════════════════════════════════════════════
with tab_saved:
    st.title("📊 Saved Analyses")
    st.caption("Review, compare and edit your saved property analyses")
    st.divider()

    analyses = load_analyses()
    if not analyses:
        st.info("No analyses saved yet. Use the Calculator tab to add your first property.", icon="🏠")
        st.stop()

    sorted_analyses = sorted(analyses, key=lambda a: (-a.get("rating",0), a.get("label","")))

    # ── Compact overview table ─────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### 🗂 All Properties")
        overview_rows = []
        for a in sorted_analyses:
            ra = compute(a)
            stars = "★"*a.get("rating",0) + "☆"*(5-a.get("rating",0)) if a.get("rating") else "—"
            overview_rows.append({
                "Label":        a.get("label","—"),
                "Rating":       stars,
                "Purchase":     f"€{a.get('purchase_price',0):,.0f}",
                "Cash Needed":  f"€{ra['cash_needed']:,.0f}",
                "€/m²":         f"€{a['purchase_price']/a['sqm']:,.0f}" if a.get("sqm") else "—",
                "Monthly":      f"€{ra['monthly_total']:,.2f}",
                "Saved":        a.get("saved_at","—"),
            })
        st.dataframe(pd.DataFrame(overview_rows), hide_index=True, use_container_width=True)

    st.divider()

    # ── Detail view ────────────────────────────────────────────────────────────
    def fmt_label(a):
        r = a.get("rating",0)
        return (("★"*r+"☆"*(5-r)+"  ") if r else "") + a.get("label","Unnamed")

    label_map    = {fmt_label(a): a for a in sorted_analyses}
    sel_display  = st.selectbox("Select a property for details", ["— select —"] + list(label_map.keys()))

    if sel_display != "— select —":
        selected  = label_map[sel_display]
        r         = compute(selected)
        url       = selected.get("url","")
        sel_label = selected.get("label","Unnamed")
        rating    = selected.get("rating",0)
        stars     = "★"*rating+"☆"*(5-rating) if rating else ""

        if url:
            st.markdown(f"### 🏠 [{sel_label}]({url})  {stars}")
        else:
            st.markdown(f"### 🏠 {sel_label}  {stars}")

        meta = st.columns(4)
        meta[0].caption(f"Saved: {selected.get('saved_at','—')}")
        if selected.get("sqm"):
            meta[1].caption(f"Size: {selected['sqm']} m²")
            meta[2].caption(f"€/m²: {selected['purchase_price']/selected['sqm']:,.0f}")
        if selected.get("is_new_build"):
            meta[3].caption("🏗️ New Build")
        if selected.get("notes"):
            st.info(selected["notes"], icon="📝")

        left, right = st.columns([1,1], gap="large")
        with left:
            with st.container(border=True):
                st.markdown("#### 💶 Financials")
                c1, c2 = st.columns(2)
                c1.metric("Purchase Price", f"€{selected['purchase_price']:,.0f}")
                c2.metric("Down Payment",   f"€{selected['down_payment']:,.0f}")
                c1.metric("Loan Amount",    f"€{r['loan_amount']:,.0f}")
                c2.metric("Monthly Costs",  f"€{r['monthly_total']:,.2f}")
                c1.metric("Additional Costs",  f"€{r['total_costs']:,.2f}",
                          delta=f"{r['cost_pct']:.1f}% of price", delta_color="inverse")
                c2.metric("Cash Needed",       f"€{r['cash_needed']:,.2f}")

                mort_rate_s  = selected.get("mort_rate",0)
                mort_years_s = selected.get("mort_years",0)
                if mort_rate_s and mort_years_s:
                    mort_ms  = monthly_repayment(r["loan_amount"], mort_rate_s, mort_years_s)
                    mort_int = mort_ms * mort_years_s * 12 - r["loan_amount"]
                    st.caption(f"🏦 €{mort_ms:,.2f}/mo at {mort_rate_s}% over {mort_years_s}y — interest €{mort_int:,.2f}")

        with right:
            with st.container(border=True):
                st.markdown("#### ⚖️ Cost Breakdown")
                item_data = []
                for item, applies in COST_ITEMS:
                    slug = item.lower().replace(" ","_")
                    item_data.append({
                        "Item":     item,
                        "Basis":    "Purchase" if applies=="purchase" else "Loan",
                        "Rate (%)": f"{selected['rates'].get(slug,0):.2f}%",
                        "VAT (%)":  f"{selected['vats'].get(slug,0):.2f}%",
                        "Cost":     f"€{r['item_costs'].get(item,0):,.2f}",
                    })
                if selected.get("is_new_build") and "VAT (New Build)" in r["item_costs"]:
                    item_data.append({
                        "Item": "VAT (New Build)", "Basis": "Purchase",
                        "Rate (%)": f"{selected['rates'].get('new_build_vat',0):.2f}%",
                        "VAT (%)": "—",
                        "Cost": f"€{r['item_costs']['VAT (New Build)']:,.2f}",
                    })
                st.dataframe(pd.DataFrame(item_data), hide_index=True, use_container_width=True)

        st.divider()

        # Actions
        mort_data = None
        if mort_rate_s and mort_years_s:
            mort_ms   = monthly_repayment(r["loan_amount"], mort_rate_s, mort_years_s)
            mort_data = {"rate": mort_rate_s, "years": mort_years_s, "monthly": mort_ms,
                         "total_interest": mort_ms*mort_years_s*12-r["loan_amount"],
                         "total_repaid":   mort_ms*mort_years_s*12}
        pdf_buf = generate_pdf(selected, r, mort_data)
        fname   = f"{sel_label.replace(' ','_')}_summary.pdf"

        ac1, ac2, ac3 = st.columns(3)
        ac1.download_button("📄 Export PDF", data=pdf_buf, file_name=fname,
                            mime="application/pdf", use_container_width=True)
        if ac2.button("✏️ Load & Edit", use_container_width=True, type="primary"):
            st.session_state.preload = selected
            st.session_state.pop("monthly_costs", None)
            st.rerun()
        if ac3.button("🗑️ Delete", use_container_width=True):
            delete_analysis(selected["id"])
            st.rerun()

        st.divider()

    # ── Comparison ─────────────────────────────────────────────────────────────
    if len(analyses) >= 2:
        with st.container(border=True):
            st.markdown("#### ⚖️ Compare Two Properties")
            all_labels = [a.get("label",f"#{i+1}") for i,a in enumerate(analyses)]
            cc1, cc2 = st.columns(2)
            sel1 = cc1.selectbox("Property A", all_labels, index=0, key="cmp1")
            sel2 = cc2.selectbox("Property B", all_labels, index=min(1,len(all_labels)-1), key="cmp2")

            a1 = next(a for a in analyses if a.get("label")==sel1)
            a2 = next(a for a in analyses if a.get("label")==sel2)
            r1, r2 = compute(a1), compute(a2)
            m1 = monthly_repayment(r1["loan_amount"], a1.get("mort_rate",0), a1.get("mort_years",25))
            m2 = monthly_repayment(r2["loan_amount"], a2.get("mort_rate",0), a2.get("mort_years",25))

            metrics = [
                ("Purchase Price",   a1["purchase_price"],     a2["purchase_price"]),
                ("Down Payment",     a1["down_payment"],        a2["down_payment"]),
                ("Loan Amount",      r1["loan_amount"],          r2["loan_amount"]),
                ("Additional Costs", r1["total_costs"],          r2["total_costs"]),
                ("Final Price",      r1["final_purchase_price"], r2["final_purchase_price"]),
                ("Cash Needed",      r1["cash_needed"],          r2["cash_needed"]),
                ("Monthly Costs",    r1["monthly_total"],        r2["monthly_total"]),
                ("Mortgage/mo",      m1,                         m2),
            ]
            if a1.get("sqm") and a2.get("sqm"):
                metrics.append(("Price/m²", a1["purchase_price"]/a1["sqm"], a2["purchase_price"]/a2["sqm"]))

            hc1, hc2, hc3 = st.columns([2,2,2])
            hc1.write("**Metric**"); hc2.write(f"**{sel1}**"); hc3.write(f"**{sel2}**")
            st.divider()
            for name, val1, val2 in metrics:
                diff = val1 - val2
                mc1, mc2, mc3 = st.columns([2,2,2])
                mc1.write(name)
                mc2.metric("", f"€{val1:,.2f}", delta=f"{'+' if diff>0 else ''}€{diff:,.2f}",
                           delta_color="inverse", label_visibility="collapsed")
                mc3.metric("", f"€{val2:,.2f}", label_visibility="collapsed")