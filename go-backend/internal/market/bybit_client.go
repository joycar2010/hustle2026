package market

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"
)

const bybitBaseURL = "https://api.bybit.com"

type BybitTicker struct {
	Bid float64
	Ask float64
	Ts  int64
}

type bybitTickerResp struct {
	RetCode int    `json:"retCode"`
	RetMsg  string `json:"retMsg"`
	Result  struct {
		List []struct {
			Symbol    string `json:"symbol"`
			Bid1Price string `json:"bid1Price"`
			Ask1Price string `json:"ask1Price"`
		} `json:"list"`
	} `json:"result"`
}

type bybitOrderBookResp struct {
	RetCode int    `json:"retCode"`
	RetMsg  string `json:"retMsg"`
	Result  struct {
		B [][]string `json:"b"`
		A [][]string `json:"a"`
	} `json:"result"`
}

type bybitFundingResp struct {
	RetCode int    `json:"retCode"`
	RetMsg  string `json:"retMsg"`
	Result  struct {
		List []struct {
			Symbol               string `json:"symbol"`
			FundingRate          string `json:"fundingRate"`
			NextFundingTime      string `json:"nextFundingTime"`
			FundingRateTimestamp string `json:"fundingRateTimestamp"`
		} `json:"list"`
	} `json:"result"`
}

var httpClient = &http.Client{Timeout: 5 * time.Second}

func getJSON(ctx context.Context, url string, out interface{}) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	return json.Unmarshal(body, out)
}

// GetBybitTicker fetches best bid/ask from Bybit linear (USDT perp)
func GetBybitTicker(symbol string) (*BybitTicker, error) {
	url := fmt.Sprintf("%s/v5/market/tickers?category=linear&symbol=%s", bybitBaseURL, symbol)
	var resp bybitTickerResp
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := getJSON(ctx, url, &resp); err != nil {
		return nil, err
	}
	if resp.RetCode != 0 || len(resp.Result.List) == 0 {
		return nil, fmt.Errorf("bybit ticker error: %s", resp.RetMsg)
	}
	item := resp.Result.List[0]
	bid, _ := strconv.ParseFloat(item.Bid1Price, 64)
	ask, _ := strconv.ParseFloat(item.Ask1Price, 64)
	return &BybitTicker{Bid: bid, Ask: ask, Ts: time.Now().UnixMilli()}, nil
}

// GetBybitOrderBook fetches best bid/ask with volume from Bybit
func GetBybitOrderBook(symbol string) (map[string]interface{}, error) {
	url := fmt.Sprintf("%s/v5/market/orderbook?category=linear&symbol=%s&limit=1", bybitBaseURL, symbol)
	var resp bybitOrderBookResp
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := getJSON(ctx, url, &resp); err != nil {
		return nil, err
	}
	if resp.RetCode != 0 {
		return nil, fmt.Errorf("bybit orderbook error: %s", resp.RetMsg)
	}
	result := map[string]interface{}{"symbol": symbol, "timestamp": time.Now().UnixMilli()}
	if len(resp.Result.B) > 0 {
		bp, _ := strconv.ParseFloat(resp.Result.B[0][0], 64)
		bv, _ := strconv.ParseFloat(resp.Result.B[0][1], 64)
		result["bid_price"] = bp
		result["bid_volume"] = bv
	}
	if len(resp.Result.A) > 0 {
		ap, _ := strconv.ParseFloat(resp.Result.A[0][0], 64)
		av, _ := strconv.ParseFloat(resp.Result.A[0][1], 64)
		result["ask_price"] = ap
		result["ask_volume"] = av
	}
	return result, nil
}

// GetBybitFundingRate fetches current funding rate
func GetBybitFundingRate(symbol string) (map[string]interface{}, error) {
	url := fmt.Sprintf("%s/v5/market/tickers?category=linear&symbol=%s", bybitBaseURL, symbol)
	var resp struct {
		RetCode int    `json:"retCode"`
		RetMsg  string `json:"retMsg"`
		Result  struct {
			List []struct {
				Symbol          string `json:"symbol"`
				FundingRate     string `json:"fundingRate"`
				NextFundingTime string `json:"nextFundingTime"`
			} `json:"list"`
		} `json:"result"`
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := getJSON(ctx, url, &resp); err != nil {
		return nil, err
	}
	if resp.RetCode != 0 || len(resp.Result.List) == 0 {
		return nil, fmt.Errorf("bybit funding error: %s", resp.RetMsg)
	}
	item := resp.Result.List[0]
	rate, _ := strconv.ParseFloat(item.FundingRate, 64)
	nextTs, _ := strconv.ParseInt(item.NextFundingTime, 10, 64)
	return map[string]interface{}{
		"symbol":            item.Symbol,
		"funding_rate":      rate,
		"next_funding_time": nextTs,
		"timestamp":         time.Now().UnixMilli(),
	}, nil
}
