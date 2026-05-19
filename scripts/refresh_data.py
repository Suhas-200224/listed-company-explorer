"""Auto-refresh script v3 — Screener.in scraper.

Replaces Yahoo Finance with Screener.in for comprehensive Indian listed
company coverage (~2,000-2,500 NSE+BSE companies vs ~600 with Yahoo).

How it works:
1. Discovers all companies with market cap > 0 from Screener's screen tool
2. For each company, scrapes the detail page for fundamentals + address
3. Extracts city/state from the company's About section text
4. Writes enriched CSV

Runs daily via GitHub Actions. Takes 30-45 minutes per refresh.
"""

import io
import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

SCREENER_BASE = "https://www.screener.in"
OUTPUT = Path(__file__).parent.parent / "data" / "companies_enriched.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── Location normalization ─────────────────────────────────────────────────

CITY_KEYWORDS = {
    "hyderabad": "Hyderabad",
    "secunderabad": "Hyderabad",
    "hitec city": "Hyderabad",
    "gachibowli": "Hyderabad",
    "kondapur": "Hyderabad",
    "navi mumbai": "Mumbai",
    "mumbai": "Mumbai",
    "bombay": "Mumbai",
    "thane": "Mumbai",
    "bengaluru": "Bangalore",
    "bangalore": "Bangalore",
    "new delhi": "Delhi",
    "delhi": "Delhi",
    "gurugram": "Gurgaon",
    "gurgaon": "Gurgaon",
    "noida": "Noida",
    "kolkata": "Kolkata",
    "calcutta": "Kolkata",
    "chennai": "Chennai",
    "madras": "Chennai",
    "pune": "Pune",
    "ahmedabad": "Ahmedabad",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "vadodara": "Vadodara",
    "jaipur": "Jaipur",
    "chandigarh": "Chandigarh",
    "indore": "Indore",
    "lucknow": "Lucknow",
    "coimbatore": "Coimbatore",
    "vizag": "Visakhapatnam",
    "visakhapatnam": "Visakhapatnam",
}

STATE_KEYWORDS = {
    "telangana": "Telangana",
    "andhra pradesh": "Andhra Pradesh",
    "maharashtra": "Maharashtra",
    "karnataka": "Karnataka",
    "tamil nadu": "Tamil Nadu",
    "west bengal": "West Bengal",
    "gujarat": "Gujarat",
    "kerala": "Kerala",
    "rajasthan": "Rajasthan",
    "punjab": "Punjab",
    "haryana": "Haryana",
    "uttar pradesh": "Uttar Pradesh",
    "madhya pradesh": "Madhya Pradesh",
    "delhi": "Delhi",
    "odisha": "Odisha",
    "bihar": "Bihar",
    "chhattisgarh": "Chhattisgarh",
    "jharkhand": "Jharkhand",
    "assam": "Assam",
    "uttarakhand": "Uttarakhand",
    "himachal pradesh": "Himachal Pradesh",
    "jammu and kashmir": "Jammu and Kashmir",
    "goa": "Goa",
}


def extract_location(text: str) -> tuple[str, str]:
    """Extract canonical city, state from address-like text."""
    if not text:
        return "Unknown", "Unknown"
    text_lower = text.lower()
    state = "Unknown"
    for kw, canonical in STATE_KEYWORDS.items():
        if kw in text_lower:
            state = canonical
            break
    city = "Unknown"
    for kw, canonical in CITY_KEYWORDS.items():
        if kw in text_lower:
            city = canonical
            break
    # Telangana → Hyderabad fallback
    if state == "Telangana" and city == "Unknown":
        city = "Hyderabad"
    return city, state


# ─── Number parsing ─────────────────────────────────────────────────────────

def parse_number(s) -> float | None:
    """Parse Indian financial strings like '₹ 1,76,234 Cr.', '12.5%', '4.85'."""
    if not s:
        return None
    s = str(s).strip()
    # Take portion before any %, /, etc
    s = re.split(r'[/%]', s)[0]
    cleaned = re.sub(r'[^\d.\-]', '', s)
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


# ─── Universe discovery ────────────────────────────────────────────────────

def fetch_universe() -> list[str]:
    """Get all company codes from Screener's screen tool (mcap > 0)."""
    print("[1/2] Discovering listed company universe via Screener.in screen...")
    codes = set()
    consecutive_empty = 0

    for page in range(1, 250):
        url = (
            f"{SCREENER_BASE}/screen/raw/"
            f"?sort=&source=&order=&page={page}"
            f"&query=Market+Capitalization+%3E+0"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                if r.status_code == 429:
                    print(f"      Page {page}: rate limited, pausing 10s")
                    time.sleep(10)
                    continue
                break

            soup = BeautifulSoup(r.text, "html.parser")
            page_codes = set()
            for a in soup.select('a[href^="/company/"]'):
                href = a.get("href", "")
                m = re.match(r"^/company/([^/]+)/?", href)
                if m:
                    page_codes.add(m.group(1))

            if not page_codes:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0
                codes.update(page_codes)

            if page % 20 == 0:
                print(f"      Page {page}: {len(codes)} unique cos so far")
            time.sleep(0.3)
        except Exception as e:
            print(f"      Page {page} error: {e}")
            continue

    print(f"      Universe size: {len(codes)} companies")
    return list(codes)


# ─── Per-company scraping ──────────────────────────────────────────────────

def scrape_company(code: str) -> dict | None:
    """Scrape a single company detail page from Screener."""
    # Try consolidated first (better data), fall back to standalone
    r = None
    for endpoint in ("consolidated/", ""):
        url = f"{SCREENER_BASE}/company/{code}/{endpoint}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r and r.status_code == 200 and "Page not found" not in r.text[:5000]:
                break
        except Exception:
            r = None
    if not r or r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else None
    if not name:
        return None

    # Top ratios — try the standard Screener structure
    ratios = {}
    # Primary structure: ul#top-ratios > li with name + number/value spans
    for li in soup.select("ul#top-ratios > li"):
        name_span = li.find("span", class_="name")
        value_span = li.find("span", class_=re.compile(r"(value|number)"))
        if name_span and value_span:
            ratios[name_span.get_text(strip=True)] = value_span.get_text(strip=True)

    # Fallback for slightly different structure
    if not ratios:
        for li in soup.find_all("li", class_=re.compile(r"flex")):
            spans = li.find_all("span")
            if len(spans) >= 2:
                label = spans[0].get_text(strip=True)
                value = spans[-1].get_text(strip=True)
                if label and value and len(label) < 30:
                    ratios.setdefault(label, value)

    mcap = parse_number(ratios.get("Market Cap"))
    if not mcap or mcap <= 0:
        return None

    # About text — for address extraction. Try multiple selectors.
    about_text = ""
    about_div = soup.find("div", class_="company-profile") or soup.find("div", class_="about")
    if about_div:
        about_text = about_div.get_text(separator=" ", strip=True)
    if not about_text:
        # Find About heading and grab following paragraphs
        for h in soup.find_all(["h2", "h3"]):
            if h.get_text(strip=True).lower().startswith("about"):
                parts = []
                for sib in h.find_next_siblings():
                    if sib.name in ("h2", "h3"):
                        break
                    parts.append(sib.get_text(separator=" ", strip=True))
                about_text = " ".join(parts)
                break

    # Sector / industry from peer comparison links
    sector = industry = None
    for link in soup.select('a[href*="/screen/"]'):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        if not text or len(text) > 50 or text.isdigit():
            continue
        if "sector_name" in href and not sector:
            sector = text
        elif "industry_name" in href and not industry:
            industry = text

    # PnL latest annual values
    revenue = profit = latest_fy = None
    pnl = soup.find("section", id="profit-loss")
    if pnl:
        table = pnl.find("table")
        if table:
            thead = table.find("thead")
            if thead:
                cols = [th.get_text(strip=True) for th in thead.find_all("th")]
                if len(cols) >= 2:
                    latest_fy = cols[-1]
            tbody = table.find("tbody")
            if tbody:
                for tr in tbody.find_all("tr"):
                    cells = tr.find_all("td")
                    if len(cells) < 2:
                        continue
                    row_label = cells[0].get_text(strip=True).rstrip("+").strip().lower()
                    latest_val = cells[-1].get_text(strip=True)
                    if row_label in ("sales", "revenue"):
                        revenue = parse_number(latest_val)
                    elif row_label == "net profit":
                        profit = parse_number(latest_val)

    city, state = extract_location(about_text)

    return {
        "ticker": f"{code}.NS",
        "name": name,
        "sector": sector or "Unknown",
        "industry": industry or "Unknown",
        "city": city,
        "state": state,
        "market_cap_cr": mcap,
        "revenue_cr": revenue,
        "profit_cr": profit,
        "revenue_growth_yoy": None,
        "pe": parse_number(ratios.get("Stock P/E")),
        "eps": None,
        "roe_pct": parse_number(ratios.get("ROE")),
        "roce_pct": parse_number(ratios.get("ROCE")),
        "debt_to_equity": None,
        "dividend_yield_pct": parse_number(ratios.get("Dividend Yield")),
        "book_value": parse_number(ratios.get("Book Value")),
        "current_price": parse_number(ratios.get("Current Price")),
        "face_value": parse_number(ratios.get("Face Value")),
        "latest_fy_end": latest_fy,
    }


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    universe = fetch_universe()
    if not universe:
        print("FATAL: empty universe — Screener fetch failed")
        return

    print(f"[2/2] Scraping {len(universe)} company detail pages (3 workers)")
    rows = []
    completed = 0
    last_save_count = 0

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(scrape_company, c): c for c in universe}
        for fut in as_completed(futures):
            completed += 1
            try:
                result = fut.result(timeout=30)
                if result:
                    rows.append(result)
            except Exception:
                pass

            if completed % 100 == 0:
                print(f"      Progress: {completed}/{len(universe)} done, {len(rows)} with data")
                # Periodic save so even partial runs are useful
                if len(rows) - last_save_count >= 300:
                    pd.DataFrame(rows).sort_values(
                        "market_cap_cr", ascending=False, na_position="last"
                    ).to_csv(OUTPUT, index=False)
                    last_save_count = len(rows)

    df = pd.DataFrame(rows).sort_values("market_cap_cr", ascending=False, na_position="last")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT, index=False)

    print(f"\n[Done] Wrote {len(df)} companies to {OUTPUT}")
    print(f"       Sectors discovered: {df['sector'].nunique()}")
    print(f"       Cities discovered: {df['city'].nunique()}")
    if "city" in df.columns:
        for city in ("Hyderabad", "Mumbai", "Bangalore", "Delhi", "Chennai"):
            count = (df["city"] == city).sum()
            print(f"       {city}: {count} cos")


if __name__ == "__main__":
    main()
