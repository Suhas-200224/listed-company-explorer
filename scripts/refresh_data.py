"""Auto-refresh script v2.

Changes from v1:
- City normalization. Yahoo Finance's city field is inconsistent for Indian
  companies (Secunderabad, HITEC City, etc.). We collapse Telangana state
  entries to Hyderabad and normalize common synonyms. This significantly
  improves geo-filtering accuracy.
- Captures latest_fy_end so the app can show what financial year the numbers
  reflect (Indian FYs typically end March 31).
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
CR = 1e7

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,application/csv,*/*",
}

# City synonyms → canonical name
CITY_NORMALIZATION = {
    "secunderabad": "Hyderabad",
    "hitec city": "Hyderabad",
    "gachibowli": "Hyderabad",
    "kondapur": "Hyderabad",
    "madhapur": "Hyderabad",
    "sangareddy": "Hyderabad",
    "medchal": "Hyderabad",
    "bengaluru": "Bangalore",
    "bangalore": "Bangalore",
    "bombay": "Mumbai",
    "mumbai": "Mumbai",
    "navi mumbai": "Mumbai",
    "thane": "Mumbai",
    "new delhi": "Delhi",
    "delhi": "Delhi",
    "gurugram": "Gurgaon",
    "gurgaon": "Gurgaon",
    "kolkata": "Kolkata",
    "calcutta": "Kolkata",
    "chennai": "Chennai",
    "madras": "Chennai",
    "pune": "Pune",
    "ahmedabad": "Ahmedabad",
    "noida": "Noida",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "thiruvananthapuram": "Trivandrum",
    "trivandrum": "Trivandrum",
    "vadodara": "Vadodara",
    "baroda": "Vadodara",
}

# When city missing/unknown, fall back to state's main commercial center
STATE_DEFAULT_CITY = {
    "telangana": "Hyderabad",
    "maharashtra": "Mumbai",
    "karnataka": "Bangalore",
    "tamil nadu": "Chennai",
    "delhi": "Delhi",
    "west bengal": "Kolkata",
    "gujarat": "Ahmedabad",
    "andhra pradesh": "Visakhapatnam",
    "kerala": "Kochi",
    "rajasthan": "Jaipur",
    "punjab": "Chandigarh",
    "haryana": "Gurgaon",
    "uttar pradesh": "Noida",
}


def normalize_location(city: str, state: str) -> tuple[str, str]:
    """Return (canonical_city, canonical_state)."""
    city = (city or "").strip()
    state = (state or "").strip()
    state_norm = state.title() if state else "Unknown"

    # Telangana special case: 95%+ of listed cos are in Hyderabad metro region.
    # Collapse all Telangana entries to Hyderabad regardless of yfinance city.
    if state.lower() == "telangana":
        return "Hyderabad", state_norm

    # Known synonym
    if city.lower() in CITY_NORMALIZATION:
        return CITY_NORMALIZATION[city.lower()], state_norm

    # City present but unrecognized → use as-is (title case)
    if city:
        return city.title(), state_norm

    # No city → use state default
    if state.lower() in STATE_DEFAULT_CITY:
        return STATE_DEFAULT_CITY[state.lower()], state_norm

    return "Unknown", state_norm


def fetch_nse_universe() -> list[str]:
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
    try:
        t = yf.Ticker(f"{symbol}.NS")
        info = t.info or {}
        mcap = info.get("marketCap")
        if not mcap or mcap <= 0:
            return None

        city, state = normalize_location(info.get("city"), info.get("state"))

        revenue = profit = growth = None
        latest_fy = None
        try:
            fin = t.financials
            if isinstance(fin, pd.DataFrame) and not fin.empty:
                cols = sorted(fin.columns, reverse=True)
                if cols and hasattr(cols[0], "strftime"):
                    latest_fy = cols[0].strftime("%Y-%m-%d")
                if "Total Revenue" in fin.index and cols:
                    revenue = fin.loc["Total Revenue", cols[0]] / CR
                    if len(cols) >= 2:
                        prev = fin.loc["Total Revenue", cols[1]]
                        if prev and prev != 0:
                            growth = ((fin.loc["Total Revenue", cols[0]] - prev) / abs(prev)) * 100
                if "Net Income" in fin.index and cols:
                    profit = fin.loc["Net Income", cols[0]] / CR
        except Exception:
            pass

        return {
            "ticker": f"{symbol}.NS",
            "name": info.get("longName") or info.get("shortName") or symbol,
            "sector": info.get("sector") or "Unknown",
            "industry": info.get("industry") or "Unknown",
            "city": city,
            "state": state,
            "market_cap_cr": mcap / CR,
            "revenue_cr": revenue,
            "profit_cr": profit,
            "revenue_growth_yoy": growth,
            "pe": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "roe_pct": (info.get("returnOnEquity") or 0) * 100 if info.get("returnOnEquity") else None,
            "debt_to_equity": (info.get("debtToEquity") or 0) / 100 if info.get("debtToEquity") else None,
            "dividend_yield_pct": (info.get("dividendYield") or 0) * 100 if info.get("dividendYield") else None,
            "latest_fy_end": latest_fy,
        }
    except Exception:
        return None


def main():
    symbols = fetch_nse_universe()
    print(f"[2/2] Enriching {len(symbols)} tickers via Yahoo Finance (12 parallel workers)")
    rows = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(enrich_ticker, s): s for s in symbols}
        for i, fut in enumerate(as_completed(futures)):
            if (i + 1) % 100 == 0:
                print(f"      Progress: {i+1}/{len(symbols)} done, {len(rows)} with data")
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
    if "latest_fy_end" in df.columns:
        fy = df["latest_fy_end"].dropna()
        if not fy.empty:
            print(f"      FY end dates: {fy.min()} → {fy.max()}")


if __name__ == "__main__":
    main()
