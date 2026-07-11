"""Načítání tick dat z Databento CSV exportů (schema trades)."""
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "GLBX-20260706-FHDPJFRK7B"

COLUMNS = ["ts_event", "price", "size", "side", "symbol"]


def load_day(date: str, front_month_only: bool = True) -> pd.DataFrame:
    """Načte ticky jednoho dne (date = 'YYYYMMDD' nebo 'YYYY-MM-DD').

    Vrací DataFrame s indexem ts_event a sloupci price, size, side, symbol.
    side = strana agresora: 'B' (bid) = agresivní nákup, 'A' (ask) = agresivní
    prodej, 'N' = neurčeno.
    """
    date = date.replace("-", "")
    path = DATA_DIR / f"glbx-mdp3-{date}.trades.csv"
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(
        path,
        usecols=COLUMNS,
        parse_dates=["ts_event"],
        dtype={"price": "float64", "size": "int32", "side": "category", "symbol": "category"},
    )
    df = df.set_index("ts_event").sort_index()

    if front_month_only:
        front = df.groupby("symbol", observed=True)["size"].sum().idxmax()
        df = df[df["symbol"] == front]
    return df
