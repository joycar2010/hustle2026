package trading

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"hustle-go/internal/db"
	"hustle-go/internal/mt5config"
)

const (
	PlatformBinance = 1
	PlatformBybit   = 2
	PlatformOKX     = 5
	PlatformBitget  = 6
)

// AccountCreds holds exchange credentials loaded from DB.
type AccountCreds struct {
	AccountID   string
	PlatformID  int
	APIKey      string
	APISecret   string
	IsMT5       bool
	Passphrase  string
	ProxyConfig []byte // raw JSONB bytes from accounts.proxy_config; may be nil
}

// proxyConfig matches the JSON structure stored in accounts.proxy_config.
type proxyConfig struct {
	Host      string `json:"host"`
	Port      int    `json:"port"`
	Username  string `json:"username"`
	Password  string `json:"password"`
	ProxyType string `json:"proxy_type"`
}

var exClient = &http.Client{Timeout: 15 * time.Second}

// proxyClientCache caches per-proxy http.Client instances so we don't rebuild a Transport per request.
var (
	proxyClientCache   = map[string]*http.Client{}
	proxyClientCacheMu sync.RWMutex
)

// httpClientFor returns an http.Client that routes through creds.ProxyConfig if present, else the default exClient.
// Falls back to direct connection on any parse/transport error so a malformed proxy never silently breaks trading.
func httpClientFor(creds *AccountCreds) *http.Client {
	if creds == nil || len(creds.ProxyConfig) == 0 {
		return exClient
	}
	var pc proxyConfig
	if err := json.Unmarshal(creds.ProxyConfig, &pc); err != nil || pc.Host == "" || pc.Port == 0 {
		return exClient
	}
	// Match Python proxy_utils.build_proxy_url: HTTP-style proxies always use "http://" scheme
	// (even for HTTPS targets — Go's http.ProxyURL handles CONNECT tunneling).
	// Only socks5/socks4 keep their original scheme.
	scheme := strings.ToLower(strings.TrimSpace(pc.ProxyType))
	switch scheme {
	case "", "http", "https":
		scheme = "http"
	}
	// httpx-style URL with embedded credentials
	var proxyStr string
	if pc.Username != "" {
		proxyStr = fmt.Sprintf("%s://%s:%s@%s:%d", scheme, pc.Username, pc.Password, pc.Host, pc.Port)
	} else {
		proxyStr = fmt.Sprintf("%s://%s:%d", scheme, pc.Host, pc.Port)
	}

	proxyClientCacheMu.RLock()
	if cached, ok := proxyClientCache[proxyStr]; ok {
		proxyClientCacheMu.RUnlock()
		return cached
	}
	proxyClientCacheMu.RUnlock()

	proxyURL, err := url.Parse(proxyStr)
	if err != nil {
		return exClient
	}
	transport := &http.Transport{
		Proxy:               http.ProxyURL(proxyURL),
		MaxIdleConns:        20,
		IdleConnTimeout:     60 * time.Second,
		TLSHandshakeTimeout: 10 * time.Second,
	}
	client := &http.Client{Transport: transport, Timeout: 15 * time.Second}

	proxyClientCacheMu.Lock()
	proxyClientCache[proxyStr] = client
	proxyClientCacheMu.Unlock()
	return client
}

// loadCredsByPlatform returns first active account for user matching platformID.
func loadCredsByPlatform(ctx context.Context, userID string, platformID int) (*AccountCreds, error) {
	c := &AccountCreds{}
	var pcRaw []byte
	err := db.Pool().QueryRow(ctx,
		`SELECT account_id::text, platform_id, api_key, api_secret, is_mt5_account, COALESCE(passphrase,''), COALESCE(proxy_config::text, '')
		 FROM accounts
		 WHERE user_id=$1::uuid AND platform_id=$2 AND is_active=true
		 LIMIT 1`,
		userID, platformID,
	).Scan(&c.AccountID, &c.PlatformID, &c.APIKey, &c.APISecret, &c.IsMT5, &c.Passphrase, &pcRaw)
	if len(pcRaw) > 0 && string(pcRaw) != "" {
		c.ProxyConfig = pcRaw
	}
	return c, err
}

// loadAllCreds returns all active accounts for user.
func loadAllCreds(ctx context.Context, userID string) ([]*AccountCreds, error) {
	rows, err := db.Pool().Query(ctx,
		`SELECT account_id::text, platform_id, api_key, api_secret, is_mt5_account, COALESCE(passphrase,''), COALESCE(proxy_config::text, '')
		 FROM accounts WHERE user_id=$1::uuid AND is_active=true`,
		userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []*AccountCreds
	for rows.Next() {
		c := &AccountCreds{}
		var pcRaw []byte
		rows.Scan(&c.AccountID, &c.PlatformID, &c.APIKey, &c.APISecret, &c.IsMT5, &c.Passphrase, &pcRaw)
		if len(pcRaw) > 0 && string(pcRaw) != "" {
			c.ProxyConfig = pcRaw
		}
		out = append(out, c)
	}
	return out, nil
}

// Binance Futures

const binanceFutBase = "https://fapi.binance.com"

func bnSign(secret, payload string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(payload))
	return hex.EncodeToString(mac.Sum(nil))
}

func binanceDo(ctx context.Context, method, path string, params url.Values, creds *AccountCreds) ([]byte, int, error) {
	params.Set("timestamp", strconv.FormatInt(time.Now().UnixMilli(), 10))
	params.Set("recvWindow", "5000")
	qs := params.Encode()
	qs += "&signature=" + bnSign(creds.APISecret, qs)

	target := binanceFutBase + path + "?" + qs
	var body io.Reader
	if method == http.MethodPost {
		body = strings.NewReader("")
	}
	req, err := http.NewRequestWithContext(ctx, method, target, body)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("X-MBX-APIKEY", creds.APIKey)
	if method == http.MethodPost {
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	resp, err := httpClientFor(creds).Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return b, resp.StatusCode, nil
}

func PlaceBinanceOrder(ctx context.Context, creds *AccountCreds, symbol, side, orderType, positionSide, quantity, price string) ([]byte, int, error) {
	p := url.Values{}
	p.Set("symbol", symbol)
	p.Set("side", strings.ToUpper(side))
	p.Set("type", strings.ToUpper(orderType))
	p.Set("quantity", quantity)
	if positionSide != "" {
		p.Set("positionSide", strings.ToUpper(positionSide))
	}
	if strings.ToUpper(orderType) == "LIMIT" {
		p.Set("price", price)
		p.Set("timeInForce", "GTX")
	}
	return binanceDo(ctx, http.MethodPost, "/fapi/v1/order", p, creds)
}

func GetBinancePositions(ctx context.Context, creds *AccountCreds, symbol string) ([]byte, int, error) {
	p := url.Values{}
	if symbol != "" {
		p.Set("symbol", symbol)
	}
	return binanceDo(ctx, http.MethodGet, "/fapi/v2/positionRisk", p, creds)
}

func GetBinanceOpenOrders(ctx context.Context, creds *AccountCreds, symbol string) ([]byte, int, error) {
	p := url.Values{}
	if symbol != "" {
		p.Set("symbol", symbol)
	}
	return binanceDo(ctx, http.MethodGet, "/fapi/v1/openOrders", p, creds)
}

func CancelAllBinanceOrders(ctx context.Context, creds *AccountCreds, symbol string) ([]byte, int, error) {
	p := url.Values{}
	p.Set("symbol", symbol)
	return binanceDo(ctx, http.MethodDelete, "/fapi/v1/allOpenOrders", p, creds)
}

func GetBinanceUserTrades(ctx context.Context, creds *AccountCreds, symbol string, startTime, endTime int64, limit int) ([]byte, int, error) {
	p := url.Values{}
	p.Set("symbol", symbol)
	if startTime > 0 {
		p.Set("startTime", strconv.FormatInt(startTime, 10))
	}
	if endTime > 0 {
		p.Set("endTime", strconv.FormatInt(endTime, 10))
	}
	p.Set("limit", strconv.Itoa(limit))
	return binanceDo(ctx, http.MethodGet, "/fapi/v1/userTrades", p, creds)
}

func GetBinanceIncome(ctx context.Context, creds *AccountCreds, symbol, incomeType string, startTime, endTime int64) ([]byte, int, error) {
	p := url.Values{}
	p.Set("symbol", symbol)
	p.Set("incomeType", incomeType)
	if startTime > 0 {
		p.Set("startTime", strconv.FormatInt(startTime, 10))
	}
	if endTime > 0 {
		p.Set("endTime", strconv.FormatInt(endTime, 10))
	}
	p.Set("limit", "1000")
	return binanceDo(ctx, http.MethodGet, "/fapi/v1/income", p, creds)
}

// MT5 microservice

func mt5BaseURL() string {
	if u := os.Getenv("MT5_SERVICE_URL"); u != "" {
		return u
	}
	bridges := mt5config.GetSystemBridges()
	if u, ok := bridges[2]; ok {
		return u
	}
	for _, u := range bridges {
		return u
	}
	return "http://127.0.0.1:8001"
}

func callMT5(ctx context.Context, method, path string, jsonBody []byte) ([]byte, int, error) {
	target := mt5BaseURL() + path
	// MT5 Bridge requires JSON body even when all fields are optional (Pydantic model required by default).
	// Default nil/empty to {} so /mt5/position/close-all and /mt5/cancel-all work without explicit caller body.
	if method == http.MethodPost && len(jsonBody) == 0 {
		jsonBody = []byte("{}")
	}
	var body io.Reader
	if len(jsonBody) > 0 {
		body = strings.NewReader(string(jsonBody))
	}
	req, err := http.NewRequestWithContext(ctx, method, target, body)
	if err != nil {
		return nil, 0, err
	}
	if len(jsonBody) > 0 {
		req.Header.Set("Content-Type", "application/json")
	}
	k := os.Getenv("MT5_API_KEY")
	if k == "" { k = mt5config.BridgeAPIKey() }
	if k != "" {
		req.Header.Set("X-Api-Key", k)
	}
	resp, err := exClient.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("MT5 service unreachable: %w", err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return b, resp.StatusCode, nil
}

func FormatPrice(f float64) string { return fmt.Sprintf("%.2f", f) }
func FormatQty(f float64) string   { return fmt.Sprintf("%.2f", f) }

// PlaceBinanceMakerQueueOrder submits a LIMIT order using Binance Futures'
// native priceMatch=QUEUE feature. The exchange atomically snaps the price to
// the best bid (BUY) or best ask (SELL) at the moment the order enters the
// matching engine — no client-side price calculation, no race condition, and
// no spread-crossing risk. Combined with timeInForce=GTX (Post-Only), the
// order is guaranteed to rest in the book as a MAKER or be rejected outright.
//
// Binance priceMatch values:
//   NONE        — default; requires explicit price parameter
//   OPPONENT    — opposing-side BBO → instant TAKER
//   OPPONENT_5/10/20 — 5/10/20 ticks into the opposite side
//   QUEUE       — own-side BBO → instant MAKER (best bid for BUY / best ask for SELL)
//   QUEUE_5/10/20    — 5/10/20 ticks behind own-side BBO
//
// When priceMatch is set, the "price" parameter MUST NOT be sent.
//
// Use this for all manual trading buttons where we want a MAKER order to rest
// in the book regardless of current quote snapshot (user clicked 平仓 / 开仓 and
// doesn't require immediate fill).
func PlaceBinanceMakerQueueOrder(
	ctx context.Context,
	creds *AccountCreds,
	symbol, side, positionSide, quantity string,
) ([]byte, int, error) {
	// In Binance hedge mode (dual-position), open vs close is determined entirely by
	// the side + positionSide combination:
	//   BUY  + LONG  → open long
	//   SELL + LONG  → close long
	//   SELL + SHORT → open short
	//   BUY  + SHORT → close short
	// The reduceOnly flag is REJECTED by the API for hedge-mode accounts
	// (code -1106 "Parameter 'reduceonly' sent when not required.").
	p := url.Values{}
	p.Set("symbol", symbol)
	p.Set("side", strings.ToUpper(side))
	p.Set("type", "LIMIT")
	p.Set("quantity", quantity)
	if positionSide != "" {
		p.Set("positionSide", strings.ToUpper(positionSide))
	}
	p.Set("priceMatch", "QUEUE") // native MAKER at own-side BBO
	p.Set("timeInForce", "GTX")  // Post-Only enforcement
	return binanceDo(ctx, http.MethodPost, "/fapi/v1/order", p, creds)
}
