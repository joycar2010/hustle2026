using System.Text.Json;
using System.Windows;
using QhClient.Services;

namespace QhClient;

public partial class ConfigWindow : Window
{
    private readonly ApiClient _api;

    public ConfigWindow(ApiClient api)
    {
        InitializeComponent();
        _api = api;
        Loaded += async (_, _) => await LoadAsync();
    }

    private async Task LoadAsync()
    {
        var p = await _api.GetParamsAsync();
        if (p is null) { Msg.Text = "未取到参数模板"; return; }
        var e = p.Value;
        Symbol.Text = GetS(e, "symbol", "XAUUSD");
        HedgeSymbol.Text = GetS(e, "hedge_symbol", "");
        EntrySpread.Text = GetN(e, "entry_spread");
        TpPoints.Text = GetN(e, "tp_points");
        SlPoints.Text = GetN(e, "sl_points");
        Ladders.Text = GetN(e, "ladders");
        HoldSecs.Text = GetN(e, "hold_secs");
        EntryInterval.Text = GetN(e, "entry_interval_sec");
        MainLotMult.Text = GetN(e, "main_lot_mult");
        HedgeLotMult.Text = GetN(e, "hedge_lot_mult");
        MainSpreadCap.Text = GetN(e, "main_spread_cap");
        HedgeSpreadCap.Text = GetN(e, "hedge_spread_cap");
        SlippageTol.Text = GetN(e, "slippage_tol");
        MaxInflight.Text = GetN(e, "max_inflight");
        WeekendGuard.IsChecked = GetB(e, "weekend_guard");
        SingleLegAlert.IsChecked = GetB(e, "single_leg_alert");
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        var tok = TokenPrompt.Ask(this);
        if (tok == null) return;
        var body = new
        {
            username = _api.Username,
            license_key = _api.LicenseKey,
            symbol = Symbol.Text.Trim(),
            hedge_symbol = HedgeSymbol.Text.Trim(),
            entry_spread = D(EntrySpread.Text),
            tp_points = D(TpPoints.Text),
            sl_points = D(SlPoints.Text),
            ladders = (int)D(Ladders.Text),
            hold_secs = (int)D(HoldSecs.Text),
            entry_interval_sec = (int)D(EntryInterval.Text),
            main_lot_mult = D(MainLotMult.Text),
            hedge_lot_mult = D(HedgeLotMult.Text),
            main_spread_cap = D(MainSpreadCap.Text),
            hedge_spread_cap = D(HedgeSpreadCap.Text),
            slippage_tol = D(SlippageTol.Text),
            max_inflight = (int)D(MaxInflight.Text),
            weekend_guard = WeekendGuard.IsChecked == true,
            single_leg_alert = SingleLegAlert.IsChecked == true,
        };
        Msg.Text = "保存中…";
        var (ok, msg, authFail) = await _api.SaveParamsAsync(tok, body);
        if (authFail) CredStore.ClearAdminToken();
        if (ok) { MessageBox.Show("参数已保存,引擎将热重载", "成功", MessageBoxButton.OK, MessageBoxImage.Information); DialogResult = true; Close(); }
        else Msg.Text = "失败: " + msg;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) { DialogResult = false; Close(); }

    private static string GetS(JsonElement e, string k, string def) => e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? (v.GetString() ?? def) : def;
    private static string GetN(JsonElement e, string k) => e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble().ToString("0.###") : "0";
    private static bool GetB(JsonElement e, string k) => e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.True;
    private static double D(string s) => double.TryParse(s, out var d) ? d : 0;
}
