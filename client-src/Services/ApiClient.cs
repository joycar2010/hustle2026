using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace QhClient.Services;

// 后端返回的登录结果
public sealed class VerifyResult
{
    [JsonPropertyName("ok")] public bool Ok { get; set; }
    [JsonPropertyName("username")] public string? Username { get; set; }
    [JsonPropertyName("plan")] public string? Plan { get; set; }
    [JsonPropertyName("expire_at")] public string? ExpireAt { get; set; }
    [JsonPropertyName("expired")] public bool Expired { get; set; }
    [JsonPropertyName("feishu_id")] public string? FeishuId { get; set; }
}

// REST 客户端: 登录 verify + 自动进出场控制(需 admin token) + 点差图拉取。实时数据全走 WS。
public sealed partial class ApiClient
{
    public static string BaseUrl = "https://qh.hustle2026.xyz";
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(15) };

    public string? Username { get; private set; }
    public string? LicenseKey { get; private set; }

    // 返回 (成功?, 提示文案)。401=密钥无效 403=停用 到期=过期
    public async Task<(bool ok, string msg, VerifyResult? data)> VerifyAsync(string licenseKey)
    {
        try
        {
            var resp = await _http.PostAsJsonAsync($"{BaseUrl}/api/auth/verify",
                new { license_key = licenseKey });
            if (resp.StatusCode == System.Net.HttpStatusCode.Unauthorized)
                return (false, "密钥无效,请检查后重试", null);
            if (resp.StatusCode == System.Net.HttpStatusCode.Forbidden)
                return (false, "账户已停用/封禁,请联系客服", null);
            if (!resp.IsSuccessStatusCode)
                return (false, $"服务器错误 {(int)resp.StatusCode}", null);
            var r = await resp.Content.ReadFromJsonAsync<VerifyResult>();
            if (r is null) return (false, "响应解析失败", null);
            if (!r.Ok && r.Expired) return (false, "授权已过期,请续费", r);
            Username = r.Username; LicenseKey = licenseKey;
            return (true, "登录成功", r);
        }
        catch (Exception e)
        {
            return (false, "连接失败: " + e.Message, null);
        }
    }

    // ---- 点差走势(无鉴权) ----
    public async Task<List<SpreadPoint>> SpreadChartAsync(int interval = 5)
    {
        try
        {
            var pts = await _http.GetFromJsonAsync<List<SpreadPoint>>(
                $"{BaseUrl}/api/engine/spread_chart?interval={interval}");
            return pts ?? new();
        }
        catch { return new(); }
    }

    // ---- 自动进/出场控制(require_admin: X-Admin-Token + X-License) ----
    // 返回 (成功?, 提示)。403=令牌无效(调用方应清令牌重输)。
    public async Task<(bool ok, string msg, bool authFail)> SetAutoEntryAsync(string adminToken, string mode, string direction)
        => await AdminPostAsync(adminToken, "/api/cmd/auto_entry",
            new { username = Username, license_key = LicenseKey, mode, direction });

    public async Task<(bool ok, string msg, bool authFail)> SetAutoExitAsync(string adminToken, string mode, bool profitFirst)
        => await AdminPostAsync(adminToken, "/api/cmd/auto_exit",
            new { username = Username, license_key = LicenseKey, mode, profit_first = profitFirst });

    private async Task<(bool ok, string msg, bool authFail)> AdminPostAsync(string adminToken, string path, object body)
    {
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Post, $"{BaseUrl}{path}");
            req.Headers.Add("X-Admin-Token", adminToken);
            req.Headers.Add("X-License", LicenseKey ?? "");
            req.Content = JsonContent.Create(body);
            var resp = await _http.SendAsync(req);
            if (resp.StatusCode == System.Net.HttpStatusCode.Forbidden)
                return (false, "Admin Token 无效或无权限", true);
            var txt = await resp.Content.ReadAsStringAsync();
            if (!resp.IsSuccessStatusCode)
            {
                string detail = txt;
                try { using var d = JsonDocument.Parse(txt); if (d.RootElement.TryGetProperty("detail", out var de)) detail = de.GetString() ?? txt; } catch { }
                return (false, detail, false);
            }
            return (true, "已设置", false);
        }
        catch (Exception e) { return (false, "请求失败: " + e.Message, false); }
    }
}

public sealed class SpreadPoint
{
    [JsonPropertyName("t")] public string? T { get; set; }   // 裸 UTC ISO
    [JsonPropertyName("fs")] public double Fs { get; set; }  // 正向点差
    [JsonPropertyName("rs")] public double Rs { get; set; }  // 反向点差
}

// ---- P2: 参数 / 内购 / 钱包 / 套利 ----
public sealed partial class ApiClient
{
    private readonly HttpClient _http2 = new() { Timeout = TimeSpan.FromSeconds(15) };

    // 参数模板(取首个/指定 symbol)
    public async Task<JsonElement?> GetParamsAsync()
    {
        try
        {
            var doc = await _http2.GetFromJsonAsync<JsonElement>($"{BaseUrl}/api/params/{Username}");
            if (doc.TryGetProperty("params", out var arr) && arr.ValueKind == JsonValueKind.Array && arr.GetArrayLength() > 0)
                return arr[0].Clone();
            return null;
        }
        catch { return null; }
    }
    // 保存参数(require_admin)
    public async Task<(bool ok, string msg, bool authFail)> SaveParamsAsync(string adminToken, object body)
        => await AdminPostAsync(adminToken, "/api/params/save", body);

    // 内购目录(公开)
    public async Task<JsonElement?> CatalogAsync()
    {
        try { return (await _http2.GetFromJsonAsync<JsonElement>($"{BaseUrl}/api/iap/catalog")).Clone(); }
        catch { return null; }
    }
    // 钱包余额(公开只读)
    public async Task<(double balance, double totalRecharge)> WalletAsync()
    {
        try
        {
            var d = await _http2.GetFromJsonAsync<JsonElement>($"{BaseUrl}/api/user/wallet/{Username}");
            double b = d.TryGetProperty("balance", out var bb) ? bb.GetDouble() : 0;
            double t = d.TryGetProperty("total_recharge", out var tt) ? tt.GetDouble() : 0;
            return (b, t);
        }
        catch { return (0, 0); }
    }
    // 收款地址(公开)
    public async Task<string> PayAddressAsync()
    {
        try
        {
            var d = await _http2.GetFromJsonAsync<JsonElement>($"{BaseUrl}/api/pay/address");
            return d.TryGetProperty("trc20_address", out var a) ? (a.GetString() ?? "") : "";
        }
        catch { return ""; }
    }
    // 统一下单(公开: license 在 body 内; 后端按 license 认账户)
    public async Task<(bool ok, string msg)> OrderSubmitAsync(string kind, string productKey, int months, double amount, string payMethod, string txHash)
    {
        try
        {
            var body = new { license_key = LicenseKey, kind, product_key = productKey, months, amount, pay_method = payMethod, tx_hash = txHash };
            var resp = await _http2.PostAsJsonAsync($"{BaseUrl}/api/order/submit", body);
            var txt = await resp.Content.ReadAsStringAsync();
            if (!resp.IsSuccessStatusCode)
            {
                string detail = txt;
                try { using var dd = JsonDocument.Parse(txt); if (dd.RootElement.TryGetProperty("detail", out var de)) detail = de.GetString() ?? txt; } catch { }
                return (false, detail);
            }
            return (true, "下单成功");
        }
        catch (Exception e) { return (false, "请求失败: " + e.Message); }
    }
    // AI 套利扫描(公开)
    public async Task<JsonElement?> ArbScanAsync()
    {
        try { return (await _http2.GetFromJsonAsync<JsonElement>($"{BaseUrl}/api/engine/arb_scan/{Username}")).Clone(); }
        catch { return null; }
    }
}
