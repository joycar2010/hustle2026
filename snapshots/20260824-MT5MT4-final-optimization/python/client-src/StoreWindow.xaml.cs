using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using QhClient.Services;

namespace QhClient;

public sealed class ProductItem
{
    public string Key { get; set; } = "";
    public string Name { get; set; } = "";
    public string Descr { get; set; } = "";
    public string Price { get; set; } = "";
    public string Unit { get; set; } = "USDT";
    public string Dur { get; set; } = "";
}

public partial class StoreWindow : Window
{
    private readonly ApiClient _api;

    public StoreWindow(ApiClient api)
    {
        InitializeComponent();
        _api = api;
        Loaded += async (_, _) => { await LoadWalletAsync(); await LoadCatalogAsync(); };
    }

    private async Task LoadWalletAsync()
    {
        var (bal, _) = await _api.WalletAsync();
        BalTxt.Text = bal.ToString("0.00");
    }

    private async Task LoadCatalogAsync()
    {
        var cat = await _api.CatalogAsync();
        var list = new List<ProductItem>();
        if (cat is { } c && c.TryGetProperty("products", out var arr) && arr.ValueKind == JsonValueKind.Array)
        {
            foreach (var p in arr.EnumerateArray())
            {
                int dur = p.TryGetProperty("duration_days", out var dd) && dd.ValueKind == JsonValueKind.Number ? dd.GetInt32() : 0;
                list.Add(new ProductItem
                {
                    Key = GetS(p, "key"),
                    Name = GetS(p, "name"),
                    Descr = GetS(p, "descr"),
                    Price = p.TryGetProperty("price", out var pr) && pr.ValueKind == JsonValueKind.Number ? pr.GetDouble().ToString("0.##") : "0",
                    Unit = GetS(p, "unit", "USDT"),
                    Dur = dur > 0 ? dur + "天" : "永久",
                });
            }
        }
        Products.ItemsSource = list;
    }

    private async void Buy_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.Tag is not string key) return;
        var dlg = new PayWindow(_api, "iap", key, 0) { Owner = this };
        if (dlg.ShowDialog() == true) { await LoadWalletAsync(); }
    }

    private async void Recharge_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new PayWindow(_api, "recharge", "", 0) { Owner = this };
        if (dlg.ShowDialog() == true) { await LoadWalletAsync(); }
    }

    private static string GetS(JsonElement e, string k, string def = "")
        => e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? (v.GetString() ?? def) : def;
}
