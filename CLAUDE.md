# Trading bot

Cíl: bot pro NQ futures sledující tick data a orderflow. Postup po fázích viz README.md — nejdřív orderflow metriky a replay na historických ticích, live napojení až nakonec.

## Struktura
- `bot/` — hlavní balíček, `scripts/` — jednorázové skripty, `tests/`, `notebooks/`
- Poznámka: backtesting.py se pro tick/orderflow strategie nehodí (je na OHLCV) — backtester píšeme vlastní, event-driven.

## Pravidla deníku (Obsidian: ~/Documents/Obsidian Vault/MyVault/Trading/)
- Do deníku ukládej POUZE: rozhodnutí o strategii a jejich zdůvodnění, výsledky backtestů (parametry, období, výnos, drawdown), poznatky a překvapení, co zbývá dodělat.
- NEUKLÁDEJ: instalace softwaru a knihoven, řešení technických chyb a překlepů, rutinní úpravy kódu bez dopadu na strategii.
- Po každém významném poznatku aktualizuj `Strategie-aktualni-stav.md` — zastaralé informace přepiš, nepřidávej donekonečna.
- Každá strategie má vlastní soubor `Strategie-<nazev>.md` s kompletním kontextem (definice, parametry, výsledky, zákazy, infrastruktura, kde pokračovat) — udržuj ho aktuální, při zahájení nové strategie ho založ. `Strategie-aktualni-stav.md` je jen stručný přehled + průřezové poznatky.
- Technické detaily prostředí (verze, knihovny) patří sem do CLAUDE.md, ne do deníku.

## Bezpečnost
- NIKDY nespouštěj kód, který odesílá reálné objednávky brokerovi, bez výslovného potvrzení uživatele v daném sezení.

## Prostředí
- Python 3.14.6 (Homebrew, `/opt/homebrew/bin/python3`)
- Virtuální prostředí: `.venv/` (aktivace: `source .venv/bin/activate`)
- Knihovny: pandas 3.0.3, numpy 2.5.1, backtesting 0.6.5, matplotlib 3.11.0

## Data
- `data/GLBX-20260706-FHDPJFRK7B/` — NQ futures (NQ.FUT, CME Globex) z Databento, tick data (schema `trades`), 2025-07-06 až 2026-07-05, denní CSV (~11 GB celkem)
- Sloupce: ts_recv, ts_event, price, size, side, symbol (kontrakty NQU5, NQZ5, …)
- Pro backtesting.py je nutné ticky agregovat do OHLCV barů (pandas resample)
