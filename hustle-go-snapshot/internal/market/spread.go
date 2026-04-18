package market

import (
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/pairs"
)

// SpreadData is the arbitrage spread payload
type SpreadData struct {
	PairCode     string `json:"pair_code,omitempty"`
	BinanceQuote struct {
		Symbol string  `json:"symbol"`
		Bid    float64 `json:"bid_price"`
		Ask    float64 `json:"ask_price"`
		Ts     int64   `json:"timestamp"`
	} `json:"binance_quote"`
	BybitQuote struct {
		Symbol string  `json:"symbol"`
		Bid    float64 `json:"bid_price"`
		Ask    float64 `json:"ask_price"`
		Ts     int64   `json:"timestamp"`
	} `json:"bybit_quote"`
	ForwardEntrySpread float64 `json:"forward_entry_spread"`
	ForwardExitSpread  float64 `json:"forward_exit_spread"`
	ReverseEntrySpread float64 `json:"reverse_entry_spread"`
	ReverseExitSpread  float64 `json:"reverse_exit_spread"`
	Timestamp          int64   `json:"timestamp"`
}

// GetSpread fetches Binance + MT5 quotes and calculates arbitrage spreads.
// Accepts ?pair_code=XAU (default "XAU") to select the product pair.
func GetSpread(c *gin.Context) {
	// Accept both ?pair= and ?pair_code= (Python client uses the former)
	pairCode := c.Query("pair_code")
	if pairCode == "" {
		pairCode = c.DefaultQuery("pair", "XAU")
	}
	pair := pairs.Global.Get(pairCode)
	if pair == nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("Unknown pair_code: %s", pairCode)})
		return
	}

	var aBid, aAsk float64
	switch pair.APlatformID {
	case 1, 0: // Binance WS ticker (0 = legacy default)
		aBid, aAsk, _ = GlobalTicks.Get(pair.BinanceSymbol)
		if aBid == 0 || aAsk == 0 {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": fmt.Sprintf("Binance data not ready for %s", pair.BinanceSymbol)})
			return
		}
	case 4: // Gate — REST poll (1s cached)
		gt, err := GetGateTick(pair.BinanceSymbol)
		if err != nil || gt.Bid == 0 || gt.Ask == 0 {
			c.JSON(http.StatusBadGateway, gin.H{"error": fmt.Sprintf("Gate data not ready for %s: %v", pair.BinanceSymbol, err)})
			return
		}
		aBid, aAsk = gt.Bid, gt.Ask
	default:
		c.JSON(http.StatusNotImplemented, gin.H{"error": fmt.Sprintf("A-side platform %d not supported for pair %s", pair.APlatformID, pair.PairCode)})
		return
	}
	binanceBid, binanceAsk := aBid, aAsk

	bybit, err := GetMT5TickFromBridge(pair.MT5Symbol, pair.BridgeURL)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": fmt.Sprintf("MT5 Bridge fetch failed for %s: %v", pair.MT5Symbol, err)})
		return
	}

	now := time.Now().UnixMilli()
	sd := SpreadData{PairCode: pairCode, Timestamp: now}
	sd.BinanceQuote.Symbol = pair.BinanceSymbol
	sd.BinanceQuote.Bid = binanceBid
	sd.BinanceQuote.Ask = binanceAsk
	sd.BinanceQuote.Ts = now
	sd.BybitQuote.Symbol = pair.MT5Symbol
	sd.BybitQuote.Bid = bybit.Bid
	sd.BybitQuote.Ask = bybit.Ask
	sd.BybitQuote.Ts = bybit.Ts

	sd.ForwardEntrySpread = bybit.Bid - binanceBid
	sd.ForwardExitSpread = bybit.Ask - binanceAsk
	sd.ReverseEntrySpread = binanceAsk - bybit.Ask
	sd.ReverseExitSpread = binanceBid - bybit.Bid

	c.JSON(http.StatusOK, sd)
}

// ComputeSpreadForPair calculates spread data for a given pair config.
// Used by the spread pusher to broadcast per-pair spreads via WebSocket.
func ComputeSpreadForPair(pair pairs.PairConfig) map[string]interface{} {
	var binanceBid, binanceAsk float64
	var ts int64
	switch pair.APlatformID {
	case 1, 0:
		binanceBid, binanceAsk, ts = GlobalTicks.Get(pair.BinanceSymbol)
	case 4:
		gt, err := GetGateTick(pair.BinanceSymbol)
		if err != nil {
			return nil
		}
		binanceBid, binanceAsk, ts = gt.Bid, gt.Ask, gt.Ts
	default:
		return nil
	}
	if binanceBid == 0 || binanceAsk == 0 {
		return nil
	}

	bybit, err := GetMT5TickFromBridge(pair.MT5Symbol, pair.BridgeURL)
	if err != nil || bybit.Bid == 0 {
		return nil
	}

	return map[string]interface{}{
		"pair_code":            pair.PairCode,
		"binance_bid":         binanceBid,
		"binance_ask":         binanceAsk,
		"bybit_bid":           bybit.Bid,
		"bybit_ask":           bybit.Ask,
		"forward_entry_spread": bybit.Bid - binanceBid,
		"forward_exit_spread":  bybit.Ask - binanceAsk,
		"reverse_entry_spread": binanceAsk - bybit.Ask,
		"reverse_exit_spread":  binanceBid - bybit.Bid,
		"timestamp":           ts,
	}
}
