package market

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"sync"
	"time"
)

// GateTick holds a cached Gate.io futures ticker quote.
type GateTick struct {
	Bid float64
	Ask float64
	Ts  int64
}

type gateCacheEntry struct {
	tick GateTick
	ts   time.Time
}

var (
	gateCacheMu sync.RWMutex
	gateCache   = make(map[string]gateCacheEntry)
	// Gate public REST ticker endpoint (USDT-settled perpetual)
	gateTickerURL = "https://api.gateio.ws/api/v4/futures/usdt/tickers?contract=%s"
	gateHTTP      = &http.Client{Timeout: 4 * time.Second}
	gateCacheTTL  = 1 * time.Second
)

// GetGateTick returns the latest best bid/ask for a Gate USDT-perp contract.
// Cached 1 second to limit REST pressure (~60 req/min per symbol under the
// spread-push cadence and ad-hoc GetSpread calls).
func GetGateTick(symbol string) (GateTick, error) {
	// Cache read
	gateCacheMu.RLock()
	if e, ok := gateCache[symbol]; ok && time.Since(e.ts) < gateCacheTTL {
		gateCacheMu.RUnlock()
		return e.tick, nil
	}
	gateCacheMu.RUnlock()

	// REST fetch
	resp, err := gateHTTP.Get(fmt.Sprintf(gateTickerURL, symbol))
	if err != nil {
		return GateTick{}, fmt.Errorf("gate http: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return GateTick{}, fmt.Errorf("gate status %d: %s", resp.StatusCode, string(body))
	}

	// Gate returns an array, even for a single contract
	var arr []struct {
		Contract    string `json:"contract"`
		Last        string `json:"last"`
		HighestBid  string `json:"highest_bid"`
		LowestAsk   string `json:"lowest_ask"`
		MarkPrice   string `json:"mark_price"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&arr); err != nil {
		return GateTick{}, fmt.Errorf("gate decode: %w", err)
	}
	if len(arr) == 0 {
		return GateTick{}, fmt.Errorf("gate empty response for %s", symbol)
	}

	row := arr[0]
	bid, _ := strconv.ParseFloat(row.HighestBid, 64)
	ask, _ := strconv.ParseFloat(row.LowestAsk, 64)
	// Fallback: if bid/ask missing, approximate via mark_price ± 1 tick (very rare)
	if bid == 0 || ask == 0 {
		mp, _ := strconv.ParseFloat(row.MarkPrice, 64)
		if mp == 0 {
			mp, _ = strconv.ParseFloat(row.Last, 64)
		}
		if mp > 0 {
			if bid == 0 {
				bid = mp * 0.9999
			}
			if ask == 0 {
				ask = mp * 1.0001
			}
		}
	}

	t := GateTick{Bid: bid, Ask: ask, Ts: time.Now().UnixMilli()}
	gateCacheMu.Lock()
	gateCache[symbol] = gateCacheEntry{tick: t, ts: time.Now()}
	gateCacheMu.Unlock()
	return t, nil
}
