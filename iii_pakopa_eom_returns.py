import requests
import pandas as pd
from bs4 import BeautifulSoup
import datetime as dt
from dateutil.relativedelta import relativedelta
import io
import numpy as np

INVESTAVIMAS_URL = "https://www.investavimas.lt/iii-pakopa-ir-fondai/"
FINANSAI_URL = "https://www.finansaipaprastai.lt/resursai/fondai"
OUTPUT_PATH = "/mnt/data/iii-pakopa-eom-returns.xlsx"

PROVIDER_NORMALIZATION = {
    'SEB': 'SEB',
    'Swedbank': 'Swedbank',
    'Luminor': 'Luminor',
    'Goindex': 'Goindex',
    'Artea': 'Artea',
    'iShares': 'iShares',
}


def parse_main_table():
    """Parse comparison table from investavimas.lt."""
    html = requests.get(INVESTAVIMAS_URL).text
    tables = pd.read_html(html)
    table = tables[0]
    table.columns = ['Valdytojas', 'Fondas / Kryptis', 'Priemonė']
    # capture links
    soup = BeautifulSoup(html, 'lxml')
    comp_table = soup.find('table')
    links = []
    for row in comp_table.find_all('tr')[1:]:
        a = row.find('a')
        if a and a.get('href'):
            links.append(a['href'])
        else:
            links.append(None)
    table['SourceLink'] = links
    return table


def find_source_for_fund(row):
    """Discover historical data source URL for a fund row."""
    # Placeholder: search Finansaipaprastai table for provider/fund name
    try:
        html = requests.get(FINANSAI_URL).text
        df_list = pd.read_html(html)
        combined = pd.concat(df_list, ignore_index=True)
        match = combined[combined.iloc[:,0].str.contains(row['Fondas / Kryptis'], case=False, na=False)]
        if not match.empty:
            return match.iloc[0][1]  # assume second column has link
    except Exception:
        pass
    return row['SourceLink']


def load_series_from_source(url):
    """Load monthly EOM series from source URL.

    Supports CSV/JSON or HTML tables containing NAV/price history.
    """
    if url is None:
        return None
    if url.endswith('.csv'):
        data = pd.read_csv(url, parse_dates=[0])
    elif url.endswith('.json'):
        data = pd.read_json(url)
    else:
        try:
            tables = pd.read_html(url)
            data = tables[0]
        except Exception:
            return None
    # heuristic to find date/value columns
    date_col = None
    value_col = None
    for col in data.columns:
        if 'date' in str(col).lower():
            date_col = col
        if any(k in str(col).lower() for k in ['nav', 'price', 'close']):
            value_col = col
    if date_col is None or value_col is None:
        return None
    series = data[[date_col, value_col]].dropna()
    series[date_col] = pd.to_datetime(series[date_col])
    series = series.set_index(date_col).sort_index()[value_col]
    # downsample to EOM
    series = series.resample('M').last().dropna()
    return series


def compute_trailing_returns(series, T):
    def ret(start):
        if start not in series.index:
            return np.nan
        return series.loc[T] / series.loc[start] - 1
    out = {}
    out['1 mėn.'] = ret(T - relativedelta(months=1))
    out['Šiemet'] = ret(dt.datetime(T.year, 12, 31))
    out['12 mėn.'] = ret(T - relativedelta(months=12))
    out['3 metai'] = ret(T - relativedelta(months=36))
    out['5 metai'] = ret(T - relativedelta(months=60))
    return out


def main():
    table = parse_main_table()
    history_rows = []
    returns_rows = []
    notes = []
    max_T = None
    for _, row in table.iterrows():
        source = find_source_for_fund(row)
        series = load_series_from_source(source)
        if series is None or series.empty:
            notes.append({'Provider': row['Valdytojas'], 'Fund': row['Fondas / Kryptis'], 'Note': 'No data source found', 'SourceURL': source})
            continue
        T = series.index.max().to_pydatetime()
        if max_T is None or T > max_T:
            max_T = T
        returns = compute_trailing_returns(series, T)
        returns_row = {
            'Valdytojas': PROVIDER_NORMALIZATION.get(row['Valdytojas'], row['Valdytojas']),
            'Fondas / Kryptis': row['Fondas / Kryptis'],
            'Priemonė': row['Priemonė'],
            'As of': T.strftime('%Y-%m-%d')
        }
        for k, v in returns.items():
            returns_row[k] = v
        returns_rows.append(returns_row)
        for date, value in series.items():
            history_rows.append({
                'Provider': row['Valdytojas'],
                'Fund': row['Fondas / Kryptis'],
                'InstrumentType': row['Priemonė'],
                'ISIN': '',
                'Currency': '',
                'Date_EOM': date.strftime('%Y-%m-%d'),
                'EOM_Level': value,
                'SourceURL': source,
            })
    returns_df = pd.DataFrame(returns_rows)
    for col in ['1 mėn.', 'Šiemet', '12 mėn.', '3 metai', '5 metai']:
        if col in returns_df:
            returns_df[col] = (returns_df[col] * 100).round(2)
    history_df = pd.DataFrame(history_rows)
    notes_df = pd.DataFrame(notes)
    with pd.ExcelWriter(OUTPUT_PATH) as writer:
        returns_df.to_excel(writer, sheet_name='Returns', index=False)
        history_df.to_excel(writer, sheet_name='EOM_History', index=False)
        notes_df.to_excel(writer, sheet_name='Notes', index=False)
    print(f"Saved {OUTPUT_PATH}")

if __name__ == '__main__':
    main()
