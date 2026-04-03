package trading

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"hustle-go/internal/db"
)

const (
	PlatformBinance = 1
	PlatformBybit   = 2
)

// AccountCreds holds exchange credentials loaded from DB.
type AccountCreds struct {
	AccountID  string
	PlatformID int
	APIKey     string
	APISecret  string
	IsMT5      bool
}

var exClient = &http.Client{Timeout: 15 * time.Second}

// loadCredsByPlatform returns first active account for user matching platformID.
func loadCredsByPlatform(ctx context.Context, userID string, platformID int) (*AccountCreds, error) {
	c := &AccountCreds{}
	err := db.Pool().QueryRow(ctx,
		`SELECT account_id::text, platform_id, api_key, api_secret, is_mt5_account
		 FROM accounts
		 WHERE user_id=$1::uuid AND platform_id=$2 AND is_active=true
		 LIMIT 1`,
		userID, platformID,
	).Scan(&c.AccountID, &c.PlatformID, &c.APIKey, &c.APISecret, &c.IsMT5)
	return c, err
}

// loadAllCreds returns all active accounts for user.
func loadAllCreds(ctx context.Context, userID string) ([]*AccountCreds, error) {
	rows, err := db.Pool().Query(ctx,
		`SELECT account_id::text, platform_id, api_key, api_secret, is_mt5_account
		 FROM accounts WHERE user_id=$1::uuid AND is_active=true`,
		userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []*AccountCreds
	for rows.Next() {
		c := &AccountCreds{}
		rows.Scan(&c.AccountID, &c.PlatformID, &c.APIKey, &c.APISecret, &c.IsMT5)
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
	resp, err := exClient.Do(req)
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
	if u := os.Getenv("MT5_SERVICE_URL"); u != "" { return u }
	return "http://127.0.0.1:8001"
}

func callMT5(ctx context.Context, method, path string, jsonBody []byte) ([]byte, int, error) {
	target := mt5BaseURL() + path
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
	if k := os.Getenv("MT5_API_KEY"); k != "" {
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
