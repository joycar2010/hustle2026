using System.Windows;
using QhClient.Services;

namespace QhClient;

public partial class PayWindow : Window
{
    private readonly ApiClient _api;
    private readonly string _kind;         // iap / recharge / subscription
    private readonly string _productKey;
    private readonly int _months;
    private double _amount;                 // iap/subscription 固定; recharge 由输入

    public PayWindow(ApiClient api, string kind, string productKey, int months, double subAmount = 0)
    {
        InitializeComponent();
        _api = api; _kind = kind; _productKey = productKey; _months = months; _amount = subAmount;
        Loaded += async (_, _) => await InitAsync();
    }

    private async Task InitAsync()
    {
        TitleTxt.Text = _kind switch { "recharge" => "账户充值", "subscription" => "包月续费", _ => "内购支付" };
        if (_kind == "recharge")
        {
            AmountBox.Visibility = Visibility.Visible;
            PmBalance.IsEnabled = false;   // 充值不支持余额支付
            ExtraK.Text = "类型"; ExtraV.Text = "余额充值";
            AmountInput.TextChanged += (_, _) => UpdateAmt();
        }
        else if (_kind == "iap")
        {
            var cat = await _api.CatalogAsync();
            if (cat is { } c && c.TryGetProperty("products", out var arr))
                foreach (var p in arr.EnumerateArray())
                    if (p.TryGetProperty("key", out var k) && k.GetString() == _productKey)
                    {
                        _amount = p.TryGetProperty("price", out var pr) ? pr.GetDouble() : 0;
                        ExtraK.Text = "商品"; ExtraV.Text = p.TryGetProperty("name", out var nm) ? nm.GetString() ?? "" : "";
                    }
        }
        else { ExtraK.Text = "时长"; ExtraV.Text = _months + " 个月"; }
        AddrTxt.Text = await _api.PayAddressAsync() is { Length: > 0 } a ? a : "(后台未配置收款地址)";
        UpdateAmt();
    }

    private void UpdateAmt()
    {
        if (_kind == "recharge") _amount = double.TryParse(AmountInput.Text, out var d) ? d : 0;
        AmtLabel.Text = _amount.ToString("0.00") + " USDT";
        BalanceHint.Text = $"将从账户余额扣除 {_amount:0.00} USDT,即时生效。";
    }

    private void Pm_Changed(object sender, RoutedEventArgs e)
    {
        bool onchain = PmOnchain.IsChecked == true;
        if (OnchainBox != null) OnchainBox.Visibility = onchain ? Visibility.Visible : Visibility.Collapsed;
        if (BalanceHint != null) BalanceHint.Visibility = onchain ? Visibility.Collapsed : Visibility.Visible;
        if (SubmitBtn != null) SubmitBtn.Content = onchain ? "我已转账·提交" : "余额支付";
    }

    private async void Submit_Click(object sender, RoutedEventArgs e)
    {
        string pm = PmOnchain.IsChecked == true ? "onchain" : "balance";
        if (_kind == "recharge" && _amount <= 0) { Msg.Text = "请输入充值金额"; return; }
        string hash = HashInput.Text.Trim();
        SubmitBtn.IsEnabled = false; Msg.Text = "提交中…";
        var (ok, msg) = await _api.OrderSubmitAsync(_kind, _productKey, _months, _amount, pm, hash);
        if (ok)
        {
            MessageBox.Show(pm == "balance" ? "余额支付成功" : "已提交,待财务核对到账(演示环境即时生效)",
                "成功", MessageBoxButton.OK, MessageBoxImage.Information);
            DialogResult = true; Close();
        }
        else { Msg.Text = msg; SubmitBtn.IsEnabled = true; }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) { DialogResult = false; Close(); }
}
