import pandas as pd
import requests
from pathlib import Path

URL = "https://www.luminor.lt/lt/rinkis-fonda?fund=22"

def fetch_luminor_fund_history(url: str = URL) -> pd.DataFrame:
    """Download Luminor Tvari Ateitis Index fund history and return DataFrame.

    Parameters
    ----------
    url: str
        Page that contains the fund history table.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    tables = pd.read_html(response.text)
    if not tables:
        raise ValueError("No tables found in the fund history page")
    # Assume the first table holds the historical values.
    history = tables[0]
    return history

def save_history_to_csv(df: pd.DataFrame, path: str | Path) -> None:
    """Save the DataFrame to CSV file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)

if __name__ == "__main__":
    data_path = Path("data/luminor_tvari_ateitis_index.csv")
    df = fetch_luminor_fund_history()
    save_history_to_csv(df, data_path)
    print(f"Saved {len(df)} rows to {data_path}")
