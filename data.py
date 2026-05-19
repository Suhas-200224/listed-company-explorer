"""Data layer.

Reads the auto-refreshed companies_enriched.csv if present (created by the
GitHub Actions workflow). Falls back to a small seed list otherwise so the
app works on first deploy before the first refresh completes.

Live price/financial history for the detail view still comes from yfinance
on demand, cached for 1 hour.
"""

import pandas as pd
import streamlit as st
import yfinance as yf
from pathlib import Path

ROOT = Path(__file__).parent
ENRICHED = ROOT / "data" / "companies_enriched.csv"
SEED = ROOT / "companies_seed.csv"
CR = 1e7


@st.cache_data(ttl=900)  # 15 min — the file is updated daily, no need for shorter
def load_companies() -> tuple[pd.DataFrame, str]:
    """Return (df, source_label). source_label tells the UI which file we used."""
    if ENRICHED.exists():
        df = pd.read_csv(ENRICHED)
        return df, "enriched"
    if SEED.exists():
        df = pd.read_csv(SEED)
        # Seed has fewer columns; pad to keep app code uniform
        for col in ["industry", "state", "market_cap_cr", "revenue_cr", "profit_cr",
                    "revenue_growth_yoy", "pe", "eps", "roe_pct", "debt_to_equity",
                    "dividend_yield_pct"]:
            if col not in df.columns:
                df[col] = None
        return df, "seed"
    return pd.DataFrame(), "empty"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_company_history(ticker: str) -> pd.DataFrame:
    """Multi-year revenue + PAT history for the detail view."""
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
    """Daily close prices for the given period."""
    try:
        t = yf.Ticker(ticker)
        h = t.history(period=period)
        return h[["Close"]] if not h.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()
