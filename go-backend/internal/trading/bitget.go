package trading

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type BitgetCreds struct {
	APIKey     string
	Secret     string
	Passphrase string
}

func bitgetSign(secret, timestamp, method, path, body string) string {
	prehash := timestamp + strings.ToUpper(method) + path + body
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(prehash))
	return base64.StdEncoding.EncodeToString(mac.Sum(nil))
}

func callBitget(ctx context.Context, creds *BitgetCreds, method, path string, jsonBody []byte) ([]byte, int, error) {
	ts := fmt.Sprintf("%d", time.Now().UnixMilli())
	bodyStr := ""
	if len(jsonBody) > 0 {
		bodyStr = string(jsonBody)
	}
	sig := bitgetSign(creds.Secret, ts, method, path, bodyStr)

	target := "https://api.bitget.com" + path
	var bodyReader io.Reader
	if len(jsonBody) > 0 {
		bodyReader = strings.NewReader(bodyStr)
	}

	req, err := http.NewRequestWithContext(ctx, method, target, bodyReader)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("ACCESS-KEY", creds.APIKey)
	req.Header.Set("ACCESS-SIGN", sig)
	req.Header.Set("ACCESS-TIMESTAMP", ts)
	req.Header.Set("ACCESS-PASSPHRASE", creds.Passphrase)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("locale", "en-US")

	resp, err := exClient.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("Bitget unreachable: %w", err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return b, resp.StatusCode, nil
}

func PlaceBitgetOrder(ctx context.Context, creds *BitgetCreds, symbol, side, orderType, size, price string) ([]byte, int, error) {
	body := map[string]interface{}{
		"symbol":      symbol,
		"productType": "USDT-FUTURES",
		"marginMode":  "crossed",
		"marginCoin":  "USDT",
		"side":        side,
		"orderType":   orderType,
		"size":        size,
	}
	if price != "" && orderType != "market" {
		body["price"] = price
	}
	jsonBody, _ := json.Marshal(body)
	return callBitget(ctx, creds, http.MethodPost, "/api/v2/mix/order/place-order", jsonBody)
}

func CancelBitgetOrder(ctx context.Context, creds *BitgetCreds, symbol, orderId string) ([]byte, int, error) {
	body, _ := json.Marshal(map[string]string{
		"symbol":      symbol,
		"productType": "USDT-FUTURES",
		"orderId":     orderId,
	})
	return callBitget(ctx, creds, http.MethodPost, "/api/v2/mix/order/cancel-order", body)
}

func GetBitgetPositions(ctx context.Context, creds *BitgetCreds, productType string) ([]byte, int, error) {
	if productType == "" {
		productType = "USDT-FUTURES"
	}
	return callBitget(ctx, creds, http.MethodGet, "/api/v2/mix/position/all-position?productType="+productType, nil)
}

func CancelAllBitgetOrders(ctx context.Context, creds *BitgetCreds, symbol string) ([]byte, int, error) {
	body, _ := json.Marshal(map[string]string{
		"symbol":      symbol,
		"productType": "USDT-FUTURES",
		"marginCoin":  "USDT",
	})
	return callBitget(ctx, creds, http.MethodPost, "/api/v2/mix/order/cancel-all-orders", body)
}
