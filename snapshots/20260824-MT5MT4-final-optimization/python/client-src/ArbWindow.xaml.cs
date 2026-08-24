using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using QhClient.Services;

namespace QhClient;

public sealed class ArbRow
{
    public string MainSym { get; set; } = "";
    public string HedgeSym { get; set; } = "";
    public string MainPrice { get; set; } = "--";
    public string HedgePrice { get; set; } = "--";
    public string Basis { get; set; } = "--";
    public string Entry { get; set; } = "--";
    public int Score { get; set; }
    public string Suggest { get; set; } = "";
    public Brush ScoreColor { get; set; } = Brushes.Gray;
}

public partial class ArbWindow : Window
{
    private readonly ApiClient _api;
    private readonly bool _unlocked;

    public ArbWindow(ApiClient api, bool unlocked)
    {
        InitializeComponent();
        _api = api; _unlocked = unlocked;
        Loaded += async (_, _) => await LoadAsync();
    }

    private async Task LoadAsync()
    {
        if (!_unlocked)
        {
            LockedBox.Visibility = Visibility.Visible;
            SummaryBox.Visibility = Visibility.Collapsed;
            return;
        }
        var r = await _api.ArbScanAsync();
        if (r is not { } d) { Verdict.Text = "分析获取失败"; return; }
        if (d.TryGetProperty("summary", out var s))
        {
            Verdict.Text = s.TryGetProperty("verdict", out var v) ? v.GetString() : "";
            SumPairs.Text = "产品对: " + GetI(s, "pairs");
            SumReach.Text = "可套利: " + GetI(s, "reachable");
            SumTop.Text = "最高评分: " + GetI(s, "top_score");
        }
        var list = new List<ArbRow>();
        if (d.TryGetProperty("pairs", out var arr) && arr.ValueKind == JsonValueKind.Array)
        {
            foreach (var p in arr.EnumerateArray())
            {
                int score = GetI(p, "score");
                list.Add(new ArbRow
                {
                    MainSym = GetS(p, "main_symbol"),
                    HedgeSym = GetS(p, "hedge_symbol"),
                    MainPrice = NumOrDash(p, "main_price"),
                    HedgePrice = NumOrDash(p, "hedge_price"),
                    Basis = NumOrDash(p, "basis"),
                    Entry = GetN(p, "entry_spread"),
                    Score = score,
                    Suggest = GetS(p, "suggest"),
                    ScoreColor = score >= 100 ? Green : (score >= 80 ? Amber : Gray),
                });
            }
        }
        Pairs.ItemsSource = list;
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await LoadAsync();

    private static readonly Brush Green = new SolidColorBrush(Color.FromRgb(0x3F, 0xD0, 0x7F));
    private static readonly Brush Amber = new SolidColorBrush(Color.FromRgb(0xE6, 0xA2, 0x3C));
    private static readonly Brush Gray = new SolidColorBrush(Color.FromRgb(0x90, 0x93, 0x99));
    private static string GetS(JsonElement e, string k) => e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? (v.GetString() ?? "") : "";
    private static int GetI(JsonElement e, string k) => e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetInt32() : 0;
    private static string GetN(JsonElement e, string k) => e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble().ToString("0.####") : "--";
    private static string NumOrDash(JsonElement e, string k) => e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble().ToString("0.####") : "--";
}
