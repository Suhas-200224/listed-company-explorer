"""Listed Company Explorer — v2.

Click-driven drill-down: sectors → companies → detail. Multi-select rows in
the company list to compare. Geography pills at top. Polished card layouts.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from data import load_companies, fetch_company_history, fetch_price_history

st.set_page_config(
    page_title="Listed Company Explorer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Custom CSS ──────────────────────────────────────────────────────────────

st.markdown("""
<style>
    #MainMenu, footer, header {visibility: hidden;}

    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        max-width: 1400px;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 14px 16px;
    }
    [data-testid="stMetricLabel"] {
        font-size: 11px !important;
        color: rgba(255, 255, 255, 0.55) !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    [data-testid="stMetricValue"] {
        font-size: 22px !important;
        font-weight: 600 !important;
    }

    /* Sector cards */
    .sector-card {
        background: linear-gradient(135deg, rgba(55, 138, 221, 0.10), rgba(55, 138, 221, 0.02));
        border: 1px solid rgba(55, 138, 221, 0.20);
        border-radius: 12px;
        padding: 16px 18px;
        margin-bottom: 8px;
        min-height: 110px;
    }
    .sector-name { font-size: 16px; font-weight: 600; margin-bottom: 6px; }
    .sector-meta { font-size: 12px; color: rgba(255, 255, 255, 0.55); margin-bottom: 10px; }
    .sector-mcap { font-size: 22px; font-weight: 600; color: #378ADD; }

    /* Compact dataframe */
    [data-testid="stDataFrame"] {
        border-radius: 12px;
        overflow: hidden;
    }

    /* Typography */
    h1 { font-size: 28px !important; margin-bottom: 0.25rem !important; }
    h2 { font-size: 22px !important; }
    h3 { font-size: 17px !important; margin-top: 1rem !important; }

    /* Geography pills */
    .stRadio > div { flex-direction: row !important; flex-wrap: wrap; gap: 6px; }
    .stRadio > div > label {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 20px;
        padding: 6px 14px !important;
        margin: 0 !important;
        font-size: 13px;
    }
    .stRadio > div > label:has(input:checked) {
        background: rgba(55, 138, 221, 0.18) !important;
        border-color: rgba(55, 138, 221, 0.5) !important;
        color: #fff !important;
    }
</style>
""", unsafe_allow_html=True)


# ─── State management ───────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "view": "sectors",
        "sel_sector": None,
        "sel_company": None,
        "geo_city": "Hyderabad",
        "compare_tickers": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ─── Data load ──────────────────────────────────────────────────────────────

companies, source = load_companies()
if companies.empty:
    st.error("No data available. Trigger the GitHub Actions workflow first.")
    st.stop()


# ─── Geography options ─────────────────────────────────────────────────────

def geo_options(df):
    """Top cities by company count + 'All India' + 'Other'."""
    counts = df[df["city"] != "Unknown"]["city"].value_counts()
    top = counts.head(7).index.tolist()
    preferred_order = ["Hyderabad", "Mumbai", "Bangalore", "Delhi", "Chennai", "Pune", "Ahmedabad"]
    top_ordered = [c for c in preferred_order if c in top] + [c for c in top if c not in preferred_order]
    return ["All India"] + top_ordered[:7]


# ─── Helpers ────────────────────────────────────────────────────────────────

def fmt_cr(v):
    if v is None or pd.isna(v):
        return "—"
    if abs(v) >= 1_00_000:
        return f"₹{v/1_00_000:.2f}L Cr"
    return f"₹{v:,.0f} Cr"

def fmt_num(v, suffix=""):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.1f}{suffix}"


# ─── Header ────────────────────────────────────────────────────────────────

st.title("📊 Listed Company Explorer")

h1, h2 = st.columns([3.5, 1])
with h1:
    geo_choices = geo_options(companies)
    cur = st.session_state.geo_city if st.session_state.geo_city in geo_choices else "All India"
    selected = st.radio(
        "Geography",
        geo_choices,
        index=geo_choices.index(cur),
        horizontal=True,
        label_visibility="collapsed",
        key="geo_radio",
    )
    if selected != st.session_state.geo_city:
        st.session_state.geo_city = selected
        st.session_state.view = "sectors"
        st.session_state.sel_sector = None
        st.session_state.sel_company = None
        st.rerun()

with h2:
    if source == "enriched":
        st.markdown(
            f"<div style='text-align:right; color:rgba(255,255,255,0.55); font-size:12px; padding-top:8px;'>"
            f"<span style='color:#1D9E75;'>● Live data</span> · {len(companies):,} companies indexed</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='text-align:right; color:#EF9F27; font-size:12px; padding-top:8px;'>"
            f"⚠ Seed data only — auto-refresh hasn't run yet</div>",
            unsafe_allow_html=True,
        )


# Scope companies
if st.session_state.geo_city == "All India":
    scoped = companies.copy()
else:
    scoped = companies[companies["city"] == st.session_state.geo_city].copy()


# ─── Breadcrumb + back ─────────────────────────────────────────────────────

view = st.session_state.view

bc1, bc2 = st.columns([0.10, 0.90])
with bc1:
    if view != "sectors":
        if st.button("← Back", use_container_width=True):
            if view == "company":
                st.session_state.view = "companies" if st.session_state.sel_sector else "sectors"
            elif view == "companies":
                st.session_state.view = "sectors"
                st.session_state.sel_sector = None
            elif view == "compare":
                st.session_state.view = "companies" if st.session_state.sel_sector else "sectors"
            st.rerun()

with bc2:
    crumbs = [st.session_state.geo_city]
    if st.session_state.sel_sector:
        crumbs.append(st.session_state.sel_sector)
    if view == "company" and st.session_state.sel_company:
        co_row = scoped[scoped["ticker"] == st.session_state.sel_company]
        if not co_row.empty:
            crumbs.append(co_row.iloc[0]["name"])
    if view == "compare":
        crumbs.append(f"Compare ({len(st.session_state.compare_tickers)})")
    st.markdown(
        f"<div style='color:rgba(255,255,255,0.45); font-size:13px; padding-top:8px;'>"
        f"{' › '.join(crumbs)}</div>",
        unsafe_allow_html=True,
    )

st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# VIEW 1: SECTOR OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════

if view == "sectors":
    agg = (
        scoped.groupby("sector", dropna=True)
        .agg(
            companies=("ticker", "count"),
            total_mcap=("market_cap_cr", "sum"),
            total_revenue=("revenue_cr", "sum"),
            total_profit=("profit_cr", "sum"),
            avg_growth=("revenue_growth_yoy", "mean"),
        )
        .reset_index()
        .sort_values("total_mcap", ascending=False)
    )
    agg["share_pct"] = agg["total_mcap"] / agg["total_mcap"].sum() * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Companies", f"{len(scoped):,}")
    c2.metric("Aggregate market cap", fmt_cr(agg["total_mcap"].sum()))
    c3.metric("Aggregate revenue", fmt_cr(agg["total_revenue"].sum()))
    c4.metric("Sectors", len(agg))

    st.markdown("### Click a sector to drill in")

    n_cols = 3
    for i in range(0, len(agg), n_cols):
        cols = st.columns(n_cols)
        for j, (_, row) in enumerate(agg.iloc[i:i + n_cols].iterrows()):
            with cols[j]:
                st.markdown(f"""
                <div class='sector-card'>
                    <div class='sector-name'>{row['sector']}</div>
                    <div class='sector-meta'>{row['companies']} cos · {row['share_pct']:.1f}% share</div>
                    <div class='sector-mcap'>{fmt_cr(row['total_mcap'])}</div>
                </div>
                """, unsafe_allow_html=True)
                if st.button(f"View {row['sector']}  →", key=f"sec_{row['sector']}", use_container_width=True):
                    st.session_state.view = "companies"
                    st.session_state.sel_sector = row["sector"]
                    st.rerun()

    st.markdown("### Sector breakdown — market cap share")
    fig = px.bar(
        agg,
        x="total_mcap", y="sector",
        orientation="h",
        text=agg["share_pct"].apply(lambda x: f"{x:.1f}%"),
        labels={"total_mcap": "Market cap (₹ Cr)", "sector": ""},
        height=max(280, 36 * len(agg)),
    )
    fig.update_traces(marker_color="#378ADD", textposition="outside")
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        margin=dict(l=10, r=80, t=10, b=10),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="rgba(255,255,255,0.8)"),
    )
    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# VIEW 2: COMPANIES IN SECTOR
# ═══════════════════════════════════════════════════════════════════════════

elif view == "companies":
    sec = st.session_state.sel_sector
    df = scoped[scoped["sector"] == sec].copy() if sec else scoped.copy()

    st.markdown(f"### {sec or 'All sectors'} · {len(df)} companies")

    sort_by = st.radio(
        "Sort by",
        ["Market cap", "Revenue", "PAT", "RoE", "Revenue growth", "P/E"],
        horizontal=True,
        label_visibility="collapsed",
    )
    sort_map = {"Market cap": "market_cap_cr", "Revenue": "revenue_cr", "PAT": "profit_cr",
                "RoE": "roe_pct", "Revenue growth": "revenue_growth_yoy", "P/E": "pe"}
    df = df.sort_values(sort_map[sort_by], ascending=(sort_by == "P/E"), na_position="last").reset_index(drop=True)

    display = df[["ticker", "name", "city", "market_cap_cr", "revenue_cr",
                  "profit_cr", "roe_pct", "pe", "revenue_growth_yoy", "debt_to_equity"]].copy()
    display["market_cap_cr"] = display["market_cap_cr"].apply(fmt_cr)
    display["revenue_cr"] = display["revenue_cr"].apply(fmt_cr)
    display["profit_cr"] = display["profit_cr"].apply(fmt_cr)
    display["roe_pct"] = display["roe_pct"].apply(lambda x: fmt_num(x, "%"))
    display["pe"] = display["pe"].apply(fmt_num)
    display["revenue_growth_yoy"] = display["revenue_growth_yoy"].apply(lambda x: fmt_num(x, "%"))
    display["debt_to_equity"] = display["debt_to_equity"].apply(fmt_num)
    display.columns = ["Ticker", "Name", "City", "M.Cap", "Revenue", "PAT", "RoE", "P/E", "Growth", "D/E"]

    event = st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        height=520,
        on_select="rerun",
        selection_mode="multi-row",
    )

    sel = event.selection.rows if event and hasattr(event, "selection") else []

    a1, a2, a3 = st.columns([1, 1, 4])
    with a1:
        if len(sel) == 1:
            if st.button("📊 View detail", use_container_width=True, type="primary"):
                st.session_state.view = "company"
                st.session_state.sel_company = df.iloc[sel[0]]["ticker"]
                st.rerun()
    with a2:
        if len(sel) >= 2:
            if st.button(f"⚖️ Compare {len(sel)}", use_container_width=True, type="primary"):
                st.session_state.compare_tickers = df.iloc[sel]["ticker"].tolist()
                st.session_state.view = "compare"
                st.rerun()
    with a3:
        if not sel:
            st.caption("Click a row to select. 1 row → detail. 2+ rows → compare.")
        elif len(sel) == 1:
            st.caption(f"Selected: {df.iloc[sel[0]]['name']}")
        else:
            st.caption(f"{len(sel)} companies selected")


# ═══════════════════════════════════════════════════════════════════════════
# VIEW 3: COMPANY DETAIL
# ═══════════════════════════════════════════════════════════════════════════

elif view == "company":
    tk = st.session_state.sel_company
    row_df = companies[companies["ticker"] == tk]
    if row_df.empty:
        st.error(f"Company {tk} not found.")
        st.stop()
    row = row_df.iloc[0]

    st.markdown(f"## {row['name']}")
    st.caption(
        f"NSE: **{row['ticker']}** · {row['sector']} · {row.get('industry') or '—'} · "
        f"{row.get('city') or '—'}, {row.get('state') or '—'}"
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Market cap", fmt_cr(row["market_cap_cr"]))
    c2.metric("Revenue", fmt_cr(row.get("revenue_cr")))
    c3.metric("PAT", fmt_cr(row.get("profit_cr")))
    c4.metric("P/E", fmt_num(row.get("pe")))
    c5.metric("RoE", fmt_num(row.get("roe_pct"), "%"))

    c6, c7, c8, c9, c10 = st.columns(5)
    c6.metric("EPS", fmt_num(row.get("eps")))
    c7.metric("D/E", fmt_num(row.get("debt_to_equity")))
    c8.metric("Div yield", fmt_num(row.get("dividend_yield_pct"), "%"))
    c9.metric("Rev growth YoY", fmt_num(row.get("revenue_growth_yoy"), "%"))
    c10.metric("Latest FY end", row.get("latest_fy_end") or "—")

    st.markdown("### Revenue & PAT history")
    hist = fetch_company_history(tk)
    if hist.empty:
        st.warning("Annual financial history not available from Yahoo for this ticker.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=hist.index, y=hist["revenue_cr"], name="Revenue", marker_color="#378ADD"))
        fig.add_trace(go.Bar(x=hist.index, y=hist["profit_cr"], name="PAT", marker_color="#1D9E75"))
        fig.update_layout(
            barmode="group", xaxis_title="Period end", yaxis_title="₹ Cr",
            height=380, margin=dict(l=10, r=10, t=10, b=10),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="rgba(255,255,255,0.8)"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Price history (5 years)")
    pxh = fetch_price_history(tk, "5y")
    if pxh.empty:
        st.info("Price history not available.")
    else:
        fig = px.line(pxh, y="Close")
        fig.update_traces(line_color="#534AB7", line_width=2)
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="", yaxis_title="Close (₹)", showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="rgba(255,255,255,0.8)"),
        )
        st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# VIEW 4: COMPARE
# ═══════════════════════════════════════════════════════════════════════════

elif view == "compare":
    tickers = st.session_state.get("compare_tickers", [])
    if len(tickers) < 2:
        st.error("Select 2+ companies from the company list to compare.")
        st.stop()

    df = companies[companies["ticker"].isin(tickers)].set_index("ticker").loc[tickers]

    st.markdown(f"### Comparing {len(tickers)} companies")

    metric_rows = [
        ("Market cap (₹ Cr)", "market_cap_cr", "max"),
        ("Revenue (₹ Cr)", "revenue_cr", "max"),
        ("PAT (₹ Cr)", "profit_cr", "max"),
        ("RoE %", "roe_pct", "max"),
        ("P/E", "pe", "min"),
        ("D/E", "debt_to_equity", "min"),
        ("Revenue growth %", "revenue_growth_yoy", "max"),
        ("Dividend yield %", "dividend_yield_pct", "max"),
    ]
    rows = {label: {tk: df.loc[tk, col] for tk in tickers} for label, col, _ in metric_rows}
    compare_df = pd.DataFrame(rows).T

    def style_row(row, mode):
        vals = pd.to_numeric(row, errors="coerce")
        if vals.dropna().empty:
            return [""] * len(row)
        best = vals.min() if mode == "min" else vals.max()
        return ["font-weight: 600; color: #1D9E75" if v == best else "" for v in vals]

    styled = compare_df.style
    for label, _, mode in metric_rows:
        styled = styled.apply(
            lambda r, m=mode: style_row(r, m), axis=1, subset=pd.IndexSlice[label, :]
        )
    styled = styled.format(lambda v: f"{v:,.2f}" if isinstance(v, (int, float)) and pd.notna(v) else "—")
    st.dataframe(styled, use_container_width=True)
    st.caption("Green = best in row. Lower is better for P/E, D/E.")

    st.markdown("### Revenue history overlay")
    colors = ["#378ADD", "#1D9E75", "#D85A30", "#7F77DD", "#EF9F27", "#D4537E"]
    fig = go.Figure()
    for i, tk in enumerate(tickers):
        hist = fetch_company_history(tk)
        if not hist.empty:
            fig.add_trace(go.Scatter(
                x=hist.index, y=hist["revenue_cr"],
                name=tk, mode="lines+markers",
                line=dict(color=colors[i % len(colors)], width=2),
            ))
    fig.update_layout(
        xaxis_title="Period end", yaxis_title="Revenue (₹ Cr)",
        height=400, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="rgba(255,255,255,0.8)"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─── Footer with FY attribution ────────────────────────────────────────────

st.divider()

fy_min = fy_max = None
if "latest_fy_end" in companies.columns:
    fy_dates = pd.to_datetime(companies["latest_fy_end"], errors="coerce").dropna()
    if not fy_dates.empty:
        fy_min = fy_dates.min().strftime("%b %Y")
        fy_max = fy_dates.max().strftime("%b %Y")

fy_text = f"FY ends range **{fy_min} → {fy_max}**" if fy_min else "latest annual filings"

st.markdown(
    f"<div style='font-size:11px; color:rgba(255,255,255,0.45); line-height:1.6;'>"
    f"<b>Data source:</b> NSE official equity list + Yahoo Finance · "
    f"<b>Coverage:</b> {len(companies):,} NSE-listed equities with valid market cap and financials "
    f"(out of ~2,100 total — smaller stocks with broken Yahoo data are excluded) · "
    f"<b>Refresh:</b> automated daily at 07:00 IST via GitHub Actions · "
    f"<b>Financials:</b> reflect each company's most recent annual report ({fy_text}). "
    f"Indian FY ends Mar 31, but some cos report calendar year. "
    f"<b>Disclaimer:</b> always cross-verify with official filings before taking decisions. "
    f"Yahoo Finance city/sector data has known gaps for Indian smallcaps."
    f"</div>",
    unsafe_allow_html=True,
)
