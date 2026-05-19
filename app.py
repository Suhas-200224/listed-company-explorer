"""Listed Company Explorer — v4.

Layout:
- Top bar: city dropdown (ALL cities) + search box
- Home: KPIs + sector bar chart (clickable) + sector buttons as fallback
- Sector view: top-companies chart (clickable) + full sortable table
- Company view: detailed financials with charts
- Search view: real-time filtered results across all companies
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

st.markdown("""
<style>
    #MainMenu, footer, header {visibility: hidden;}
    .block-container { padding-top: 1.2rem !important; padding-bottom: 2rem !important; max-width: 1400px; }

    [data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 12px 16px;
    }
    [data-testid="stMetricLabel"] {
        font-size: 11px !important;
        color: rgba(255, 255, 255, 0.55) !important;
        text-transform: uppercase; letter-spacing: 0.5px;
    }
    [data-testid="stMetricValue"] { font-size: 22px !important; font-weight: 600 !important; }

    [data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }

    h1 { font-size: 26px !important; margin-bottom: 0.25rem !important; }
    h2 { font-size: 20px !important; }
    h3 { font-size: 16px !important; margin-top: 0.5rem !important; }
</style>
""", unsafe_allow_html=True)


# ─── State init ─────────────────────────────────────────────────────────────

for key, default in {
    "view": "home",
    "sel_sector": None,
    "sel_company": None,
    "geo_city": "All India",
    "search_q": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ─── Load data ─────────────────────────────────────────────────────────────

companies, source = load_companies()
if companies.empty:
    st.error("No data loaded. Trigger the GitHub Actions workflow.")
    st.stop()


# ─── Helpers ───────────────────────────────────────────────────────────────

def fmt_cr(v):
    if v is None or pd.isna(v): return "—"
    if abs(v) >= 1_00_000: return f"₹{v/1_00_000:.2f}L Cr"
    return f"₹{v:,.0f} Cr"

def fmt_num(v, suffix=""):
    if v is None or pd.isna(v): return "—"
    return f"{v:,.1f}{suffix}"


# ─── HEADER: title + city dropdown + search ────────────────────────────────

st.markdown("# 📊 Listed Company Explorer")

t1, t2, t3 = st.columns([1.2, 2.5, 1])

with t1:
    # Build city list: sorted by company count, with counts shown
    city_counts = (
        companies[companies["city"].notna() & (companies["city"] != "Unknown")]
        ["city"].value_counts()
    )
    city_options = ["All India"] + [f"{c} ({n})" for c, n in city_counts.items()]
    city_lookup = {f"{c} ({n})": c for c, n in city_counts.items()}
    city_lookup["All India"] = "All India"

    # Determine current display value
    cur_display = "All India"
    if st.session_state.geo_city != "All India":
        for disp, raw in city_lookup.items():
            if raw == st.session_state.geo_city:
                cur_display = disp
                break

    sel_display = st.selectbox(
        "City",
        city_options,
        index=city_options.index(cur_display) if cur_display in city_options else 0,
        label_visibility="collapsed",
    )
    sel_city = city_lookup.get(sel_display, "All India")
    if sel_city != st.session_state.geo_city:
        st.session_state.geo_city = sel_city
        st.session_state.view = "home"
        st.session_state.sel_sector = None
        st.session_state.sel_company = None
        st.rerun()

with t2:
    search = st.text_input(
        "Search",
        value=st.session_state.search_q,
        placeholder="🔍 Search company, sector, or industry (e.g. 'reddy', 'pharma', 'cement')",
        label_visibility="collapsed",
    )
    if search != st.session_state.search_q:
        st.session_state.search_q = search
        if search.strip():
            st.session_state.view = "search"
        elif st.session_state.view == "search":
            st.session_state.view = "home"
        st.rerun()

with t3:
    st.markdown(
        f"<div style='text-align:right; padding-top:6px; color:rgba(255,255,255,0.5); font-size:12px;'>"
        f"<span style='color:#1D9E75;'>● Live</span> · {len(companies):,} cos indexed</div>",
        unsafe_allow_html=True,
    )


# ─── Apply city scope ──────────────────────────────────────────────────────

if st.session_state.geo_city == "All India":
    scoped = companies.copy()
else:
    scoped = companies[companies["city"] == st.session_state.geo_city].copy()


# ─── Breadcrumb + back button ──────────────────────────────────────────────

view = st.session_state.view
bc1, bc2 = st.columns([0.10, 0.90])
with bc1:
    if view in ("sector", "company", "search"):
        if st.button("← Back", use_container_width=True):
            if view == "company":
                st.session_state.view = "sector" if st.session_state.sel_sector else "home"
            elif view == "sector":
                st.session_state.view = "home"
                st.session_state.sel_sector = None
            elif view == "search":
                st.session_state.view = "home"
                st.session_state.search_q = ""
            st.rerun()
with bc2:
    crumbs = [st.session_state.geo_city]
    if st.session_state.sel_sector and view != "search":
        crumbs.append(st.session_state.sel_sector)
    if view == "company" and st.session_state.sel_company:
        co = companies[companies["ticker"] == st.session_state.sel_company]
        if not co.empty:
            crumbs.append(co.iloc[0]["name"])
    if view == "search":
        crumbs.append(f"Search: '{st.session_state.search_q}'")
    st.markdown(
        f"<div style='color:rgba(255,255,255,0.5); font-size:13px; padding-top:8px;'>"
        f"{' › '.join(crumbs)}</div>",
        unsafe_allow_html=True,
    )

st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# VIEW: SEARCH
# ═══════════════════════════════════════════════════════════════════════════

if view == "search":
    q = st.session_state.search_q.strip().lower()
    matches = companies[
        companies["name"].fillna("").str.lower().str.contains(q, na=False) |
        companies["ticker"].fillna("").str.lower().str.contains(q, na=False) |
        companies["sector"].fillna("").str.lower().str.contains(q, na=False) |
        companies["industry"].fillna("").str.lower().str.contains(q, na=False)
    ].sort_values("market_cap_cr", ascending=False, na_position="last")

    st.markdown(f"### {len(matches)} matches for '{st.session_state.search_q}'")

    if matches.empty:
        st.info("No matches. Try a shorter or different keyword.")
    else:
        display = matches[["ticker", "name", "sector", "city",
                           "market_cap_cr", "revenue_cr", "profit_cr", "pe", "roe_pct"]].copy()
        display["market_cap_cr"] = display["market_cap_cr"].apply(fmt_cr)
        display["revenue_cr"] = display["revenue_cr"].apply(fmt_cr)
        display["profit_cr"] = display["profit_cr"].apply(fmt_cr)
        display["pe"] = display["pe"].apply(fmt_num)
        display["roe_pct"] = display["roe_pct"].apply(lambda x: fmt_num(x, "%"))
        display.columns = ["Ticker", "Name", "Sector", "City", "M.Cap", "Revenue", "PAT", "P/E", "RoE"]

        event = st.dataframe(
            display, hide_index=True, use_container_width=True, height=520,
            on_select="rerun", selection_mode="single-row",
        )
        if event.selection.rows:
            sel = matches.iloc[event.selection.rows[0]]
            if st.button(f"📊 View {sel['name']} details →", type="primary"):
                st.session_state.view = "company"
                st.session_state.sel_company = sel["ticker"]
                st.rerun()
        else:
            st.caption("Click a row to select a company, then click 'View details'.")


# ═══════════════════════════════════════════════════════════════════════════
# VIEW: HOME (sector chart)
# ═══════════════════════════════════════════════════════════════════════════

elif view == "home":
    agg = (
        scoped.groupby("sector", dropna=True)
        .agg(
            companies=("ticker", "count"),
            total_mcap=("market_cap_cr", "sum"),
            total_revenue=("revenue_cr", "sum"),
            total_profit=("profit_cr", "sum"),
        )
        .reset_index()
        .sort_values("total_mcap", ascending=False)
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Companies", f"{len(scoped):,}")
    c2.metric("Market cap", fmt_cr(agg["total_mcap"].sum()))
    c3.metric("Revenue", fmt_cr(agg["total_revenue"].sum()))
    c4.metric("Sectors", len(agg))

    if agg.empty:
        st.warning(f"No companies in {st.session_state.geo_city}. Pick a different city.")
        st.stop()

    st.markdown("### Sectors by market cap — click a bar OR a button below to drill in")

    # Clickable sector chart
    fig = px.bar(
        agg, x="total_mcap", y="sector", orientation="h",
        text=agg["total_mcap"].apply(fmt_cr),
        custom_data=["sector", "companies"],
        labels={"total_mcap": "Market cap (₹ Cr)", "sector": ""},
        height=max(350, 38 * len(agg)),
    )
    fig.update_traces(
        marker_color="#378ADD", textposition="outside",
        hovertemplate="<b>%{customdata[0]}</b><br>Market cap: ₹%{x:,.0f} Cr<br>%{customdata[1]} companies<extra></extra>",
    )
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        margin=dict(l=10, r=80, t=10, b=10),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="rgba(255,255,255,0.8)"),
    )

    event = st.plotly_chart(
        fig, use_container_width=True,
        on_select="rerun", selection_mode="points",
        key="sector_chart",
    )

    if event and hasattr(event, "selection") and event.selection.get("points"):
        try:
            clicked_sector = event.selection["points"][0].get("y") or \
                             event.selection["points"][0].get("customdata", [None])[0]
            if clicked_sector and clicked_sector in agg["sector"].values:
                st.session_state.view = "sector"
                st.session_state.sel_sector = clicked_sector
                st.rerun()
        except Exception:
            pass

    # Button fallback: every sector as a clickable button
    st.markdown("**Or pick a sector:**")
    cols_per_row = 4
    for i in range(0, len(agg), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, (_, row) in enumerate(agg.iloc[i:i+cols_per_row].iterrows()):
            with cols[j]:
                label = f"{row['sector']} ({row['companies']})"
                if st.button(label, key=f"sec_btn_{row['sector']}", use_container_width=True):
                    st.session_state.view = "sector"
                    st.session_state.sel_sector = row["sector"]
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# VIEW: SECTOR (chart + table)
# ═══════════════════════════════════════════════════════════════════════════

elif view == "sector":
    sec = st.session_state.sel_sector
    df = scoped[scoped["sector"] == sec].copy().sort_values("market_cap_cr", ascending=False, na_position="last")

    st.markdown(f"### {sec} — {len(df)} companies")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Companies", len(df))
    c2.metric("Market cap", fmt_cr(df["market_cap_cr"].sum()))
    c3.metric("Revenue", fmt_cr(df["revenue_cr"].sum()))
    c4.metric("PAT", fmt_cr(df["profit_cr"].sum()))

    # Top companies chart (clickable)
    st.markdown("#### Top companies by market cap — click a bar to view detail")
    top_n = df.head(20).copy()
    if not top_n.empty:
        fig = px.bar(
            top_n, x="market_cap_cr", y="name", orientation="h",
            text=top_n["market_cap_cr"].apply(fmt_cr),
            custom_data=["ticker", "name"],
            labels={"market_cap_cr": "Market cap (₹ Cr)", "name": ""},
            height=max(350, 28 * len(top_n)),
        )
        fig.update_traces(
            marker_color="#1D9E75", textposition="outside",
            hovertemplate="<b>%{customdata[1]}</b><br>Market cap: ₹%{x:,.0f} Cr<extra></extra>",
        )
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            margin=dict(l=10, r=80, t=10, b=10),
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="rgba(255,255,255,0.8)"),
        )
        event = st.plotly_chart(
            fig, use_container_width=True,
            on_select="rerun", selection_mode="points",
            key=f"co_chart_{sec}",
        )
        if event and hasattr(event, "selection") and event.selection.get("points"):
            try:
                cd = event.selection["points"][0].get("customdata")
                if cd:
                    st.session_state.view = "company"
                    st.session_state.sel_company = cd[0]
                    st.rerun()
            except Exception:
                pass

    # Full table
    st.markdown("#### All companies in sector — click a row to view detail")
    display = df[["ticker", "name", "city", "market_cap_cr", "revenue_cr",
                  "profit_cr", "roe_pct", "pe", "revenue_growth_yoy"]].copy()
    display["market_cap_cr"] = display["market_cap_cr"].apply(fmt_cr)
    display["revenue_cr"] = display["revenue_cr"].apply(fmt_cr)
    display["profit_cr"] = display["profit_cr"].apply(fmt_cr)
    display["roe_pct"] = display["roe_pct"].apply(lambda x: fmt_num(x, "%"))
    display["pe"] = display["pe"].apply(fmt_num)
    display["revenue_growth_yoy"] = display["revenue_growth_yoy"].apply(lambda x: fmt_num(x, "%"))
    display.columns = ["Ticker", "Name", "City", "M.Cap", "Revenue", "PAT", "RoE", "P/E", "Growth"]

    event = st.dataframe(
        display, hide_index=True, use_container_width=True, height=420,
        on_select="rerun", selection_mode="single-row",
    )
    if event.selection.rows:
        sel = df.iloc[event.selection.rows[0]]
        if st.button(f"📊 View {sel['name']} details →", type="primary"):
            st.session_state.view = "company"
            st.session_state.sel_company = sel["ticker"]
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# VIEW: COMPANY DETAIL
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
    c9.metric("Rev growth", fmt_num(row.get("revenue_growth_yoy"), "%"))
    c10.metric("Latest FY end", row.get("latest_fy_end") or "—")

    st.markdown("### Revenue & PAT history")
    hist = fetch_company_history(tk)
    if hist.empty:
        st.info("Annual financial history not available for this ticker.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=hist.index, y=hist["revenue_cr"], name="Revenue", marker_color="#378ADD"))
        fig.add_trace(go.Bar(x=hist.index, y=hist["profit_cr"], name="PAT", marker_color="#1D9E75"))
        fig.update_layout(
            barmode="group", xaxis_title="Period end", yaxis_title="₹ Cr",
            height=360, margin=dict(l=10, r=10, t=10, b=10),
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
            height=300, margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="", yaxis_title="Close (₹)", showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="rgba(255,255,255,0.8)"),
        )
        st.plotly_chart(fig, use_container_width=True)


# ─── Footer ────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    f"Data: Yahoo Finance · {len(companies):,} NSE-listed companies indexed · "
    f"Auto-refreshed daily via GitHub Actions"
)
