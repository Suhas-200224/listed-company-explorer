"""Listed Company Explorer.

Auto-refreshing dashboard for NSE-listed companies. Sector view, geo filter,
company comparison, drill-down.

Data refresh handled by GitHub Actions (scripts/refresh_data.py runs daily).
This app just reads the resulting CSV.
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
    initial_sidebar_state="expanded",
)


# ─── helpers ─────────────────────────────────────────────────────────────────

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


# ─── load data ───────────────────────────────────────────────────────────────

companies, source = load_companies()

if companies.empty:
    st.error("No company data available. The auto-refresh workflow hasn't run yet — "
             "go to the **Actions** tab on GitHub and trigger 'Refresh company data' manually.")
    st.stop()


# ─── sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📊 Filters")

    # Source indicator
    if source == "enriched":
        st.success(f"✓ Live data · {len(companies)} companies")
    else:
        st.warning(f"⚠ Seed data only — {len(companies)} cos. "
                   "Trigger the GitHub Action to load full universe.")

    st.divider()

    # Geography filter
    cities = ["All India"] + sorted(
        c for c in companies["city"].dropna().unique()
        if c and c != "Unknown"
    )
    default_idx = cities.index("Hyderabad") if "Hyderabad" in cities else 0
    selected_city = st.radio("Geography", cities, index=default_idx)

    if selected_city == "All India":
        scoped = companies.copy()
    else:
        scoped = companies[companies["city"] == selected_city].copy()

    st.caption(f"**{len(scoped)}** companies in this scope")

    st.divider()

    view = st.radio(
        "View",
        ["Sector overview", "Company list", "Compare", "Company detail"],
        index=0,
    )

    st.divider()

    if st.button("🔄 Clear app cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("Forces re-read of the data file. Underlying data refreshes daily via GitHub Actions.")


# ─── header ──────────────────────────────────────────────────────────────────

st.title("Listed Company Explorer")
st.caption(
    f"{selected_city} · {len(scoped)} of {len(companies)} NSE-listed companies · "
    f"Source: NSE + Yahoo Finance, auto-refreshed daily"
)


# ═══════════════════════════════════════════════════════════════════════════
# VIEW 1: SECTOR OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════

if view == "Sector overview":
    st.subheader("Sectors ranked by aggregate market cap")

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
    c1.metric("Companies", len(scoped))
    c2.metric("Aggregate market cap", fmt_cr(agg["total_mcap"].sum()))
    c3.metric("Aggregate revenue", fmt_cr(agg["total_revenue"].sum()))
    c4.metric("Sectors", len(agg))

    st.divider()

    fig = px.bar(
        agg.head(15),
        x="total_mcap",
        y="sector",
        orientation="h",
        text=agg.head(15)["share_pct"].apply(lambda x: f"{x:.1f}%"),
        labels={"total_mcap": "Market cap (₹ Cr)", "sector": ""},
        height=max(300, 40 * min(len(agg), 15)),
    )
    fig.update_traces(marker_color="#378ADD", textposition="outside")
    fig.update_layout(yaxis={"categoryorder": "total ascending"},
                      margin=dict(l=10, r=80, t=10, b=10), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    display = agg.copy()
    display["total_mcap"] = display["total_mcap"].apply(fmt_cr)
    display["total_revenue"] = display["total_revenue"].apply(fmt_cr)
    display["total_profit"] = display["total_profit"].apply(fmt_cr)
    display["avg_growth"] = display["avg_growth"].apply(lambda x: fmt_num(x, "%"))
    display["share_pct"] = display["share_pct"].apply(lambda x: f"{x:.1f}%")
    display.columns = ["Sector", "# Cos", "Market cap", "Revenue", "PAT", "Avg growth", "Share"]
    st.dataframe(display, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# VIEW 2: COMPANY LIST
# ═══════════════════════════════════════════════════════════════════════════

elif view == "Company list":
    sectors_available = sorted(s for s in scoped["sector"].dropna().unique() if s)
    sel_sector = st.selectbox("Sector", ["All sectors"] + sectors_available)
    df = scoped if sel_sector == "All sectors" else scoped[scoped["sector"] == sel_sector]

    sort_by = st.radio(
        "Sort by",
        ["Market cap", "Revenue", "PAT", "RoE", "Revenue growth", "P/E"],
        horizontal=True,
    )
    sort_map = {"Market cap": "market_cap_cr", "Revenue": "revenue_cr", "PAT": "profit_cr",
                "RoE": "roe_pct", "Revenue growth": "revenue_growth_yoy", "P/E": "pe"}
    df = df.sort_values(sort_map[sort_by], ascending=(sort_by == "P/E"), na_position="last")

    cols = ["ticker", "name", "sector", "city", "market_cap_cr", "revenue_cr",
            "profit_cr", "roe_pct", "pe", "revenue_growth_yoy", "debt_to_equity"]
    display = df[cols].copy()
    display["market_cap_cr"] = display["market_cap_cr"].apply(fmt_cr)
    display["revenue_cr"] = display["revenue_cr"].apply(fmt_cr)
    display["profit_cr"] = display["profit_cr"].apply(fmt_cr)
    display["roe_pct"] = display["roe_pct"].apply(lambda x: fmt_num(x, "%"))
    display["pe"] = display["pe"].apply(fmt_num)
    display["revenue_growth_yoy"] = display["revenue_growth_yoy"].apply(lambda x: fmt_num(x, "%"))
    display["debt_to_equity"] = display["debt_to_equity"].apply(fmt_num)
    display.columns = ["Ticker", "Name", "Sector", "City", "M.Cap", "Revenue",
                       "PAT", "RoE", "P/E", "Growth", "D/E"]

    st.dataframe(display, hide_index=True, use_container_width=True, height=600)
    st.caption(f"{len(df)} companies · sorted by {sort_by}")


# ═══════════════════════════════════════════════════════════════════════════
# VIEW 3: COMPARE
# ═══════════════════════════════════════════════════════════════════════════

elif view == "Compare":
    st.caption("Pick 2–6 companies to compare side-by-side")
    options = scoped.apply(lambda r: f"{r['name']} ({r['ticker']})", axis=1).tolist()
    label_to_ticker = dict(zip(options, scoped["ticker"]))
    picked = st.multiselect("Companies", options, max_selections=6)

    if len(picked) < 2:
        st.info("Pick at least 2 companies above.")
    else:
        tickers = [label_to_ticker[p] for p in picked]
        df = scoped[scoped["ticker"].isin(tickers)].set_index("ticker").loc[tickers]

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
            return ["font-weight: 600; color: #0F6E56" if v == best else "" for v in vals]

        styled = compare_df.style
        for label, _, mode in metric_rows:
            styled = styled.apply(
                lambda r, m=mode: style_row(r, m), axis=1, subset=pd.IndexSlice[label, :]
            )
        styled = styled.format(lambda v: f"{v:,.2f}" if isinstance(v, (int, float)) and pd.notna(v) else "—")
        st.dataframe(styled, use_container_width=True)
        st.caption("Green = best in row. Lower is better for P/E, D/E.")

        st.subheader("Revenue history")
        fig = go.Figure()
        for tk in tickers:
            hist = fetch_company_history(tk)
            if not hist.empty:
                fig.add_trace(go.Scatter(x=hist.index, y=hist["revenue_cr"],
                                         name=tk, mode="lines+markers"))
        fig.update_layout(xaxis_title="Year", yaxis_title="Revenue (₹ Cr)",
                          height=400, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# VIEW 4: COMPANY DETAIL
# ═══════════════════════════════════════════════════════════════════════════

elif view == "Company detail":
    options = scoped.apply(lambda r: f"{r['name']} ({r['ticker']})", axis=1).tolist()
    label_to_ticker = dict(zip(options, scoped["ticker"]))
    picked = st.selectbox("Company", options)
    tk = label_to_ticker[picked]
    row = scoped[scoped["ticker"] == tk].iloc[0]

    st.header(row["name"])
    st.caption(f"NSE: {row['ticker']} · {row['sector']} · {row.get('industry') or '—'} · "
               f"{row.get('city') or '—'}, {row.get('state') or '—'}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Market cap", fmt_cr(row["market_cap_cr"]))
    c2.metric("Revenue", fmt_cr(row["revenue_cr"]))
    c3.metric("PAT", fmt_cr(row["profit_cr"]))
    c4.metric("P/E", fmt_num(row["pe"]))
    c5.metric("RoE", fmt_num(row["roe_pct"], "%"))

    c6, c7, c8, c9, c10 = st.columns(5)
    c6.metric("EPS", fmt_num(row["eps"]))
    c7.metric("D/E", fmt_num(row["debt_to_equity"]))
    c8.metric("Div yield", fmt_num(row["dividend_yield_pct"], "%"))
    c9.metric("Rev growth YoY", fmt_num(row["revenue_growth_yoy"], "%"))
    c10.metric("Industry", str(row.get("industry") or "—")[:20])

    st.divider()

    st.subheader("Revenue & PAT history")
    hist = fetch_company_history(tk)
    if hist.empty:
        st.warning("Annual financial history not available from Yahoo for this ticker.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=hist.index, y=hist["revenue_cr"], name="Revenue", marker_color="#378ADD"))
        fig.add_trace(go.Bar(x=hist.index, y=hist["profit_cr"], name="PAT", marker_color="#1D9E75"))
        fig.update_layout(barmode="group", xaxis_title="Year", yaxis_title="₹ Cr",
                          height=400, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Price history (5 yr)")
    px_df = fetch_price_history(tk, "5y")
    if px_df.empty:
        st.info("Price history not available.")
    else:
        fig = px.line(px_df, y="Close")
        fig.update_traces(line_color="#534AB7")
        fig.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="", yaxis_title="Close (₹)", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Data via NSE + Yahoo Finance. Always cross-verify with the company's actual annual report."
    )
