# Trading bot

Vývoj trading bota pro NQ futures postaveného na tick datech a orderflow.

## Struktura
- `bot/` — hlavní Python balíček (orderflow metriky, strategie, backtester)
- `scripts/` — jednorázové skripty (příprava dat, analýzy)
- `tests/` — testy
- `notebooks/` — experimenty a vizualizace
- `data/` — historická data (mimo git, ~11 GB)

## Prostředí
```bash
source .venv/bin/activate
```

## Plán (fáze)
1. Načítání ticků a výpočet orderflow metrik (delta, kumulativní delta, volume profile)
2. Replay engine — přehrávání historických ticků jako simulace živého trhu
3. Vývoj a backtest strategie nad orderflow
4. Live napojení (feed + exekuce) — až po ověření na historii
# tradingbot
