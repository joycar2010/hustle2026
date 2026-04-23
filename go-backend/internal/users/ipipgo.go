package users

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
)

const ipipgoAPI = "https://www.ipipgo.com/web/api/static-proxy/dynamic"
const ipipgoKey = "13957717158"
const ipipgoSign = "ba7c97980567c023880039024549c44b"

type ipipgoOrder struct {
	OrderNo     string  `json:"orderNo"`
	Amount      float64 `json:"amount"`
	CountryName string  `json:"countryName"`
	IPNum       int     `json:"ipNum"`
	BuyTime     string  `json:"buyTime"`
	PayType     int     `json:"payType"`
	State       int     `json:"state"`
	CreateTime  string  `json:"createTime"`
}

type ipipgoResp struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    struct {
		Data      []ipipgoOrder `json:"data"`
		TotalSize int           `json:"totalSize"`
	} `json:"data"`
}

// parseBuyTime extracts days from strings like "30天", "1天", "90天"
func parseBuyTime(bt string) int {
	re := regexp.MustCompile(`(\d+)`)
	m := re.FindString(bt)
	if m == "" {
		return 30
	}
	d, _ := strconv.Atoi(m)
	return d
}

// IPIPGOOrders GET /api/v1/users/ipipgo-orders
// Returns IPIPGO static proxy orders with computed expiration
func IPIPGOOrders(c *gin.Context) {
	callerID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	if !isAdmin(ctx, callerID) {
		c.JSON(http.StatusForbidden, gin.H{"detail": "仅管理员可操作"})
		return
	}

	body, _ := json.Marshal(map[string]interface{}{
		"key":      ipipgoKey,
		"sign":     ipipgoSign,
		"pageNum":  1,
		"pageSize": 100,
	})

	req, _ := http.NewRequest("POST", ipipgoAPI, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"detail": "IPIPGO API 请求失败: " + err.Error()})
		return
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)

	var result ipipgoResp
	if err := json.Unmarshal(raw, &result); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"detail": "IPIPGO 响应解析失败"})
		return
	}
	if result.Code != 0 {
		c.JSON(http.StatusBadGateway, gin.H{"detail": "IPIPGO 错误: " + result.Message})
		return
	}

	cst := time.FixedZone("CST", 8*3600)
	var orders []gin.H
	for _, o := range result.Data.Data {
		// Parse createTime as allocated_at
		allocatedAt, _ := time.ParseInLocation("2006-01-02 15:04:05", o.CreateTime, cst)

		// Compute expires_at from buyTime
		days := parseBuyTime(o.BuyTime)
		expiresAt := allocatedAt.AddDate(0, 0, days)

		// Determine status
		now := time.Now().In(cst)
		ipStatus := "unknown"
		if o.State == 2 {
			if now.Before(expiresAt) {
				ipStatus = "active"
			} else {
				ipStatus = "expired"
			}
		} else if o.State == 1 {
			ipStatus = "pending"
		} else {
			ipStatus = "cancelled"
		}

		orders = append(orders, gin.H{
			"order_no":     o.OrderNo,
			"country":      o.CountryName,
			"ip_count":     o.IPNum,
			"buy_time":     o.BuyTime,
			"amount":       o.Amount,
			"allocated_at": allocatedAt.Format("2006-01-02"),
			"expires_at":   expiresAt.Format("2006-01-02"),
			"ip_status":    ipStatus,
			"state":        o.State,
			"days_left":    int(expiresAt.Sub(now).Hours() / 24),
		})
	}
	if orders == nil {
		orders = []gin.H{}
	}
	c.JSON(http.StatusOK, gin.H{"orders": orders, "total": result.Data.TotalSize})
}
