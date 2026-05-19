"""Auto-refresh script.

Pulls the full list of NSE-listed equities from NSE's official archive,
then enriches each with sector/city/financials from Yahoo Finance.
Output: data/companies_enriched.csv

Runs daily via GitHub Actions. No manual maintenance needed — new IPOs and
delistings flow through automatically as NSE updates its list.
"""

import io
import time
import requests
import pandas as pd
import yfinance as yf
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

NSE_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
OUTPUT = Path(__file__).parent.parent / "data" / "companies_enriched.csv"
CR = 1e7  # one crore in rupees

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,application/csv,*/*",
}


def fetch_nse_universe() -> list[str]:
    """Download the official NSE equity list. Returns list of ticker symbols."""
    print(f"[1/2] Fetching NSE master list from {NSE_URL}")
    r = requests.get(NSE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content))
    df.columns = [c.strip() for c in df.columns]
    if "SERIES" in df.columns:
        df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
    symbols = df["SYMBOL"].astype(str).str.strip().tolist()
    print(f"      Found {len(symbols)} NSE-listed equities (EQ series)")
    return symbols


def enrich_ticker(symbol: str) -> dict | None:
    """Pull current fundamentals for one ticker. None on failure or no market cap."""
    try:
        t = yf.Ticker(f"{symbol}.NS")
        info = t.info or {}
        mcap = info.get("marketCap")
        if not mcap or mcap <= 0:
            return None  # delisted / no live data

        # Latest annual revenue & PAT from financials
        revenue = profit = growth = None
        try:
            fin = t.financials
            if isinstance(fin, pd.DataFrame) and not fin.empty:
                cols = sorted(fin.columns, reverse=True)
                if "Total Revenue" in fin.index and len(cols) >= 1:
                    revenue = fin.loc["Total Revenue", cols[0]] / CR
                    if len(cols) >= 2:
                        prev = fin.loc["Total Revenue", cols[1]]
                        if prev and prev != 0:
                            growth = ((fin.loc["Total Revenue", cols[0]] - prev) / abs(prev)) * 100
                if "Net Income" in fin.index and len(cols) >= 1:
                    profit = fin.loc["Net Income", cols[0]] / CR
        except Exception:
            pass

        return {
            "ticker": f"{symbol}.NS",
            "name": info.get("longName") or info.get("shortName") or symbol,
            "sector": info.get("sector") or "Unknown",
            "industry": info.get("industry") or "Unknown",
            "city": info.get("city") or "Unknown",
            "state": info.get("state") or "Unknown",
            "market_cap_cr": mcap / CR,
            "revenue_cr": revenue,
            "profit_cr": profit,
            "revenue_growth_yoy": growth,
            "pe": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "roe_pct": (info.get("returnOnEquity") or 0) * 100 if info.get("returnOnEquity") else None,
            "debt_to_equity": (info.get("debtToEquity") or 0) / 100 if info.get("debtToEquity") else None,
            "dividend_yield_pct": (info.get("dividendYield") or 0) * 100 if info.get("dividendYield") else None,
        }
    except Exception:
        return None


def main():
    symbols = fetch_nse_universe()

    print(f"[2/2] Enriching {len(symbols)} tickers via Yahoo Finance (parallel)")
    rows = []
    completed = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(enrich_ticker, s): s for s in symbols}
        for fut in as_completed(futures):
            completed += 1
            if completed % 100 == 0:
                print(f"      Progress: {completed}/{len(symbols)} done, {len(rows)} with data")
            try:
                result = fut.result(timeout=20)
                if result:
                    rows.append(result)
            except Exception:
                continue

    df = pd.DataFrame(rows).sort_values("market_cap_cr", ascending=False)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT, index=False)
    print(f"      Wrote {len(df)} companies to {OUTPUT}")
    print(f"      Sectors: {df['sector'].nunique()} | Cities: {df['city'].nunique()}")


if __name__ == "__main__":
    main()
