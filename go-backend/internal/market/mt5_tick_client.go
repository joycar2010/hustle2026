package market

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"hustle-go/internal/mt5config"
)

type MT5Tick struct {
	Symbol  string  `json:"symbol"`
	Bid     float64 `json:"bid"`
	Ask     float64 `json:"ask"`
	Last    float64 `json:"last"`
	Volume  int64   `json:"volume"`
	Time    int64   `json:"time"`
	TimeMsc int64   `json:"time_msc"`
}

func GetMT5TickFromBridge(symbol, bridgeURL string) (*BybitTicker, error) {
	if bridgeURL == "" {
		return nil, fmt.Errorf("MT5 bridge URL not configured for symbol %s", symbol)
	}
	apiKey := mt5config.BridgeAPIKey()
	url := fmt.Sprintf("%s/mt5/tick/%s", bridgeURL, symbol)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-API-Key", apiKey)
	req.Header.Set("X-Api-Key", apiKey)

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("MT5 Bridge unreachable: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("MT5 Bridge returned %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var tick MT5Tick
	if err := json.Unmarshal(body, &tick); err != nil {
		return nil, err
	}

	if tick.Bid == 0 || tick.Ask == 0 {
		return nil, fmt.Errorf("MT5 tick invalid: bid=%f ask=%f", tick.Bid, tick.Ask)
	}

	return &BybitTicker{Bid: tick.Bid, Ask: tick.Ask, Ts: time.Now().UnixMilli()}, nil
}
