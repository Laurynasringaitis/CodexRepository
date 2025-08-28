import yfinance as yf
import pandas as pd
import requests
import re
import sys
import subprocess
from io import BytesIO
from pathlib import Path

# -----------------------------
# Settings
# -----------------------------
tickers = ["SE0015192349", "LU1711526407", "ACWI"]

# If you want to "freeze" today to test logic for a specific date (e.g., Aug 26):
# today = pd.Timestamp("2025-08-26").normalize()
# Otherwise, use the real current day:
today = pd.Timestamp.today().normalize()

# -----------------------------
# Helpers
# -----------------------------
def get_eom_prices(prices: pd.Series) -> pd.Series:
    """Convert daily prices to month-end prices."""
    return prices.resample('ME').last()


def calc_return_eom(eom_prices: pd.Series, start_date: pd.Timestamp, end_date: pd.Timestamp):
    """Period return using end-of-month prices."""
    try:
        start_price = eom_prices.loc[start_date]
        end_price = eom_prices.loc[end_date]
        return (end_price / start_price - 1) * 100
    except KeyError:
        return None


def _ensure_excel_engine():
    """Ensure an .xls reader is available."""
    for eng, pkg, spec in (("calamine", "python-calamine", "python-calamine"),
                           ("xlrd", "xlrd", "xlrd<2.0")):
        try:
            if eng == "calamine":
                import calamine  # noqa: F401
            else:
                import xlrd  # noqa: F401
            return eng
        except Exception:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", spec], stdout=subprocess.DEVNULL)
                return eng
            except Exception:
                continue
    raise RuntimeError("No .xls engine available. Tried python-calamine and xlrd<2.0.")


def _find_history_xls_url(page_html: str, base: str) -> str:
    """Locate the XLS link for historical NAV values."""
    m = re.search(r'href="([^"]+pensiju_fondai/[^"]+\.xls)".{0,120}istorija', page_html, flags=re.I | re.S)
    if not m:
        m = re.search(r'href="([^"]+pensiju_fondai/[^"]+\.xls)"', page_html, flags=re.I)
    if not m:
        raise ValueError("Could not locate XLS link on the fund page.")
    href = m.group(1)
    if href.startswith("http"):
        return href
    from urllib.parse import urljoin
    return urljoin(base, href)


def fetch_history_dataframe(fund_page_url: str) -> pd.DataFrame:
    r = requests.get(fund_page_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    xls_url = _find_history_xls_url(r.text, fund_page_url)

    xr = requests.get(xls_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    xr.raise_for_status()
    buf = BytesIO(xr.content)

    eng = _ensure_excel_engine()
    df = pd.read_excel(buf, engine=eng)
    df = df.dropna(how="all").dropna(how="all", axis=1)
    df.columns = [str(c).strip() for c in df.columns]
    date_col = next((c for c in df.columns if "data" in c.lower() or "date" in c.lower()), df.columns[0])
    value_col = next((c for c in df.columns if c != date_col and re.search(r"(vert|value|kaina|nav)", str(c), re.I)), None)
    if value_col is None:
        value_col = df.columns[1]
    out = df[[date_col, value_col]].rename(columns={date_col: "date", value_col: "nav"})
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["nav"] = pd.to_numeric(out["nav"], errors="coerce")
    return out.dropna(subset=["date", "nav"]).sort_values("date").reset_index(drop=True)


def process_custom_fund(company: str, name: str, url: str):
    df = fetch_history_dataframe(url)
    df.set_index("date", inplace=True)
    eom_prices = df["nav"].resample("ME").last()
    last_eom = eom_prices[eom_prices.index < today].index.max()
    if pd.isna(last_eom):
        return None

    date_1m = last_eom - pd.DateOffset(months=1)
    date_12m = last_eom - pd.DateOffset(years=1)
    date_3y = last_eom - pd.DateOffset(years=3)
    date_5y = last_eom - pd.DateOffset(years=5)
    date_ytd = pd.Timestamp(f"{last_eom.year - 1}-12-31") if last_eom.month < 12 else pd.Timestamp(f"{last_eom.year}-12-31")

    returns = {
        "1 mėn.": calc_return_eom(eom_prices, date_1m, last_eom),
        "grąža [1] nuo metų pradžios, proc.": calc_return_eom(eom_prices, date_ytd, last_eom),
        "vidutinė metinė grąža [2] per praėjusius 1 metus, proc.": calc_return_eom(eom_prices, date_12m, last_eom),
        "vidutinė metinė grąža [2] per praėjusius 3 metus, proc.": calc_return_eom(eom_prices, date_3y, last_eom),
        "vidutinė metinė grąža [2] per praėjusius 5 metus, proc.": calc_return_eom(eom_prices, date_5y, last_eom),
    }

    row = {
        "Pensijų kaupimo bendrovės pavadinimas\n": company,
        "Pensijų fondo pavadinimas\n": name,
    }
    row.update(returns)
    return row

# -----------------------------
# Main
# -----------------------------
rows = []

# Yahoo Finance sources
for ticker in tickers:
    msci = yf.Ticker(ticker)
    try:
        info = msci.info
    except Exception:
        info = {}
    fund_company = info.get("fundFamily", "N/A")
    fund_name = info.get("longName", ticker)
    try:
        hist = msci.history(period="6y", interval="1d")["Close"]
        hist.index = hist.index.tz_localize(None)
    except Exception:
        hist = pd.Series(dtype="float64")
    if hist.empty:
        print(f"No data for ticker {ticker}")
        continue
    eom_prices = get_eom_prices(hist)
    eom_prices.index = eom_prices.index.normalize()
    last_eom = eom_prices[eom_prices.index < today].index.max()
    if pd.isna(last_eom):
        print(f"No valid month-end data before {today.date()} for {ticker}")
        continue
    date_1m = last_eom - pd.DateOffset(months=1)
    date_12m = last_eom - pd.DateOffset(years=1)
    date_3y = last_eom - pd.DateOffset(years=3)
    date_5y = last_eom - pd.DateOffset(years=5)
    date_ytd = pd.Timestamp(f"{last_eom.year - 1}-12-31") if last_eom.month < 12 else pd.Timestamp(f"{last_eom.year}-12-31")
    returns = {
        "1 mėn.": calc_return_eom(eom_prices, date_1m, last_eom),
        "grąža [1] nuo metų pradžios, proc.": calc_return_eom(eom_prices, date_ytd, last_eom),
        "vidutinė metinė grąža [2] per praėjusius 1 metus, proc.": calc_return_eom(eom_prices, date_12m, last_eom),
        "vidutinė metinė grąža [2] per praėjusius 3 metus, proc.": calc_return_eom(eom_prices, date_3y, last_eom),
        "vidutinė metinė grąža [2] per praėjusius 5 metus, proc.": calc_return_eom(eom_prices, date_5y, last_eom),
    }
    row = {
        "Pensijų kaupimo bendrovės pavadinimas\n": fund_company,
        "Pensijų fondo pavadinimas\n": fund_name,
    }
    row.update(returns)
    rows.append(row)

# Custom funds scraped from web sources
custom_funds = [
    {
        "company": "Luminor",
        "name": "Tvari ateitis Index",
        "url": "https://www.luminor.lt/lt/rinkis-fonda?fund=22",
    },
    # Add more custom funds here
]

for f in custom_funds:
    row = process_custom_fund(f["company"], f["name"], f["url"])
    if row:
        rows.append(row)

# Assemble DataFrame once all rows collected
df2 = pd.DataFrame(rows)

df2['Pensijų kaupimo bendrovės pavadinimas\n'] = df2.apply(
    lambda row: row['Pensijų fondo pavadinimas\n'].split()[0]
    if pd.isna(row['Pensijų kaupimo bendrovės pavadinimas\n'])
       or row['Pensijų kaupimo bendrovės pavadinimas\n'] in ["N/A", "", None]
    else row['Pensijų kaupimo bendrovės pavadinimas\n'],
    axis=1
)

return_columns = [col for col in df2.columns if ('proc.' in col) or ('mėn.' in col)]
df2[return_columns] = df2[return_columns].round(2)

if __name__ == "__main__":
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(df2)
