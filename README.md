# CodexRepository

This repository contains utilities for working with pension fund data.

## Download Luminor Tvari Ateitis Index history

Run the provided script to download the fund's historical unit values and store them as a CSV file for use in Jupyter notebooks.

```bash
pip install -r requirements.txt
python scripts/fetch_luminor_fund.py
```

The script saves the history to `data/luminor_tvari_ateitis_index.csv`.

You can then load it in a notebook:

```python
import pandas as pd

df = pd.read_csv("data/luminor_tvari_ateitis_index.csv")
print(df.head())
```
