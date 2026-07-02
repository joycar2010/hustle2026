using System.Collections.ObjectModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;

namespace QhClient;

// 配对成交历史一行
public sealed class PairRow
{
    public string Time { get; set; } = "";
    public string Direction { get; set; } = "";
    public string Spread { get; set; } = "";
    public string Profit { get; set; } = "";
    public bool Up { get; set; }
}
// 单腿成交一行
public sealed class DealRow
{
    public string Time { get; set; } = "";
    public string Side { get; set; } = "";
    public string Lots { get; set; } = "";
    public string Price { get; set; } = "";
    public string Profit { get; set; } = "";
}

// 一条腿(主/对冲)账户卡
public partial class LegVm : ObservableObject
{
    [ObservableProperty] private string _title = "";
    [ObservableProperty] private string _platform = "--";
    [ObservableProperty] private string _login = "--";
    [ObservableProperty] private string _balance = "--";
    [ObservableProperty] private string _equity = "--";
    [ObservableProperty] private string _conn = "--";
    [ObservableProperty] private bool _connected;
    [ObservableProperty] private string _server = "--";
    [ObservableProperty] private double _pnl;
    [ObservableProperty] private string _ask = "--";
    [ObservableProperty] private string _bid = "--";
}

public partial class MainViewModel : ObservableObject
{
    // 顶栏
    [ObservableProperty] private string _username = "";
    [ObservableProperty] private string _plan = "";
    [ObservableProperty] private string _expire = "";
    [ObservableProperty] private bool _demo;
    [ObservableProperty] private string _connStatus = "连接中…";
    [ObservableProperty] private bool _connected;

    // 双腿
    public LegVm Main { get; } = new() { Title = "主账户 (MT5)" };
    public LegVm Hedge { get; } = new() { Title = "对冲账户 (MT5)" };

    // 综合
    [ObservableProperty] private double _totalProfit;
    [ObservableProperty] private double _revSpread;   // 反向开仓点差 = 对冲ASK - 主BID
    [ObservableProperty] private double _fwdSpread;   // 正向开仓点差 = 主ASK - 对冲BID
    [ObservableProperty] private string _marketState = "--";
    [ObservableProperty] private int _pairCount;
    [ObservableProperty] private string _autoEntry = "off";
    [ObservableProperty] private string _autoExit = "off";
    [ObservableProperty] private string _lastAlert = "";
    [ObservableProperty] private bool _aiArbUnlocked;

    // 历史表(WS slow 驱动)
    public ObservableCollection<PairRow> Pairs { get; } = new();
    public ObservableCollection<DealRow> MainDeals { get; } = new();
    public ObservableCollection<DealRow> HedgeDeals { get; } = new();

    // ---- 从快照更新 ----
    public void Apply(Services.Snapshot s)
    {
        var f = s.Fast;
        // legs
        if (TryProp(f, "legs", out var legs) && TryProp(legs, "status", out var st))
        {
            if (TryProp(st, "main", out var m)) FillLeg(Main, m);
            if (TryProp(st, "hedge", out var h)) FillLeg(Hedge, h);
        }
        // account profit (主)
        if (TryProp(f, "account", out var acc) && acc.ValueKind == JsonValueKind.Object)
            Main.Pnl = GetNum(acc, "profit");
        // ticks
        if (TryProp(f, "tick_main", out var tm) && tm.ValueKind == JsonValueKind.Object)
        { Main.Ask = Fmt(GetNum(tm, "ask")); Main.Bid = Fmt(GetNum(tm, "bid")); }
        if (TryProp(f, "tick_hedge", out var th) && th.ValueKind == JsonValueKind.Object)
        { Hedge.Ask = Fmt(GetNum(th, "ask")); Hedge.Bid = Fmt(GetNum(th, "bid")); }
        // engine state
        if (TryProp(f, "state", out var state) && state.ValueKind == JsonValueKind.Object)
        {
            if (TryProp(state, "cycle", out var cyc) && cyc.ValueKind == JsonValueKind.Object)
                PairCount = (int)GetNum(cyc, "pairs");
            if (TryProp(state, "market", out var mk) && mk.ValueKind == JsonValueKind.Object)
                MarketState = (mk.TryGetProperty("closed", out var cl) && cl.ValueKind == JsonValueKind.True) ? "休市" : "运行";
        }
        // 综合盈亏 = 主+对冲净值浮盈(用 equity-balance 近似, 精确值走持仓汇总)
        // 开仓点差
        double mBid = ParseD(Main.Bid), mAsk = ParseD(Main.Ask), hBid = ParseD(Hedge.Bid), hAsk = ParseD(Hedge.Ask);
        if (mBid > 0 && hAsk > 0) RevSpread = Math.Round(hAsk - mBid, 2);
        if (mAsk > 0 && hBid > 0) FwdSpread = Math.Round(mAsk - hBid, 2);
        TotalProfit = Math.Round(Main.Pnl + Hedge.Pnl, 2);

        // user_data
        var ud = s.UserData;
        if (ud.ValueKind == JsonValueKind.Object)
        {
            if (ud.TryGetProperty("auto_entry", out var ae)) AutoEntry = ae.GetString() ?? "off";
            if (ud.TryGetProperty("auto_exit", out var ax)) AutoExit = ax.GetString() ?? "off";
            if (ud.TryGetProperty("force_demo", out var fd)) Demo = fd.ValueKind == JsonValueKind.True;
            if (ud.TryGetProperty("entitlements", out var ent) && ent.ValueKind == JsonValueKind.Object)
            {
                if (ent.TryGetProperty("ai_arb", out var aa))
                    AiArbUnlocked = (aa.ValueKind == JsonValueKind.True) ||
                        (aa.ValueKind == JsonValueKind.String && (aa.GetString() ?? "").ToLower() is "true" or "1");
            }
            if (ud.TryGetProperty("alerts", out var al) && al.ValueKind == JsonValueKind.Array && al.GetArrayLength() > 0)
            {
                var first = al[0];
                LastAlert = (first.TryGetProperty("msg", out var mm) ? mm.GetString() : "") ?? "";
            }
        }

        // ---- slow: 配对历史 + 两腿成交 ----
        var sl = s.Slow;
        if (sl.ValueKind == JsonValueKind.Object)
        {
            if (TryProp(sl, "paired", out var pd) && TryProp(pd, "pairs", out var parr) && parr.ValueKind == JsonValueKind.Array)
            {
                Pairs.Clear();
                foreach (var p in parr.EnumerateArray())
                {
                    double prof = GetNum(p, "profit");
                    Pairs.Add(new PairRow
                    {
                        Time = ShortTime(GetStr(p, "closed_at", GetStr(p, "opened_at", ""))),
                        Direction = GetStr(p, "direction", "-") == "forward" ? "正向" : "反向",
                        Spread = Fmt(GetNum(p, "spread")),
                        Profit = prof.ToString("0.00"), Up = prof >= 0
                    });
                    if (Pairs.Count >= 50) break;
                }
            }
            FillDeals(MainDeals, sl, "deals_main");
            FillDeals(HedgeDeals, sl, "deals_hedge");
        }
    }

    private static void FillDeals(ObservableCollection<DealRow> col, JsonElement sl, string key)
    {
        if (!(sl.TryGetProperty(key, out var dd) && dd.TryGetProperty("deals", out var arr) && arr.ValueKind == JsonValueKind.Array)) return;
        col.Clear();
        foreach (var d in arr.EnumerateArray())
        {
            col.Add(new DealRow
            {
                Time = ShortTime(GetStr(d, "time", GetStr(d, "dealt_at", ""))),
                Side = GetStr(d, "side", GetStr(d, "type", "-")),
                Lots = Fmt(GetNum(d, "lots")),
                Price = Fmt(GetNum(d, "price")),
                Profit = GetNum(d, "profit").ToString("0.00"),
            });
            if (col.Count >= 50) break;
        }
    }
    private static string ShortTime(string iso)
        => string.IsNullOrEmpty(iso) ? "-" : (iso.Length >= 19 ? iso[5..19].Replace("T", " ") : iso);

    private static void FillLeg(LegVm vm, JsonElement a)
    {
        if (a.ValueKind != JsonValueKind.Object) return;
        vm.Platform = GetStr(a, "platform", "MT5");
        vm.Login = GetStr(a, "account", "--");
        vm.Balance = Fmt(GetNum(a, "balance"));
        vm.Equity = Fmt(GetNum(a, "equity"));
        vm.Connected = a.TryGetProperty("connected", out var c) && c.ValueKind == JsonValueKind.True;
        vm.Conn = vm.Connected ? "链接成功" : "断开";
        vm.Server = GetStr(a, "server", "--");
        vm.Pnl = Math.Round(GetNum(a, "equity") - GetNum(a, "balance"), 2);
    }

    // ---- JSON helpers ----
    private static bool TryProp(JsonElement e, string name, out JsonElement v)
    {
        if (e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out v)) return true;
        v = default; return false;
    }
    private static double GetNum(JsonElement e, string name)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : 0;
    private static string GetStr(JsonElement e, string name, string def)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? (v.GetString() ?? def) : def;
    private static string Fmt(double d) => d == 0 ? "--" : d.ToString("0.00");
    private static double ParseD(string s) => double.TryParse(s, out var d) ? d : 0;
}
