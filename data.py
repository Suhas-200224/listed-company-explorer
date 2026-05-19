"""Data layer.

Reads auto-refreshed companies_enriched.csv (built daily by GitHub Actions).
Falls back to a small seed list before first refresh runs.
"""

import pandas as pd
import streamlit as st
import yfinance as yf
from pathlib import Path

ROOT = Path(__file__).parent
ENRICHED = ROOT / "data" / "companies_enriched.csv"
SEED = ROOT / "companies_seed.csv"
CR = 1e7


@st.cache_data(ttl=900)
def load_companies() -> tuple[pd.DataFrame, str]:
    if ENRICHED.exists():
        df = pd.read_csv(ENRICHED)
        return df, "enriched"
    if SEED.exists():
        df = pd.read_csv(SEED)
        for col in ["industry", "state", "market_cap_cr", "revenue_cr", "profit_cr",
                    "revenue_growth_yoy", "pe", "eps", "roe_pct", "debt_to_equity",
                    "dividend_yield_pct", "latest_fy_end"]:
            if col not in df.columns:
                df[col] = None
        return df, "seed"
    return pd.DataFrame(), "empty"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_company_history(ticker: str) -> pd.DataFrame:
    try:
        t = yf.Ticker(ticker)
        fin = t.financials
        if not isinstance(fin, pd.DataFrame) or fin.empty:
            return pd.DataFrame()
        rows = []
        for col in sorted(fin.columns):
            year = col.year if hasattr(col, "year") else str(col)
            rev = fin.loc["Total Revenue", col] / CR if "Total Revenue" in fin.index else None
            pat = fin.loc["Net Income", col] / CR if "Net Income" in fin.index else None
            rows.append({"year": year, "revenue_cr": rev, "profit_cr": pat})
        return pd.DataFrame(rows).set_index("year")
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_price_history(ticker: str, period: str = "5y") -> pd.DataFrame:
    try:
        t = yf.Ticker(ticker)
        h = t.history(period=period)
        return h[["Close"]] if not h.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()
