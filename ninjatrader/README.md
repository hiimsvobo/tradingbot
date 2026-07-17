# NinjaTrader strategie (Lucid prop účet)

## IvbBreakout (port 16. 7. 2026 — čeká na Market Replay ověření)

Port `bot/strategy_ivb.py` (tick-validovaná verze, WR 58 %, $61,8k/rok na 1× NQ).
IB 9:30–9:45 ET z ticků; vstup na close 5min baru za IB s filtry (delta, objem
≥ 1,2×, wick ≤ 25 %, bez absorpce big sweepy, risk ≥ 60 b); SL za extrémem
svíčky, TP 3R, flat 15:00, max 1 obchod/den. Stejná infrastruktura jako
AbsorptionScalp (Eastern převod, simulovaný stop + pojistný CataPts, Day TIF,
unikátní OCO signály IvbL/IvbS).

Fáze: (1) Market Replay proti `scripts/backtest_ivb_ticks.py` /
`outputs/ivb_ticks_trades.csv` — POZOR: 1s timestampy NT slévají sweepy,
absorb filtr bude přísnější (spíš méně obchodů); (2) rozhodnout sizing
(eval: MNQ dle risku $500 ≈ 2–4 mikra; Contracts + instrument MNQ);
(3) spustit vedle scalpu.

# AbsorptionScalp — nasazení v NinjaTraderu 8 (Lucid prop účet)

Port `bot/strategy_absorption.py` do NinjaScriptu. Stejná pravidla i parametry
(walk-forward 7/2026): 40-range bary, absorpce + big sweepy >= 50 ks (min 100
proti směru), agrese delta >= 5 % + tělo >= 50 %, vstup do 15 b od zóny,
target 2R, stop za zónou, time-stop 15:55 ET, 2 kontrakty.

## Instalace
1. VPS (Windows, 8 GB RAM / 2 jádra stačí) + NinjaTrader 8 přihlášený k Lucid účtu.
2. NinjaTrader: New > NinjaScript Editor > Strategies > pravý klik > Import,
   nebo soubor zkopírovat do `Documents\NinjaTrader 8\bin\Custom\Strategies\`
   a v editoru zkompilovat (F5).
3. Graf: NQ (aktuální kontrakt), session template **CME US Index Futures RTH**.
   Timeframe grafu je jedno — strategie používá vlastní tick sérii.
4. Strategies > přidat AbsorptionScalp, zkontrolovat parametry (default = ověřené),
   Calculate = On each tick. Účet: nejdřív **Sim101!**

## Fáze nasazení (neměnit pořadí)
1. **Ověření portu — HOTOVO 13. 7.** Přesná shoda obchodů s Pythonem není
   dosažitelná: NT feed má sekundové timestampy (Databento ns), big sweepy
   se slévají a setupů prochází víc. Ověřeno jinak: (a) logika portu
   reprodukuje Python při stejném rozlišení dat, (b) celoroční backtest
   i walk-forward s 1s timestampy prošly (net $14,7k; OOS 24/24 ziskových).
   Statistickou shodu dál sledovat v sim fázi.
2. **Sim fáze**: 2–4 týdny na Sim101 s živými daty prop účtu. Očekávání
   podle 1s backtestu (NT feed): ~0,9 obchodu/den, WR ~45 %, avg ~$60/obchod
   na 1 kontrakt, avg win ~2x avg loss. Výrazně víc obchodů/den = problém.
3. **Eval**: 1 kontrakt (kvůli trailing drawdownu evalu), parametr Contracts=1.
4. **Funded**: po fundnutí zvážit Contracts=2 (max risk $600/obchod).

## Provozní poznámky
- Strategie NIC neobchoduje mimo 9:30–16:00 ET; pozice zavírá 15:55,
  pojistka ExitOnSessionClose 15:55 (300 s před 16:00).
- Stop = stop-market, target = limitka (OCO přes SetStopLoss/SetProfitTarget).
- Agresor se odvozuje z bid/ask (price >= ask -> buy). Drobné odchylky od
  Databento dat jsou možné — proto krok 1.
- Časy si strategie sama převádí na US Eastern (oprava 13. 7. — původní verze
  brala čas v zóně NT, na českém VPS pak "RTH filtr" obchodoval v noci NY).
  Zobrazovací zónu NT přesto doporučeno přepnout na Eastern kvůli porovnávání.
- Po výpadku spojení NT strategii vypne — nastavit restart/notifikaci.
- Stop je SIMULOVANÝ (drží ho NT, na burzu jde market až při dotyku) — nutné
  kvůli vstupům, kde cena proskočí stop před odesláním (jinak reject + OCO
  chyby a strategie se vypne). HOTOVO 14. 7.: pojistný BURZOVNÍ stop-market
  CataPts (default 30 b) za normálním stopem — kryje pozici při pádu NT/VPS.
  Pokládá se po fillu vstupu (OnPositionUpdate), při zavření pozice se ruší sám.
- Každý obchod má unikátní jméno signálu (AbsL1, AbsS2, …) kvůli OCO ID.
- TimeInForce = Day (16. 7.): Lucid/LFE odmítá GTC příkazy ("You must set a
  date for TIF=GTD") -> reject vstupu a strategie se vypnula. Vše je intraday,
  Day nic nemění na logice.
- Lucid: automatizace povolena, HFT ne (jsme ~0,6 obchodu/den). Písemné
  potvrzení od supportu archivovat.
