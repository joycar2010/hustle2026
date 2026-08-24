using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using QhClient.Services;
using WinForms = System.Windows.Forms;

namespace QhClient;

public partial class MainWindow : Window
{
    private readonly MainViewModel _vm = new();
    private readonly WsClient _ws;
    private readonly ApiClient _api;
    private readonly DispatcherTimer _chartTimer = new() { Interval = TimeSpan.FromSeconds(15) };
    private WinForms.NotifyIcon? _tray;
    private string _lastAlertShown = "";

    public MainWindow(ApiClient api, VerifyResult login)
    {
        InitializeComponent();
        _api = api;
        _vm.Username = login.Username ?? "";
        _vm.Plan = login.Plan ?? "";
        _vm.Expire = (login.ExpireAt ?? "").Length >= 10 ? login.ExpireAt![..10] : (login.ExpireAt ?? "");
        DataContext = _vm;

        SetupTray();

        _ws = new WsClient(api.LicenseKey ?? "");
        _ws.OnConnectionChanged += conn => Dispatcher.Invoke(() =>
        {
            _vm.Connected = conn;
            _vm.ConnStatus = conn ? "实时已连接" : "断线重连中…";
        });
        _ws.OnSnapshot += snap => Dispatcher.Invoke(() =>
        {
            _vm.Apply(snap);
            // 新告警 → 托盘气泡(仅 warn/err 已在后端过滤, 这里去重)
            if (!string.IsNullOrEmpty(_vm.LastAlert) && _vm.LastAlert != _lastAlertShown)
            {
                _lastAlertShown = _vm.LastAlert;
                _tray?.ShowBalloonTip(4000, "Quant Hedge 告警", _vm.LastAlert, WinForms.ToolTipIcon.Warning);
            }
        });
        _ws.Start();

        _chartTimer.Tick += async (_, _) => await RefreshChartAsync();
        Loaded += async (_, _) => { await RefreshChartAsync(); _chartTimer.Start(); };
        Closed += (_, _) => { _ws.Stop(); _chartTimer.Stop(); _tray?.Dispose(); };
    }

    private void SetupTray()
    {
        _tray = new WinForms.NotifyIcon
        {
            Icon = System.Drawing.SystemIcons.Information,
            Visible = true,
            Text = "Quant Hedge 交易终端",
        };
        _tray.DoubleClick += (_, _) => { Show(); WindowState = WindowState.Normal; Activate(); };
        var menu = new WinForms.ContextMenuStrip();
        menu.Items.Add("显示主界面", null, (_, _) => { Show(); WindowState = WindowState.Normal; Activate(); });
        menu.Items.Add("退出程序", null, (_, _) => Application.Current.Shutdown());
        _tray.ContextMenuStrip = menu;
    }

    private async Task RefreshChartAsync()
    {
        var pts = await _api.SpreadChartAsync(5);
        if (pts.Count == 0) return;
        var xs = Enumerable.Range(0, pts.Count).Select(i => (double)i).ToArray();
        var fs = pts.Select(p => p.Fs).ToArray();
        var rs = pts.Select(p => p.Rs).ToArray();
        var plot = SpreadPlot.Plot;
        plot.Clear();
        var sFwd = plot.Add.Scatter(xs, fs); sFwd.LegendText = "正向点差"; sFwd.MarkerSize = 0; sFwd.LineWidth = 2;
        var sRev = plot.Add.Scatter(xs, rs); sRev.LegendText = "反向点差"; sRev.MarkerSize = 0; sRev.LineWidth = 2;
        plot.Axes.AutoScale();
        plot.ShowLegend();
        // 深色主题
        plot.FigureBackground.Color = ScottPlot.Color.FromHex("#111A2E");
        plot.DataBackground.Color = ScottPlot.Color.FromHex("#0B1220");
        plot.Axes.Color(ScottPlot.Color.FromHex("#7C8B9E"));
        SpreadPlot.Refresh();
    }

    // ---- 自动控制 ----
    private string? EnsureAdminToken() => TokenPrompt.Ask(this);

    private async void ApplyEntry_Click(object sender, RoutedEventArgs e)
    {
        var mode = (AeMode.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "off";
        var dir = (AeDir.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "reverse";
        if ((mode == "armed" || mode == "full") &&
            MessageBox.Show($"确认将自动进场设为「{mode}」?\n武装/全量为真金自动开仓,请确认已知晓风险。",
                "真金操作确认", MessageBoxButton.OKCancel, MessageBoxImage.Warning) != MessageBoxResult.OK)
            return;
        var tok = EnsureAdminToken(); if (tok == null) return;
        var (ok, msg, authFail) = await _api.SetAutoEntryAsync(tok, mode, dir);
        if (authFail) CredStore.ClearAdminToken();
        MessageBox.Show(ok ? $"自动进场已设为 {mode}/{dir}" : "失败: " + msg, "自动进场",
            MessageBoxButton.OK, ok ? MessageBoxImage.Information : MessageBoxImage.Error);
    }

    private async void ApplyExit_Click(object sender, RoutedEventArgs e)
    {
        var mode = (AxMode.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "off";
        if ((mode == "armed" || mode == "full") &&
            MessageBox.Show($"确认将自动出场设为「{mode}」?\n武装/全量为真金自动平仓,请确认已知晓风险。",
                "真金操作确认", MessageBoxButton.OKCancel, MessageBoxImage.Warning) != MessageBoxResult.OK)
            return;
        var tok = EnsureAdminToken(); if (tok == null) return;
        var (ok, msg, authFail) = await _api.SetAutoExitAsync(tok, mode, AxProfitFirst.IsChecked == true);
        if (authFail) CredStore.ClearAdminToken();
        MessageBox.Show(ok ? $"自动出场已设为 {mode}" : "失败: " + msg, "自动出场",
            MessageBoxButton.OK, ok ? MessageBoxImage.Information : MessageBoxImage.Error);
    }

    private void Config_Click(object sender, RoutedEventArgs e)
        => new ConfigWindow(_api) { Owner = this }.ShowDialog();

    private void Store_Click(object sender, RoutedEventArgs e)
        => new StoreWindow(_api) { Owner = this }.ShowDialog();

    private void Arb_Click(object sender, RoutedEventArgs e)
        => new ArbWindow(_api, _vm.AiArbUnlocked) { Owner = this }.ShowDialog();

    private void Logout_Click(object sender, RoutedEventArgs e)
    {
        _ws.Stop(); _chartTimer.Stop();
        CredStore.Clear();
        var shell = new WebShellWindow("");
        Application.Current.MainWindow = shell;
        shell.Show();
        Close();
    }
}
