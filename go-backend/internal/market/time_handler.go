package market

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

// timeOffset stores the Binance-local time offset in milliseconds (atomic)
var timeOffset atomic.Int64

type binanceServerTimeResp struct {
	ServerTime int64 `json:"serverTime"`
}

// SyncServerTime fetches Binance server time and stores the offset
func SyncServerTime(c *gin.Context) {
	offset, binanceTime, localTime, err := fetchBinanceTimeOffset()
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": fmt.Sprintf("time sync failed: %v", err)})
		return
	}
	timeOffset.Store(offset)
	c.JSON(http.StatusOK, gin.H{
		"binance_time": binanceTime,
		"local_time":   localTime,
		"offset":       offset,
	})
}

// GetTimeOffset returns the stored time offset
func GetTimeOffset(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"offset":    timeOffset.Load(),
		"timestamp": time.Now().UnixMilli(),
	})
}

func fetchBinanceTimeOffset() (offset, binanceTime, localTime int64, err error) {
	url := "https://fapi.binance.com/fapi/v1/time"
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	resp, err := httpClient.Do(req)
	if err != nil {
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var data binanceServerTimeResp
	if err = json.Unmarshal(body, &data); err != nil {
		return
	}
	binanceTime = data.ServerTime
	localTime = time.Now().UnixMilli()
	offset = binanceTime - localTime
	return
}

// RunTimeSyncLoop periodically syncs server time every 5 minutes
func RunTimeSyncLoop() {
	for {
		offset, _, _, err := fetchBinanceTimeOffset()
		if err == nil {
			timeOffset.Store(offset)
		}
		time.Sleep(5 * time.Minute)
	}
}
