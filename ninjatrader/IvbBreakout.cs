// IvbBreakout — port strategie z bot/strategy_ivb.py (Python replay engine).
//
// IVB model A s filtrem velikosti svíčky (NQ, RTH). IB = high/low 9:30-9:45 ET
// z ticků; od 9:45 se staví 5min bary z ticků (OnMarketData) včetně delty a
// big sweepů po cenách. Vstup na close 5min baru, který zavře za IB:
// delta ve směru, objem >= VolMult x průměr předchozích 6 barů, wick proti
// <= WickMax x range, big sweepy proti směru v krajní čtvrtině baru
// < AbsorbMax (žádná absorpce), risk (close az za extrém svíčky) >= MinRiskPts.
// SL za extrémem breakoutové svíčky, TP RRR x risk limitkou, flat 15:00 ET,
// max 1 obchod/den, oba směry.
//
// Musí dávat shodné obchody s Python verzí na stejných datech (ověřit v
// Market Replay proti scripts/backtest_ivb_ticks.py). POZOR: NT 1s timestampy
// slévají sweepy -> absorb filtr je přísnější (podmínka NEpřítomnosti
// absorpce), spíš méně obchodů — ověřit v replay.
//
// SIGNÁLY Z NQ, VSTUPY NA MNQ: strategie čte ticky NQ (tam je objem a
// orderflow), ale objednávky posílá na MNQ sérii (parametr MnqInstrument —
// MUSÍ odpovídat aktuálnímu kontraktu, např. "MNQ 09-26"). Počet mikr =
// floor(RiskUsd / (risk_b * $2)), min 1, strop MaxMicros. Ceny NQ a MNQ jsou
// prakticky identické (stejný index, arbitráž), stopy/targety z NQ cen platí.
//
// Nastavení grafu: NQ (aktuální kontrakt), libovolný časový rámec (bary grafu
// se nepoužívají, jen ticky), session template "CME US Index Futures RTH".
// Calculate = OnEachTick.
//
// Parametry odpovídají tick validaci 17. 7. 2026: risk >= 60 b, TP 3R,
// fixní risk $500 na MNQ: net $11,6k/rok, maxDD $2,0k, 1–4 mikra (medián 3).

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class IvbBreakout : Strategy
    {
        // === parametry ===
        [NinjaScriptProperty, Display(Name = "MnqInstrument (aktuální kontrakt!)", Order = 0)]
        public string MnqInstrument { get; set; }

        [NinjaScriptProperty, Range(50, 5000), Display(Name = "RiskUsd (fixní risk na obchod)", Order = 1)]
        public double RiskUsd { get; set; }

        [NinjaScriptProperty, Range(1, 50), Display(Name = "MaxMicros (strop počtu mikr)", Order = 2)]
        public int MaxMicros { get; set; }

        [NinjaScriptProperty, Range(1, 200), Display(Name = "MinRiskPts (min range svíčky, b)", Order = 3)]
        public double MinRiskPts { get; set; }

        [NinjaScriptProperty, Range(0.5, 10), Display(Name = "Rrr", Order = 4)]
        public double Rrr { get; set; }

        [NinjaScriptProperty, Range(1, 5), Display(Name = "VolMult (x prům. 6 barů)", Order = 5)]
        public double VolMult { get; set; }

        [NinjaScriptProperty, Range(0, 1), Display(Name = "WickMax (podíl range)", Order = 6)]
        public double WickMax { get; set; }

        [NinjaScriptProperty, Range(1, 1000), Display(Name = "BigSweep (ks)", Order = 7)]
        public int BigSweep { get; set; }

        [NinjaScriptProperty, Range(0, 5000), Display(Name = "AbsorbMax (ks proti v krajní 1/4)", Order = 8)]
        public int AbsorbMax { get; set; }

        [NinjaScriptProperty, Range(5, 300), Display(Name = "CataPts (pojistný burzovní stop, b za normálním)", Order = 9)]
        public double CataPts { get; set; }

        // === interní typy ===
        private class Bar5
        {
            public DateTime Slot;
            public double Open, High, Low, Close;
            public long Volume, Delta;
            // price -> [big buy, big sell]
            public Dictionary<double, long[]> BigLevels = new Dictionary<double, long[]>();
        }

        // === stav ===
        private const int MnqBip = 2;        // index MNQ série (0 graf, 1 NQ ticky)
        private const double MnqPointValue = 2.0;
        private double ibHi = double.MinValue, ibLo = double.MaxValue;
        private bool ibValid;
        private Bar5 cur;
        private readonly List<Bar5> bars = new List<Bar5>();
        private DateTime curDay = DateTime.MinValue;   // Eastern datum
        private DateTime tradedDay = DateTime.MinValue;
        private double tickSize;

        private static readonly TimeSpan IbStart = new TimeSpan(9, 30, 0);
        private static readonly TimeSpan IbEnd = new TimeSpan(9, 45, 0);
        private static readonly TimeSpan FlatTime = new TimeSpan(15, 0, 0);
        // časy ticků chodí v časové zóně nastavené v NT (Options > Time zone);
        // strategie je vždy převádí na US Eastern, aby filtr nezávisel na VPS
        private static readonly TimeZoneInfo Eastern =
            TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");

        private int tradeNo;         // unikátní jméno signálu pro každý obchod (OCO)
        private string sigName = "";
        private double cataPrice;    // cena pojistného burzovního stopu (pokládá se po fillu)

        // rozpracovaný sweep (po cenách — absorb filtr potřebuje ceny)
        private DateTime swTime = DateTime.MinValue;
        private int swSide;          // +1 buy, -1 sell, 0 neurčeno
        private long swSize;
        private readonly Dictionary<double, long> swLevels = new Dictionary<double, long>();

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "IvbBreakout";
                Calculate = Calculate.OnEachTick;
                // Lucid/LFE odmítá GTC; vše je intraday (flat 15:00), Day je správně
                TimeInForce = TimeInForce.Day;
                EntriesPerDirection = 1;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 300;

                MnqInstrument = "MNQ 09-26";
                RiskUsd = 500;
                MaxMicros = 10;
                MinRiskPts = 60;
                Rrr = 3.0;
                VolMult = 1.2;
                WickMax = 0.25;
                BigSweep = 50;
                AbsorbMax = 100;
                CataPts = 30;
            }
            else if (State == State.Configure)
            {
                // ticky NQ pro stavbu barů (primární série je jen nosič) — index 1
                AddDataSeries(BarsPeriodType.Tick, 1);
                // MNQ pro exekuci — index 2 (MnqBip)
                AddDataSeries(MnqInstrument, BarsPeriodType.Minute, 1);
            }
            else if (State == State.DataLoaded)
            {
                tickSize = Instrument.MasterInstrument.TickSize;
            }
        }

        protected override void OnMarketData(MarketDataEventArgs e)
        {
            if (e.MarketDataType != MarketDataType.Last)
                return;
            // bary se staví JEN z NQ ticků — MNQ data ignorovat (jiný instrument)
            if (e.Instrument != BarsArray[1].Instrument)
                return;

            DateTime t = e.Time;
            DateTime et = TimeZoneInfo.ConvertTime(
                DateTime.SpecifyKind(t, DateTimeKind.Unspecified),
                Core.Globals.GeneralOptions.TimeZoneInfo, Eastern);
            TimeSpan tod = et.TimeOfDay;

            // nový den -> reset IB a barů
            if (et.Date != curDay)
            {
                curDay = et.Date;
                ibHi = double.MinValue; ibLo = double.MaxValue; ibValid = false;
                bars.Clear();
                cur = null;
                swSize = 0; swLevels.Clear();
            }

            // time-stop otevřené pozice (MNQ)
            if (Positions[MnqBip].MarketPosition != MarketPosition.Flat && tod >= FlatTime)
            {
                if (Positions[MnqBip].MarketPosition == MarketPosition.Long)
                    ExitLong(MnqBip, 0, "TS", sigName);
                else
                    ExitShort(MnqBip, 0, "TS", sigName);
            }

            // IB fáze
            if (tod >= IbStart && tod < IbEnd)
            {
                ibHi = Math.Max(ibHi, e.Price);
                ibLo = Math.Min(ibLo, e.Price);
                ibValid = true;
                return;
            }
            if (tod < IbStart || tod >= FlatTime || !ibValid)
                return;

            // agresor z bid/ask (Databento 'side' ekvivalent)
            int side = e.Price >= e.Ask ? 1 : (e.Price <= e.Bid ? -1 : 0);

            // sweep hranice: nový čas nebo strana -> uzavřít předchozí
            if (t != swTime || side != swSide)
            {
                FlushSweep();
                swTime = t; swSide = side;
            }
            swSize += e.Volume;
            long lv; swLevels.TryGetValue(e.Price, out lv);
            swLevels[e.Price] = lv + e.Volume;

            // 5min slot
            DateTime slot = et.Date.AddMinutes(Math.Floor(tod.TotalMinutes / 5.0) * 5);
            if (cur == null || slot != cur.Slot)
            {
                FlushSweep();
                if (cur != null)
                {
                    OnBar5Close(cur, tod);
                    bars.Add(cur);
                    if (bars.Count > 50) bars.RemoveAt(0);
                }
                cur = new Bar5 { Slot = slot, Open = e.Price, High = e.Price, Low = e.Price };
            }

            cur.High = Math.Max(cur.High, e.Price);
            cur.Low = Math.Min(cur.Low, e.Price);
            cur.Close = e.Price;
            cur.Volume += e.Volume;
            cur.Delta += side * e.Volume;
        }

        private void FlushSweep()
        {
            if (swSize >= BigSweep && cur != null && swSide != 0)
            {
                int k = swSide == 1 ? 0 : 1;
                foreach (var kv in swLevels)
                {
                    long[] arr;
                    if (!cur.BigLevels.TryGetValue(kv.Key, out arr))
                        cur.BigLevels[kv.Key] = arr = new long[2];
                    arr[k] += kv.Value;
                }
            }
            swSize = 0;
            swLevels.Clear();
        }

        private void OnBar5Close(Bar5 b, TimeSpan tod)
        {
            if (Positions[MnqBip].MarketPosition != MarketPosition.Flat
                || tradedDay == curDay || bars.Count < 6 || tod >= FlatTime)
                return;

            double volAvg = 0;
            for (int i = bars.Count - 6; i < bars.Count; i++) volAvg += bars[i].Volume;
            volAvg /= 6.0;

            double rng = b.High - b.Low;
            if (rng <= 0 || b.Volume < VolMult * volAvg)
                return;

            for (int d = 1; d >= -1; d -= 2)
            {
                double edge = d == 1 ? ibHi : ibLo;
                if ((b.Close - edge) * d <= 0 || b.Delta * d <= 0)
                    continue;

                double wick = d == 1 ? b.High - b.Close : b.Close - b.Low;
                if (wick > WickMax * rng)
                    continue;

                // big sweepy proti směru v krajní čtvrtině baru (absorpce)
                double q = d == 1 ? b.High - 0.25 * rng : b.Low + 0.25 * rng;
                long absorb = 0;
                foreach (var kv in b.BigLevels)
                    if (d == 1 ? kv.Key >= q - 1e-9 : kv.Key <= q + 1e-9)
                        absorb += kv.Value[d == 1 ? 1 : 0];
                if (absorb >= AbsorbMax)
                    continue;

                double stop = d == 1 ? b.Low - tickSize : b.High + tickSize;
                double risk = (b.Close - stop) * d;
                if (risk < MinRiskPts)
                    continue;

                // sizing: fixní dolarový risk na MNQ ($2/bod)
                int micros = (int)(RiskUsd / (risk * MnqPointValue));
                micros = Math.Max(1, Math.Min(MaxMicros, micros));

                tradedDay = curDay;
                double target = b.Close + d * risk * Rrr;
                // unikátní signál pro každý obchod (recyklace OCO ID hází chyby)
                sigName = (d == 1 ? "IvbL" : "IvbS") + (++tradeNo);
                // simulovaný stop: NT ho drží lokálně a při dotyku pošle market
                SetStopLoss(sigName, CalculationMode.Price, stop, true);
                SetProfitTarget(sigName, CalculationMode.Price, target);
                cataPrice = stop - d * CataPts;
                if (d == 1) EnterLong(MnqBip, micros, sigName);
                else EnterShort(MnqBip, micros, sigName);
                return;
            }
        }

        // pojistný BURZOVNÍ stop-market (ne simulovaný): normální stop drží NT
        // lokálně, takže při pádu NT/VPS by pozice zůstala nekrytá. Pokládá se
        // až po fillu vstupu; při zavření pozice ho NT sám zruší.
        protected override void OnPositionUpdate(Cbi.Position position, double averagePrice,
                                                 int quantity, MarketPosition marketPosition)
        {
            // reagovat jen na MNQ pozici (NQ se neobchoduje)
            if (position.Instrument != BarsArray[MnqBip].Instrument)
                return;
            if (marketPosition == MarketPosition.Long)
                ExitLongStopMarket(MnqBip, true, quantity, cataPrice, "Cata", sigName);
            else if (marketPosition == MarketPosition.Short)
                ExitShortStopMarket(MnqBip, true, quantity, cataPrice, "Cata", sigName);
        }

        protected override void OnBarUpdate() { /* logika běží v OnMarketData */ }
    }
}
