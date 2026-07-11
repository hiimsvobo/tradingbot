# Trading bot

Cíl: bot pro NQ futures sledující tick data a orderflow. Postup po fázích viz README.md — nejdřív orderflow metriky a replay na historických ticích, live napojení až nakonec.

## Struktura
- `bot/` — hlavní balíček, `scripts/` — jednorázové skripty, `tests/`, `notebooks/`
- Poznámka: backtesting.py se pro tick/orderflow strategie nehodí (je na OHLCV) — backtester píšeme vlastní, event-driven.

## Prostředí
- Python 3.14.6 (Homebrew, `/opt/homebrew/bin/python3`)
- Virtuální prostředí: `.venv/` (aktivace: `source .venv/bin/activate`)
- Knihovny: pandas 3.0.3, numpy 2.5.1, backtesting 0.6.5, matplotlib 3.11.0

## Data
- `data/GLBX-20260706-FHDPJFRK7B/` — NQ futures (NQ.FUT, CME Globex) z Databento, tick data (schema `trades`), 2025-07-06 až 2026-07-05, denní CSV (~11 GB celkem)
- Sloupce: ts_recv, ts_event, price, size, side, symbol (kontrakty NQU5, NQZ5, …)
- Pro backtesting.py je nutné ticky agregovat do OHLCV barů (pandas resample)
