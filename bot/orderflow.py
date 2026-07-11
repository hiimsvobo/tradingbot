"""Orderflow metriky počítané z tick dat (schema trades)."""
import numpy as np
import pandas as pd

TICK_SIZE = 0.25  # NQ


def signed_size(df: pd.DataFrame) -> pd.Series:
    """Objem se znaménkem podle agresora: +size nákup (B), -size prodej (A)."""
    sign = np.where(df["side"] == "B", 1, np.where(df["side"] == "A", -1, 0))
    return df["size"] * sign


def delta_bars(df: pd.DataFrame, freq: str = "1min") -> pd.DataFrame:
    """OHLCV bary + delta (buy − sell objem) a kumulativní delta."""
    signed = signed_size(df)
    bars = pd.DataFrame({
        "open": df["price"].resample(freq).first(),
        "high": df["price"].resample(freq).max(),
        "low": df["price"].resample(freq).min(),
        "close": df["price"].resample(freq).last(),
        "volume": df["size"].resample(freq).sum(),
        "delta": signed.resample(freq).sum(),
        "trades": df["price"].resample(freq).count(),
    }).dropna(subset=["open"])
    bars["cum_delta"] = bars["delta"].cumsum()
    return bars


def volume_profile(df: pd.DataFrame, tick_size: float = TICK_SIZE) -> pd.DataFrame:
    """Objem, buy/sell objem a delta po cenových hladinách."""
    level = (df["price"] / tick_size).round() * tick_size
    signed = signed_size(df)
    prof = pd.DataFrame({
        "volume": df.groupby(level)["size"].sum(),
        "delta": signed.groupby(level).sum(),
    })
    prof.index.name = "price"
    return prof.sort_index()


def poc(profile: pd.DataFrame) -> float:
    """Point of Control — hladina s největším zobchodovaným objemem."""
    return float(profile["volume"].idxmax())


def large_trades(df: pd.DataFrame, min_size: int = 20) -> pd.DataFrame:
    """Obchody s objemem >= min_size kontraktů (aktivita velkých hráčů)."""
    return df[df["size"] >= min_size]
