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

type OKXCreds struct {
	APIKey     string
	Secret     string
	Passphrase string
	Proxy      string
}

func okxSign(secret, timestamp, method, path, body string) string {
	prehash := timestamp + method + path + body
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(prehash))
	return base64.StdEncoding.EncodeToString(mac.Sum(nil))
}

func callOKX(ctx context.Context, creds *OKXCreds, method, path string, jsonBody []byte) ([]byte, int, error) {
	ts := time.Now().UTC().Format("2006-01-02T15:04:05.000Z")
	bodyStr := ""
	if len(jsonBody) > 0 {
		bodyStr = string(jsonBody)
	}
	sig := okxSign(creds.Secret, ts, method, path, bodyStr)

	target := "https://www.okx.com" + path
	var bodyReader io.Reader
	if len(jsonBody) > 0 {
		bodyReader = strings.NewReader(bodyStr)
	}

	req, err := http.NewRequestWithContext(ctx, method, target, bodyReader)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("OK-ACCESS-KEY", creds.APIKey)
	req.Header.Set("OK-ACCESS-SIGN", sig)
	req.Header.Set("OK-ACCESS-TIMESTAMP", ts)
	req.Header.Set("OK-ACCESS-PASSPHRASE", creds.Passphrase)
	req.Header.Set("Content-Type", "application/json")

	client := exClient
	resp, err := client.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("OKX unreachable: %w", err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return b, resp.StatusCode, nil
}

func PlaceOKXOrder(ctx context.Context, creds *OKXCreds, instId, side, ordType, sz, px string) ([]byte, int, error) {
	body := map[string]interface{}{
		"instId":  instId,
		"tdMode":  "cross",
		"side":    side,
		"ordType": ordType,
		"sz":      sz,
	}
	if px != "" && ordType != "market" {
		body["px"] = px
	}
	jsonBody, _ := json.Marshal(body)
	return callOKX(ctx, creds, http.MethodPost, "/api/v5/trade/order", jsonBody)
}

func CancelOKXOrder(ctx context.Context, creds *OKXCreds, instId, ordId string) ([]byte, int, error) {
	body, _ := json.Marshal(map[string]string{"instId": instId, "ordId": ordId})
	return callOKX(ctx, creds, http.MethodPost, "/api/v5/trade/cancel-order", body)
}

func GetOKXPositions(ctx context.Context, creds *OKXCreds) ([]byte, int, error) {
	return callOKX(ctx, creds, http.MethodGet, "/api/v5/account/positions", nil)
}

func GetOKXAccountBalance(ctx context.Context, creds *OKXCreds) ([]byte, int, error) {
	return callOKX(ctx, creds, http.MethodGet, "/api/v5/account/balance", nil)
}

func CancelAllOKXOrders(ctx context.Context, creds *OKXCreds, instId string) ([]byte, int, error) {
	body, _ := json.Marshal(map[string]string{"instId": instId})
	return callOKX(ctx, creds, http.MethodPost, "/api/v5/trade/cancel-batch-orders", body)
}
