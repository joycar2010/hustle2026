package market

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/pairs"
)

// QuoteResponse is the Binance quote HTTP response
type QuoteResponse struct {
	Symbol    string  `json:"symbol"`
	PairCode  string  `json:"pair_code,omitempty"`
	Bid       float64 `json:"bid"`
	Ask       float64 `json:"ask"`
	Spread    float64 `json:"spread"`
	Timestamp int64   `json:"timestamp"`
}

// GetBinanceQuote returns the latest Binance best bid/ask.
// Accepts ?pair_code=XAU (default "XAU").
func GetBinanceQuote(c *gin.Context) {
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

	bid, ask, ts := GlobalTicks.Get(pair.BinanceSymbol)
	if bid == 0 || ask == 0 {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": fmt.Sprintf("No data for %s", pair.BinanceSymbol)})
		return
	}
	c.JSON(http.StatusOK, QuoteResponse{
		Symbol:    pair.BinanceSymbol,
		PairCode:  pairCode,
		Bid:       bid,
		Ask:       ask,
		Spread:    ask - bid,
		Timestamp: ts,
	})
}

// GetOrderBook returns best bid/ask with volume from both Binance and MT5/Bybit.
// Accepts ?pair_code=XAU (default "XAU").
func GetOrderBook(c *gin.Context) {
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

	type result struct {
		data map[string]interface{}
		err  error
		key  string
	}

	ch := make(chan result, 2)

	go func() {
		data, err := getBinanceOrderBook(pair.BinanceSymbol)
		ch <- result{data: data, err: err, key: "binance"}
	}()
	go func() {
		data, err := GetBybitOrderBook(pair.BinanceSymbol)
		ch <- result{data: data, err: err, key: "bybit"}
	}()

	resp := gin.H{"pair_code": pairCode, "timestamp": time.Now().UnixMilli()}
	for i := 0; i < 2; i++ {
		r := <-ch
		if r.err != nil {
			resp[r.key] = gin.H{}
		} else {
			resp[r.key] = r.data
		}
	}
	c.JSON(http.StatusOK, resp)
}

func getBinanceOrderBook(symbol string) (map[string]interface{}, error) {
	url := fmt.Sprintf("https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol=%s", symbol)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var data map[string]interface{}
	if err := json.Unmarshal(body, &data); err != nil {
		return nil, err
	}
	bp, _ := strconv.ParseFloat(fmt.Sprint(data["bidPrice"]), 64)
	bv, _ := strconv.ParseFloat(fmt.Sprint(data["bidQty"]), 64)
	ap, _ := strconv.ParseFloat(fmt.Sprint(data["askPrice"]), 64)
	av, _ := strconv.ParseFloat(fmt.Sprint(data["askQty"]), 64)
	return map[string]interface{}{
		"symbol":     symbol,
		"bid_price":  bp,
		"bid_volume": bv,
		"ask_price":  ap,
		"ask_volume": av,
		"timestamp":  time.Now().UnixMilli(),
	}, nil
}

// GetFundingRate returns Binance funding rate + per-lot cost.
// Accepts ?pair_code=XAU (default "XAU").
func GetFundingRate(c *gin.Context) {
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

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var resp struct {
		Symbol          string `json:"symbol"`
		MarkPrice       string `json:"markPrice"`
		LastFundingRate string `json:"lastFundingRate"`
		NextFundingTime int64  `json:"nextFundingTime"`
	}
	apiURL := fmt.Sprintf("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=%s", pair.BinanceSymbol)
	if err := getJSON(ctx, apiURL, &resp); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}
	markPrice, _ := strconv.ParseFloat(resp.MarkPrice, 64)
	rate, _ := strconv.ParseFloat(resp.LastFundingRate, 64)

	// per-lot cost: conversion_factor * mark_price * rate
	perLot := pair.ConversionFactor * markPrice * rate
	c.JSON(http.StatusOK, gin.H{
		"symbol":             resp.Symbol,
		"pair_code":          pairCode,
		"mark_price":         markPrice,
		"funding_rate":       rate,
		"funding_rate_pct":   rate * 100.0,
		"long_cost_per_lot":  perLot,
		"short_cost_per_lot": -perLot,
		"next_funding_time":  resp.NextFundingTime,
		"timestamp":          time.Now().UnixMilli(),
	})
}

// GetBybitSwapRate returns MT5 broker overnight swap rates.
// Accepts ?pair_code=XAU (default "XAU").
func GetBybitSwapRate(c *gin.Context) {
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

	base := pair.BridgeURL
	if base == "" {
		base = os.Getenv("MT5_SERVICE_URL")
	}
	if base == "" {
		base = "http://172.31.14.113:8887"
	}
	apiURL := base + "/mt5/symbol_info/" + url.PathEscape(pair.MT5Symbol)
	req, err := http.NewRequest(http.MethodGet, apiURL, nil)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	if k := os.Getenv("MT5_API_KEY"); k != "" {
		req.Header.Set("X-Api-Key", k)
	}
	client := &http.Client{Timeout: 5 * time.Second}
	httpResp, err := client.Do(req)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}
	defer httpResp.Body.Close()

	var info struct {
		Symbol    string  `json:"symbol"`
		SwapLong  float64 `json:"swap_long"`
		SwapShort float64 `json:"swap_short"`
		SwapMode  int     `json:"swap_mode"`
		Contract  float64 `json:"trade_contract_size"`
		Rollover3 int     `json:"swap_rollover3days"`
	}
	if err := json.NewDecoder(httpResp.Body).Decode(&info); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}

	longSwap := info.SwapLong / pair.ConversionFactor
	shortSwap := info.SwapShort / pair.ConversionFactor

	c.JSON(http.StatusOK, gin.H{
		"symbol":             info.Symbol,
		"pair_code":          pairCode,
		"long_swap_per_lot":  longSwap,
		"short_swap_per_lot": shortSwap,
		"swap_mode":          info.SwapMode,
		"rollover_day":       info.Rollover3,
		"contract_size":      info.Contract,
		"timestamp":          time.Now().UnixMilli(),
	})
}
