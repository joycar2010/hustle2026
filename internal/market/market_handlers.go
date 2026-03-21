package market

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
)

// QuoteResponse is the Binance quote HTTP response
type QuoteResponse struct {
	Symbol    string  `json:"symbol"`
	Bid       float64 `json:"bid"`
	Ask       float64 `json:"ask"`
	Spread    float64 `json:"spread"`
	Timestamp int64   `json:"timestamp"`
}

// GetBinanceQuote returns the latest Binance XAUUSDT best bid/ask
func GetBinanceQuote(c *gin.Context) {
	bid, ask, ts := GetTick()
	if bid == 0 || ask == 0 {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Binance WebSocket not yet connected"})
		return
	}
	c.JSON(http.StatusOK, QuoteResponse{
		Symbol:    "XAUUSDT",
		Bid:       bid,
		Ask:       ask,
		Spread:    ask - bid,
		Timestamp: ts,
	})
}

// GetOrderBook returns best bid/ask with volume from both Binance and Bybit
func GetOrderBook(c *gin.Context) {
	type result struct {
		data map[string]interface{}
		err  error
		key  string
	}

	ch := make(chan result, 2)

	go func() {
		data, err := getBinanceOrderBook("XAUUSDT")
		ch <- result{data: data, err: err, key: "binance"}
	}()
	go func() {
		data, err := GetBybitOrderBook("XAUUSDT")
		ch <- result{data: data, err: err, key: "bybit"}
	}()

	resp := gin.H{"timestamp": time.Now().UnixMilli()}
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

// GetFundingRate returns Bybit XAUUSDT funding rate
func GetFundingRate(c *gin.Context) {
	data, err := GetBybitFundingRate("XAUUSDT")
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, data)
}

// GetBybitSwapRate returns Bybit XAUUSDT swap/funding rate (alias)
func GetBybitSwapRate(c *gin.Context) {
	data, err := GetBybitFundingRate("XAUUSDT")
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, data)
}
