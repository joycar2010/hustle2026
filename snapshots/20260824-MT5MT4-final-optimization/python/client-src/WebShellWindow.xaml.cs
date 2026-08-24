using System.Windows;
using Microsoft.Web.WebView2.Core;
using QhClient.Services;
using WinForms = System.Windows.Forms;

namespace QhClient;

// 混合外壳: WebView2 内嵌真实 dashboard(视觉/迭代一致性),原生外壳提供托盘/免重登/告警可靠性。
// 登录统一走 web 自己的登录页(唯一登录入口, 无原生登录框); 有存密钥则注入自动登录, 无则显 web 登录并在成功后捕获密钥存 DPAPI。
public partial class WebShellWindow : Window
{
    private string _license;                  // 可空: 空=走 web 登录页
    private WsClient? _ws;
    private WinForms.NotifyIcon? _tray;
    private string _lastAlert = "";
    private bool _autoLoggedIn;

    public WebShellWindow(string license = "")
    {
        InitializeComponent();
        _license = license ?? "";
        SetupTray();
        Loaded += async (_, _) => { RegisterGlobalHotkey(); await InitWebAsync(); };
        Closed += (_, _) => { try { UnregisterHotKey(_hwnd, HOTKEY_ID); } catch { } _ws?.Stop(); _tray?.Dispose(); Web?.Dispose(); };
    }

    private async Task InitWebAsync()
    {
        try
        {
            // 用户数据目录放 LocalAppData(避免 Program Files 权限问题 + 单文件解压场景)
            var udf = System.IO.Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "QuantHedge", "WebView2");
            System.IO.Directory.CreateDirectory(udf);
            var env = await CoreWebView2Environment.CreateAsync(null, udf);
            await Web.EnsureCoreWebView2Async(env);

            var s = Web.CoreWebView2.Settings;
            s.AreDefaultContextMenusEnabled = false;   // 收口①: 关 Chromium 右键(不盖 web 自己的右键菜单)
            s.AreBrowserAcceleratorKeysEnabled = false; // 禁 F5/Ctrl+P 等浏览器快捷键
            s.IsZoomControlEnabled = false;             // 禁 Ctrl+滚轮缩放(保持像素一致)
            s.IsStatusBarEnabled = false;

            // 收口: 有存密钥才注入 localStorage.qh_key(供 web 自助流程 + 自动登录复用)
            if (!string.IsNullOrEmpty(_license))
                await Web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                    $"try{{localStorage.setItem('qh_key','{JsEscape(_license)}');}}catch(e){{}}");

            Web.CoreWebView2.ProcessFailed += OnProcessFailed;         // 收口③
            Web.CoreWebView2.NavigationCompleted += OnNavCompleted;    // 收口②+④+自动登录

            // logo 离线兜底: 拦截登录页 logo 请求, 返回内嵌资源字节(断网也显示)
            Web.CoreWebView2.AddWebResourceRequestedFilter("*QHEDGELOGO-mid.png*", CoreWebView2WebResourceContext.Image);
            Web.CoreWebView2.WebResourceRequested += OnLogoRequested;

            Web.CoreWebView2.Navigate(ApiClient.BaseUrl + "/dashboard");
        }
        catch (Exception e)
        {
            ShowOverlay("初始化失败: " + e.Message, retry: true);
        }
    }

    private async void OnNavCompleted(object? sender, CoreWebView2NavigationCompletedEventArgs e)
    {
        if (!e.IsSuccess)
        {
            ShowOverlay("无法连接交易服务器,请检查网络", retry: true);   // 收口④
            return;
        }
        ApplyZoom();   // 首帧即按窗宽缩放, 避免小屏挤压
        if (_autoLoggedIn) { HideOverlay(); return; }
        _autoLoggedIn = true;

        if (!string.IsNullOrEmpty(_license))
        {
            // 有存密钥 → 遮罩下自动登录(web 登录页永不露脸), 成功才撤遮罩
            var js = @"(function(){try{
                var lg=document.getElementById('login');
                if(lg && lg.style.display!=='none'){
                  var k=document.getElementById('lg-key'); if(k)k.value=localStorage.getItem('qh_key')||'';
                  if(typeof doLogin==='function')doLogin();
                }
            }catch(e){}})();";
            try { await Web.CoreWebView2.ExecuteScriptAsync(js); } catch { }
            await WaitLoginDoneThenReveal(captureKey: false);
        }
        else
        {
            // 无存密钥 → 直接显 web 登录页(唯一登录入口), 用户登录成功后捕获密钥存 DPAPI
            HideOverlay();
            _ = WaitLoginDoneThenReveal(captureKey: true);
        }
    }

    // 轮询 web 登录成功(#login 隐藏)。captureKey=true 时登录成功后从 localStorage 抓 qh_key 存 DPAPI 并启 WS。
    private async Task WaitLoginDoneThenReveal(bool captureKey)
    {
        int max = captureKey ? int.MaxValue : 40;   // 自动登录 8s 超时; 手动登录一直等
        for (int i = 0; i < max; i++)
        {
            if (!IsLoaded) return;
            try
            {
                var r = await Web.CoreWebView2.ExecuteScriptAsync(
                    "(function(){var l=document.getElementById('login');return (!l||l.style.display==='none')?'1':'0';})()");
                if (r != null && r.Contains('1'))
                {
                    HideOverlay();
                    if (captureKey)
                    {
                        var kr = await Web.CoreWebView2.ExecuteScriptAsync("localStorage.getItem('qh_key')");
                        var key = (kr ?? "").Trim('"');
                        if (!string.IsNullOrEmpty(key) && key != "null")
                        {
                            _license = key; CredStore.SaveLicense(key);
                        }
                    }
                    StartWs();
                    return;
                }
            }
            catch { }
            await Task.Delay(captureKey ? 800 : 200);
        }
        // 自动登录超时(密钥失效/过期): 撤遮罩露出 web 登录页, 切到手动捕获
        HideOverlay();
        _ = WaitLoginDoneThenReveal(captureKey: true);
    }

    private void StartWs()
    {
        if (_ws != null || string.IsNullOrEmpty(_license)) return;
        _ws = new WsClient(_license);
        _ws.OnSnapshot += snap => Dispatcher.Invoke(() => OnSnapshot(snap));
        _ws.Start();
    }

    // 按窗口宽度等比缩放, 保证 dashboard(设计宽~1280)在小屏不挤压/不横向滚
    private const double DesignWidth = 1280.0;
    private void ApplyZoom()
    {
        try
        {
            if (Web?.CoreWebView2 == null) return;
            double avail = Web.ActualWidth > 0 ? Web.ActualWidth : ActualWidth;
            if (avail <= 0) return;
            double z = Math.Min(1.0, Math.Max(0.6, avail / DesignWidth));   // 0.6~1.0 之间
            Web.ZoomFactor = z;
        }
        catch { }
    }
    private void Window_SizeChanged(object sender, SizeChangedEventArgs e) => ApplyZoom();

    private void OnProcessFailed(object? sender, CoreWebView2ProcessFailedEventArgs e)
    {
        // 收口③: 渲染进程崩溃 → 自动 Reload + 原生"重连中"覆盖层
        Dispatcher.Invoke(() =>
        {
            ShowOverlay("交易终端已重连…", retry: false);
            _autoLoggedIn = false;
            try { Web.CoreWebView2?.Reload(); } catch { }
        });
    }

    private void Retry_Click(object sender, RoutedEventArgs e)
    {
        ShowOverlay("正在重连…", retry: false);
        _autoLoggedIn = false;
        try { Web.CoreWebView2?.Navigate(ApiClient.BaseUrl + "/dashboard"); } catch { }
    }

    private void ShowOverlay(string msg, bool retry)
    {
        Overlay.Visibility = Visibility.Visible;
        OverlayMsg.Text = msg;
        OverlayBar.Visibility = retry ? Visibility.Collapsed : Visibility.Visible;
        RetryBtn.Visibility = retry ? Visibility.Visible : Visibility.Collapsed;
    }
    private void HideOverlay() => Overlay.Visibility = Visibility.Collapsed;

    // logo 离线兜底: 命中登录页 logo 请求 → 返回内嵌资源字节
    private static byte[]? _logoBytes;
    private void OnLogoRequested(object? sender, CoreWebView2WebResourceRequestedEventArgs e)
    {
        try
        {
            _logoBytes ??= ReadEmbedded("QhClient.logo-mid.png");
            if (_logoBytes == null) return;   // 取不到就放行走网络
            var ms = new System.IO.MemoryStream(_logoBytes);
            var resp = Web.CoreWebView2.Environment.CreateWebResourceResponse(
                ms, 200, "OK", "Content-Type: image/png");
            e.Response = resp;
        }
        catch { }
    }
    private static byte[]? ReadEmbedded(string name)
    {
        try
        {
            var asm = System.Reflection.Assembly.GetExecutingAssembly();
            using var s = asm.GetManifestResourceStream(name);
            if (s == null) return null;
            using var ms = new System.IO.MemoryStream();
            s.CopyTo(ms); return ms.ToArray();
        }
        catch { return null; }
    }

    // ---- 托盘告警(独立 WS 驱动, 不靠 web) ----
    private void OnSnapshot(Snapshot s)
    {
        try
        {
            var ud = s.UserData;
            if (ud.ValueKind == System.Text.Json.JsonValueKind.Object &&
                ud.TryGetProperty("alerts", out var al) &&
                al.ValueKind == System.Text.Json.JsonValueKind.Array && al.GetArrayLength() > 0)
            {
                var first = al[0];
                var msg = first.TryGetProperty("msg", out var m) ? m.GetString() ?? "" : "";
                if (!string.IsNullOrEmpty(msg) && msg != _lastAlert)
                {
                    _lastAlert = msg;
                    _tray?.ShowBalloonTip(4000, "Quant Hedge 告警", msg, WinForms.ToolTipIcon.Warning);
                }
            }
        }
        catch { }
    }

    private void SetupTray()
    {
        _tray = new WinForms.NotifyIcon
        {
            Icon = LoadAppIcon(),
            Visible = true,
            Text = "Quant Hedge 交易终端",
        };
        _tray.DoubleClick += (_, _) => ShowMain();
        var menu = new WinForms.ContextMenuStrip();
        menu.Items.Add("显示主界面", null, (_, _) => ShowMain());
        _autostartItem = new WinForms.ToolStripMenuItem("开机自启动", null, (_, _) => ToggleAutostart())
        { Checked = IsAutostartEnabled(), CheckOnClick = false };
        menu.Items.Add(_autostartItem);
        menu.Items.Add(new WinForms.ToolStripSeparator());
        menu.Items.Add("退出登录", null, (_, _) => { CredStore.Clear(); RestartToLogin(); });
        menu.Items.Add("退出程序", null, (_, _) => { _reallyExit = true; Application.Current.Shutdown(); });
        _tray.ContextMenuStrip = menu;
    }

    private void ShowMain() { Show(); WindowState = WindowState.Normal; Activate(); }

    // 托盘图标: 从当前 exe 提取自带 app.ico(与窗口/任务栏一致), 失败回落系统图标
    private static System.Drawing.Icon LoadAppIcon()
    {
        try
        {
            var exe = Environment.ProcessPath;
            if (!string.IsNullOrEmpty(exe))
            {
                var ic = System.Drawing.Icon.ExtractAssociatedIcon(exe);
                if (ic != null) return ic;
            }
        }
        catch { }
        return System.Drawing.SystemIcons.Application;
    }

    // ---- 关闭→最小化到托盘(交易终端常驻, 告警不断) ----
    private bool _reallyExit;
    protected override void OnClosing(System.ComponentModel.CancelEventArgs e)
    {
        if (!_reallyExit)
        {
            e.Cancel = true;
            Hide();
            _tray?.ShowBalloonTip(2000, "Quant Hedge", "已最小化到托盘,仍在接收实时告警。双击图标恢复。", WinForms.ToolTipIcon.Info);
            return;
        }
        base.OnClosing(e);
    }

    // ---- 开机自启(注册表 HKCU\...\Run) ----
    private WinForms.ToolStripMenuItem? _autostartItem;
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string RunValue = "QuantHedge";
    private static bool IsAutostartEnabled()
    {
        try { using var k = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(RunKey); return k?.GetValue(RunValue) != null; }
        catch { return false; }
    }
    private void ToggleAutostart()
    {
        try
        {
            using var k = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(RunKey, writable: true)
                          ?? Microsoft.Win32.Registry.CurrentUser.CreateSubKey(RunKey);
            if (IsAutostartEnabled()) { k!.DeleteValue(RunValue, false); if (_autostartItem != null) _autostartItem.Checked = false; }
            else
            {
                var exe = Environment.ProcessPath ?? System.Diagnostics.Process.GetCurrentProcess().MainModule?.FileName;
                if (!string.IsNullOrEmpty(exe)) { k!.SetValue(RunValue, "\"" + exe + "\""); if (_autostartItem != null) _autostartItem.Checked = true; }
            }
        }
        catch (Exception ex) { _tray?.ShowBalloonTip(3000, "开机自启", "设置失败: " + ex.Message, WinForms.ToolTipIcon.Error); }
    }

    // ---- 全局快捷键 Ctrl+Alt+Q 显/隐主窗 ----
    [System.Runtime.InteropServices.DllImport("user32.dll")] private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);
    [System.Runtime.InteropServices.DllImport("user32.dll")] private static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    private const int HOTKEY_ID = 0xB01D;
    private const uint MOD_CONTROL = 0x2, MOD_ALT = 0x1;
    private const uint VK_Q = 0x51, WM_HOTKEY = 0x0312;
    private IntPtr _hwnd;
    private void RegisterGlobalHotkey()
    {
        try
        {
            var helper = new System.Windows.Interop.WindowInteropHelper(this);
            _hwnd = helper.Handle;
            var src = System.Windows.Interop.HwndSource.FromHwnd(_hwnd);
            src?.AddHook(HwndHook);
            RegisterHotKey(_hwnd, HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_Q);
        }
        catch { }
    }
    private IntPtr HwndHook(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg == WM_HOTKEY && wParam.ToInt32() == HOTKEY_ID)
        {
            if (IsVisible && WindowState != WindowState.Minimized) Hide();
            else ShowMain();
            handled = true;
        }
        return IntPtr.Zero;
    }

    private void RestartToLogin()
    {
        _ws?.Stop();
        // 清凭证 + 清 web 会话, 重开空壳 → 显 web 登录页(唯一登录入口)
        try { CredStore.Clear(); Web.CoreWebView2?.ExecuteScriptAsync("try{localStorage.removeItem('qh_key')}catch(e){}"); } catch { }
        try { UnregisterHotKey(_hwnd, HOTKEY_ID); } catch { }
        _tray?.Dispose();
        var shell = new WebShellWindow("");
        Application.Current.MainWindow = shell;
        shell.Show();
        _reallyExit = true;   // 放行本窗真正关闭(否则被 OnClosing 拦成隐藏)
        Close();
    }

    private static string JsEscape(string s) => (s ?? "").Replace("\\", "\\\\").Replace("'", "\\'");
}
