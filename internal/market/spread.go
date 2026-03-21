package market

import (
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// SpreadData is the arbitrage spread payload
type SpreadData struct {
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
	ForwardEntrySpread float64 `json:"forward_entry_spread"` // bybit_bid - binance_bid
	ForwardExitSpread  float64 `json:"forward_exit_spread"`  // bybit_ask - binance_ask
	ReverseEntrySpread float64 `json:"reverse_entry_spread"` // binance_ask - bybit_ask
	ReverseExitSpread  float64 `json:"reverse_exit_spread"`  // binance_bid - bybit_bid
	Timestamp          int64   `json:"timestamp"`
}

// GetSpread fetches Binance + Bybit quotes and calculates arbitrage spreads
func GetSpread(c *gin.Context) {
	binanceBid, binanceAsk, _ := GetTick()
	if binanceBid == 0 || binanceAsk == 0 {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Binance WebSocket not ready"})
		return
	}

	bybit, err := GetBybitTicker("XAUUSDT")
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": fmt.Sprintf("Bybit fetch failed: %v", err)})
		return
	}

	now := time.Now().UnixMilli()
	sd := SpreadData{Timestamp: now}
	sd.BinanceQuote.Symbol = "XAUUSDT"
	sd.BinanceQuote.Bid = binanceBid
	sd.BinanceQuote.Ask = binanceAsk
	sd.BinanceQuote.Ts = now
	sd.BybitQuote.Symbol = "XAUUSDT"
	sd.BybitQuote.Bid = bybit.Bid
	sd.BybitQuote.Ask = bybit.Ask
	sd.BybitQuote.Ts = bybit.Ts

	// Arbitrage spread formulas (same as Python market_service.py)
	sd.ForwardEntrySpread = bybit.Bid - binanceBid
	sd.ForwardExitSpread = bybit.Ask - binanceAsk
	sd.ReverseEntrySpread = binanceAsk - bybit.Ask
	sd.ReverseExitSpread = binanceBid - bybit.Bid

	c.JSON(http.StatusOK, sd)
}
