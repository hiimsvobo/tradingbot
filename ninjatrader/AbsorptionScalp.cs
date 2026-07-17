// AbsorptionScalp — port strategie z bot/strategy_absorption.py (Python replay engine).
//
// Scalp absorpce -> agrese na 40-range barech (NQ, RTH). Bary si strategie
// staví sama z ticků (OnMarketData), včetně delty, big sweepů a objemu v těle.
// Musí dávat shodné obchody s Python verzí na stejných datech (ověřit v
// Market Replay proti scripts/backtest_absorption_ticks.py).
//
// Nastavení grafu: NQ 12-26 (aktuální kontrakt), libovolný časový rámec
// (bary grafu se nepoužívají, jen ticky), session template "CME US Index
// Futures RTH". Calculate = OnEachTick.
//
// Parametry odpovídají walk-forwardu 7/2026: zóna maxRisk 15 b, agrese
// delta >= 5 % objemu, tělo >= 50 %, big sweepy >= 50 ks / min 100 ks
// proti směru, target 2R, time-stop 15:55 ET, 2 kontrakty.

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
    public class AbsorptionScalp : Strategy
    {
        // === parametry ===
        [NinjaScriptProperty, Range(1, 10), Display(Name = "Contracts", Order = 1)]
        public int Contracts { get; set; }

        [NinjaScriptProperty, Range(1, 100), Display(Name = "RangeTicks", Order = 2)]
        public int RangeTicks { get; set; }

        [NinjaScriptProperty, Range(1, 50), Display(Name = "MaxRiskPts", Order = 3)]
        public double MaxRiskPts { get; set; }

        [NinjaScriptProperty, Range(0.5, 5), Display(Name = "Rrr", Order = 4)]
        public double Rrr { get; set; }

        [NinjaScriptProperty, Range(0, 1), Display(Name = "AggrDelta (podíl objemu)", Order = 5)]
        public double AggrDelta { get; set; }

        [NinjaScriptProperty, Range(0, 1), Display(Name = "BodyFrac", Order = 6)]
        public double BodyFrac { get; set; }

        [NinjaScriptProperty, Range(1, 1000), Display(Name = "BigSweep (ks)", Order = 7)]
        public int BigSweep { get; set; }

        [NinjaScriptProperty, Range(0, 5000), Display(Name = "MinBig (ks proti směru)", Order = 8)]
        public int MinBig { get; set; }

        [NinjaScriptProperty, Range(1, 20), Display(Name = "MaxWait (barů)", Order = 9)]
        public int MaxWait { get; set; }

        [NinjaScriptProperty, Range(2, 50), Display(Name = "Lookback (barů)", Order = 10)]
        public int Lookback { get; set; }

        [NinjaScriptProperty, Range(0, 1), Display(Name = "WickFrac", Order = 11)]
        public double WickFrac { get; set; }

        [NinjaScriptProperty, Range(5, 200), Display(Name = "CataPts (pojistný burzovní stop, b za normálním)", Order = 12)]
        public double CataPts { get; set; }

        // === interní typy ===
        private class RangeBar
        {
            public double Open, High, Low, Close;
            public long Volume, Delta, BigBuy, BigSell;
            public Dictionary<double, long> Levels = new Dictionary<double, long>();

            public long BodyVol()
            {
                double lo = Math.Min(Open, Close), hi = Math.Max(Open, Close);
                long v = 0;
                foreach (var kv in Levels)
                    if (kv.Key >= lo - 1e-9 && kv.Key <= hi + 1e-9) v += kv.Value;
                return v;
            }
        }

        private class Setup
        {
            public int Direction;   // +1 long, -1 short
            public double Stop;     // za extrémem absorpčního baru
            public int BarsLeft;
        }

        // === stav ===
        private RangeBar cur;
        private readonly List<RangeBar> bars = new List<RangeBar>();
        private readonly List<Setup> setups = new List<Setup>();
        private double rangePts, tickSize;
        private readonly TimeSpan flatTime = new TimeSpan(15, 55, 0);
        // časy ticků chodí v časové zóně nastavené v NT (Options > Time zone);
        // strategie je vždy převádí na US Eastern, aby RTH filtr nezávisel na VPS
        private static readonly TimeZoneInfo Eastern =
            TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");

        private int tradeNo;         // unikátní jméno signálu pro každý obchod (OCO)
        private string sigName = ""; // jméno signálu otevřené/poslední pozice
        private double cataPrice;    // cena pojistného burzovního stopu (pokládá se po fillu)

        // rozpracovaný sweep
        private DateTime swTime = DateTime.MinValue;
        private int swSide;          // +1 buy, -1 sell, 0 neurčeno
        private long swSize;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "AbsorptionScalp";
                Calculate = Calculate.OnEachTick;
                // Lucid/LFE odmítá GTC ("You must set a date for TIF=GTD");
                // vše je intraday (flat 15:55), Day je správně i logicky
                TimeInForce = TimeInForce.Day;
                EntriesPerDirection = 1;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 300;

                Contracts = 2;
                RangeTicks = 40;
                MaxRiskPts = 15;
                Rrr = 2.0;
                AggrDelta = 0.05;
                BodyFrac = 0.5;
                BigSweep = 50;
                MinBig = 100;
                MaxWait = 6;
                Lookback = 10;
                WickFrac = 0.5;
                CataPts = 30;
            }
            else if (State == State.Configure)
            {
                // ticky pro stavbu barů (primární série je jen nosič)
                AddDataSeries(BarsPeriodType.Tick, 1);
            }
            else if (State == State.DataLoaded)
            {
                tickSize = Instrument.MasterInstrument.TickSize;
                rangePts = RangeTicks * tickSize;
            }
        }

        protected override void OnMarketData(MarketDataEventArgs e)
        {
            if (e.MarketDataType != MarketDataType.Last)
                return;

            DateTime t = e.Time;
            TimeSpan tod = TimeZoneInfo.ConvertTime(
                DateTime.SpecifyKind(t, DateTimeKind.Unspecified),
                Core.Globals.GeneralOptions.TimeZoneInfo, Eastern).TimeOfDay;

            // RTH only
            if (tod < new TimeSpan(9, 30, 0) || tod >= new TimeSpan(16, 0, 0))
                return;

            // time-stop otevřené pozice
            if (Position.MarketPosition != MarketPosition.Flat && tod >= flatTime)
            {
                if (Position.MarketPosition == MarketPosition.Long) ExitLong("TS", sigName);
                else ExitShort("TS", sigName);
            }

            // agresor z bid/ask (Databento 'side' ekvivalent)
            int side = e.Price >= e.Ask ? 1 : (e.Price <= e.Bid ? -1 : 0);

            // sweep hranice: nový čas nebo strana -> uzavřít předchozí
            if (t != swTime || side != swSide)
            {
                FlushSweep();
                swTime = t; swSide = side;
            }
            swSize += e.Volume;

            if (cur == null)
                cur = new RangeBar { Open = e.Price, High = e.Price, Low = e.Price };

            cur.High = Math.Max(cur.High, e.Price);
            cur.Low = Math.Min(cur.Low, e.Price);
            cur.Close = e.Price;
            cur.Volume += e.Volume;
            cur.Delta += side * e.Volume;
            long lv; cur.Levels.TryGetValue(e.Price, out lv);
            cur.Levels[e.Price] = lv + e.Volume;

            if (cur.High - cur.Low >= rangePts - 1e-9)
            {
                FlushSweep();
                OnRangeBarClose(cur, tod);
                bars.Add(cur);
                if (bars.Count > 200) bars.RemoveAt(0);
                cur = null;
            }
        }

        private void FlushSweep()
        {
            if (swSize >= BigSweep && cur != null)
            {
                if (swSide == 1) cur.BigBuy += swSize;
                else if (swSide == -1) cur.BigSell += swSize;
            }
            swSize = 0;
        }

        private void OnRangeBarClose(RangeBar b, TimeSpan tod)
        {
            double rng = b.High - b.Low;

            // 1) agrese proti čekajícím setupům (vstup jen flat, před time-stopem)
            if (Position.MarketPosition == MarketPosition.Flat && tod < flatTime && rng > 0)
            {
                long bodyVol = b.BodyVol();
                foreach (var s in setups)
                {
                    int d = s.Direction;
                    bool aggr = b.Delta * d >= AggrDelta * Math.Max(b.Volume, 1)
                                && (b.Close - b.Open) * d > 0
                                && bodyVol > BodyFrac * Math.Max(b.Volume, 1);
                    double risk = (b.Close - s.Stop) * d;   // kladné jen se stopem na správné straně
                    bool intact = d == 1 ? b.Low > s.Stop : b.High < s.Stop;
                    if (aggr && intact && risk > 0 && risk <= MaxRiskPts)
                    {
                        double target = b.Close + d * risk * Rrr;
                        // unikátní signál pro každý obchod (recyklace OCO ID hází chyby)
                        sigName = (d == 1 ? "AbsL" : "AbsS") + (++tradeNo);
                        // simulovaný stop: NT ho drží lokálně a při dotyku pošle market
                        // -> žádné rejecty, když cena proskočí stop dřív než vstup
                        SetStopLoss(sigName, CalculationMode.Price, s.Stop, true);
                        SetProfitTarget(sigName, CalculationMode.Price, target);
                        cataPrice = s.Stop - d * CataPts;
                        if (d == 1) EnterLong(Contracts, sigName);
                        else EnterShort(Contracts, sigName);
                        setups.Clear();
                        break;
                    }
                }
            }

            // 2) odpočet setupů; proražení zóny setup ruší
            for (int i = setups.Count - 1; i >= 0; i--)
            {
                setups[i].BarsLeft--;
                bool broken = setups[i].Direction == 1 ? b.Low <= setups[i].Stop
                                                       : b.High >= setups[i].Stop;
                if (setups[i].BarsLeft <= 0 || broken)
                    setups.RemoveAt(i);
            }

            // 3) nový absorpční setup?
            if (bars.Count < Lookback || rng <= 0)
                return;

            for (int d = 1; d >= -1; d -= 2)
            {
                double extLo = double.MaxValue, extHi = double.MinValue;
                for (int i = bars.Count - Lookback; i < bars.Count; i++)
                {
                    extLo = Math.Min(extLo, bars[i].Low);
                    extHi = Math.Max(extHi, bars[i].High);
                }
                bool extreme = d == 1 ? b.Low <= extLo : b.High >= extHi;
                if (!extreme) continue;

                long bigAgainst = d == 1 ? b.BigSell : b.BigBuy;
                if (bigAgainst < MinBig) continue;

                bool deltaAgainst = b.Delta * d < 0;
                bool closedWith = (b.Close - b.Open) * d > 0;
                double wick = d == 1 ? Math.Min(b.Open, b.Close) - b.Low
                                     : b.High - Math.Max(b.Open, b.Close);
                bool closeBeyond = d == 1 ? b.Close >= b.Low + wick
                                          : b.Close <= b.High - wick;

                bool divergence = closedWith && deltaAgainst;
                bool wickAbsorb = wick >= WickFrac * rng && deltaAgainst && closeBeyond;

                if (divergence || wickAbsorb)
                {
                    double stop = d == 1 ? b.Low - tickSize : b.High + tickSize;
                    setups.Add(new Setup { Direction = d, Stop = stop, BarsLeft = MaxWait });
                }
            }
        }

        // pojistný BURZOVNÍ stop-market (ne simulovaný): normální stop drží NT
        // lokálně, takže při pádu NT/VPS by pozice zůstala nekrytá. Pokládá se
        // až po fillu vstupu; při zavření pozice ho NT sám zruší.
        protected override void OnPositionUpdate(Cbi.Position position, double averagePrice,
                                                 int quantity, MarketPosition marketPosition)
        {
            if (marketPosition == MarketPosition.Long)
                ExitLongStopMarket(0, true, quantity, cataPrice, "Cata", sigName);
            else if (marketPosition == MarketPosition.Short)
                ExitShortStopMarket(0, true, quantity, cataPrice, "Cata", sigName);
        }

        protected override void OnBarUpdate() { /* logika běží v OnMarketData */ }
    }
}
