using System.Net.WebSockets;
using System.Text;
using System.Text.Json;

namespace QhClient.Services;

// 实时快照(后端 _ws_broadcaster 推送)。用 JsonDocument 弹性解析, 不强建全量模型。
public sealed class Snapshot
{
    public JsonElement Fast { get; init; }
    public JsonElement Slow { get; init; }
    public JsonElement UserData { get; init; }
    public long Ts { get; init; }
    public static Snapshot? Parse(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.TryGetProperty("type", out var t) && t.GetString() != "snapshot") return null;
            return new Snapshot
            {
                // Clone: JsonDocument 释放后仍可读
                Fast = root.TryGetProperty("fast", out var f) ? f.Clone() : default,
                Slow = root.TryGetProperty("slow", out var s) ? s.Clone() : default,
                UserData = root.TryGetProperty("user_data", out var u) ? u.Clone() : default,
                Ts = root.TryGetProperty("ts", out var ts) && ts.ValueKind == JsonValueKind.Number ? ts.GetInt64() : 0,
            };
        }
        catch { return null; }
    }
}

// WS 客户端: 连接→认证→持续收快照。断线自动重连(3s)。UI 线程外触发事件, 调用方负责 marshaling。
public sealed class WsClient
{
    public static string WsUrl = "wss://qh.hustle2026.xyz/ws/stream";
    private readonly string _licenseKey;
    private ClientWebSocket? _ws;
    private CancellationTokenSource? _cts;

    public event Action<Snapshot>? OnSnapshot;
    public event Action<bool>? OnConnectionChanged;   // true=已连 false=断开

    public WsClient(string licenseKey) => _licenseKey = licenseKey;

    public void Start()
    {
        _cts = new CancellationTokenSource();
        _ = RunLoopAsync(_cts.Token);
    }
    public void Stop()
    {
        _cts?.Cancel();
        try { _ws?.Abort(); } catch { }
    }

    private async Task RunLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                _ws = new ClientWebSocket();
                await _ws.ConnectAsync(new Uri(WsUrl), ct);
                // 首帧认证
                var auth = JsonSerializer.Serialize(new { license_key = _licenseKey });
                await _ws.SendAsync(Encoding.UTF8.GetBytes(auth), WebSocketMessageType.Text, true, ct);
                OnConnectionChanged?.Invoke(true);
                await ReceiveLoopAsync(_ws, ct);
            }
            catch (OperationCanceledException) { break; }
            catch { /* 落到重连 */ }
            OnConnectionChanged?.Invoke(false);
            try { await Task.Delay(3000, ct); } catch { break; }
        }
    }

    private async Task ReceiveLoopAsync(ClientWebSocket ws, CancellationToken ct)
    {
        var buf = new byte[1 << 16];
        var sb = new StringBuilder();
        while (!ct.IsCancellationRequested && ws.State == WebSocketState.Open)
        {
            sb.Clear();
            WebSocketReceiveResult res;
            do
            {
                res = await ws.ReceiveAsync(new ArraySegment<byte>(buf), ct);
                if (res.MessageType == WebSocketMessageType.Close)
                {
                    await ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "", ct);
                    return;
                }
                sb.Append(Encoding.UTF8.GetString(buf, 0, res.Count));
            } while (!res.EndOfMessage);

            var text = sb.ToString();
            if (text.Contains("\"ping\"")) continue;   // 心跳
            var snap = Snapshot.Parse(text);
            if (snap != null) OnSnapshot?.Invoke(snap);
        }
    }
}
