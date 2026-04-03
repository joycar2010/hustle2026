package trading

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
	"hustle-go/internal/market"
)

type orderRow struct {
	OrderID         string    `json:"order_id"`
	AccountID       string    `json:"account_id"`
	Symbol          string    `json:"symbol"`
	OrderSide       string    `json:"order_side"`
	OrderType       string    `json:"order_type"`
	Price           float64   `json:"price"`
	Qty             float64   `json:"qty"`
	FilledQty       float64   `json:"filled_qty"`
	Status          string    `json:"status"`
	PlatformOrderID *string   `json:"platform_order_id"`
	Fee             float64   `json:"fee"`
	Source          string    `json:"source"`
	CreateTime      time.Time `json:"create_time"`
	UpdateTime      time.Time `json:"update_time"`
}

func scanOrder(row interface{ Scan(...any) error }) (*orderRow, error) {
	o := &orderRow{}
	return o, row.Scan(
		&o.OrderID, &o.AccountID, &o.Symbol, &o.OrderSide, &o.OrderType,
		&o.Price, &o.Qty, &o.FilledQty, &o.Status, &o.PlatformOrderID,
		&o.Fee, &o.Source, &o.CreateTime, &o.UpdateTime,
	)
}

const selectOrder = `SELECT order_id::text, account_id::text, symbol, order_side, order_type,
	price, qty, filled_qty, status, platform_order_id, fee, source, create_time, update_time
	FROM order_records`

// GetOrders GET /api/v1/trading/orders
func GetOrders(c *gin.Context) {
	userID := c.GetString("user_id")
	limit := 50
	source := c.Query("source")
	statusFilter := c.Query("status")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	accRows, err := db.Pool().Query(ctx,
		`SELECT account_id::text FROM accounts WHERE user_id=$1::uuid`, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	var accountIDs []string
	for accRows.Next() {
		var id string
		accRows.Scan(&id)
		accountIDs = append(accountIDs, id)
	}
	accRows.Close()
	if len(accountIDs) == 0 {
		c.JSON(http.StatusOK, []gin.H{})
		return
	}

	query := selectOrder + ` WHERE account_id = ANY($1::uuid[])`
	args := []interface{}{accountIDs}
	argIdx := 2

	if source != "" {
		query += ` AND source=$` + strconv.Itoa(argIdx)
		args = append(args, source)
		argIdx++
	}
	if statusFilter != "" {
		// Support comma-separated status values like "new,pending"
		statuses := strings.Split(statusFilter, ",")
		if len(statuses) == 1 {
			query += ` AND status=$` + strconv.Itoa(argIdx)
			args = append(args, statusFilter)
			argIdx++
		} else {
			placeholders := make([]string, len(statuses))
			for i, s := range statuses {
				placeholders[i] = "$" + strconv.Itoa(argIdx)
				args = append(args, strings.TrimSpace(s))
				argIdx++
			}
			query += ` AND status IN (` + strings.Join(placeholders, ",") + `)`
		}
	}
	query += ` ORDER BY create_time DESC LIMIT $` + strconv.Itoa(argIdx)
	args = append(args, limit)

	rows, err := db.Pool().Query(ctx, query, args...)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()

	var orders []gin.H
	for rows.Next() {
		o, err := scanOrder(rows)
		if err != nil {
			continue
		}
		orders = append(orders, gin.H{
			"id":        o.OrderID,
			"timestamp": o.CreateTime.Format(time.RFC3339),
			"exchange":  "exchange",
			"side":      o.OrderSide,
			"quantity":  o.Qty,
			"price":     o.Price,
			"status":    o.Status,
			"symbol":    o.Symbol,
			"source":    o.Source,
		})
	}
	if orders == nil {
		orders = []gin.H{}
	}
	c.JSON(http.StatusOK, orders)
}

// GetTradingHistory GET /api/v1/trading/history
func GetTradingHistory(c *gin.Context) {
	userID := c.GetString("user_id")
	dateStr := c.Query("date")

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	accRows, err := db.Pool().Query(ctx,
		`SELECT account_id::text, platform_id, is_mt5_account FROM accounts WHERE user_id=$1::uuid`, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	type accInfo struct {
		id         string
		platformID int
		isMT5      bool
	}
	var accounts []accInfo
	for accRows.Next() {
		var a accInfo
		accRows.Scan(&a.id, &a.platformID, &a.isMT5)
		accounts = append(accounts, a)
	}
	accRows.Close()

	if len(accounts) == 0 {
		c.JSON(http.StatusOK, gin.H{"stats": gin.H{}, "accountTrades": []gin.H{}, "mt5Trades": []gin.H{}})
		return
	}

	var accountIDs []string
	for _, a := range accounts {
		accountIDs = append(accountIDs, a.id)
	}

	query := selectOrder + ` WHERE account_id = ANY($1::uuid[])`
	args := []interface{}{accountIDs}

	if dateStr != "" {
		t, err := time.Parse("2006-01-02", dateStr)
		if err == nil {
			query += ` AND create_time >= $2 AND create_time < $3`
			args = append(args, t, t.Add(24*time.Hour))
		}
	}
	query += ` ORDER BY create_time ASC`

	rows, err := db.Pool().Query(ctx, query, args...)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()

	accMap := map[string]accInfo{}
	for _, a := range accounts {
		accMap[a.id] = a
	}

	var accountTrades []gin.H
	var mt5Trades []gin.H

	for rows.Next() {
		o, err := scanOrder(rows)
		if err != nil {
			continue
		}
		acc := accMap[o.AccountID]
		trade := gin.H{
			"order_id":          o.OrderID,
			"account_id":        o.AccountID,
			"symbol":            o.Symbol,
			"side":              o.OrderSide,
			"type":              o.OrderType,
			"price":             o.Price,
			"qty":               o.Qty,
			"filled_qty":        o.FilledQty,
			"status":            o.Status,
			"platform_order_id": o.PlatformOrderID,
			"fee":               o.Fee,
			"source":            o.Source,
			"create_time":       o.CreateTime,
		}
		if acc.isMT5 {
			mt5Trades = append(mt5Trades, trade)
		} else {
			accountTrades = append(accountTrades, trade)
		}
	}

	if accountTrades == nil {
		accountTrades = []gin.H{}
	}
	if mt5Trades == nil {
		mt5Trades = []gin.H{}
	}
	c.JSON(http.StatusOK, gin.H{
		"stats":         gin.H{},
		"accountTrades": accountTrades,
		"mt5Trades":     mt5Trades,
	})
}

// GetAllTradingHistory GET /api/v1/trading/history/all
func GetAllTradingHistory(c *gin.Context) {
	GetTradingHistory(c)
}

// DeleteAllTradingHistory DELETE /api/v1/trading/history/all
func DeleteAllTradingHistory(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	accRows, err := db.Pool().Query(ctx,
		`SELECT account_id::text FROM accounts WHERE user_id=$1::uuid`, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	var accountIDs []string
	for accRows.Next() {
		var id string
		accRows.Scan(&id)
		accountIDs = append(accountIDs, id)
	}
	accRows.Close()

	if len(accountIDs) == 0 {
		c.JSON(http.StatusOK, gin.H{"message": "No data to delete"})
		return
	}
	_, err = db.Pool().Exec(ctx,
		`DELETE FROM order_records WHERE account_id = ANY($1::uuid[])`, accountIDs)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "All trading history deleted successfully"})
}

// ── Manual Trading ─────────────────────────────────────────────────────────

type manualOrderReq struct {
	Exchange  string  `json:"exchange"`
	Side      string  `json:"side"`
	Quantity  float64 `json:"quantity"`
	AccountID *string `json:"account_id"`
}

type closePosReq struct {
	Exchange string  `json:"exchange"`
	Quantity float64 `json:"quantity"`
}

// ManualOrder POST /api/v1/trading/manual/order
func ManualOrder(c *gin.Context) {
	userID := c.GetString("user_id")
	var req manualOrderReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	if req.Exchange == "" || req.Side == "" || req.Quantity <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "exchange, side, quantity required"})
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	bid, ask, _ := market.GetTick()
	if bid == 0 || ask == 0 {
		c.JSON(http.StatusServiceUnavailable, gin.H{"detail": "market data not available"})
		return
	}

	switch req.Exchange {
	case "binance":
		creds, err := loadCredsByPlatform(ctx, userID, PlatformBinance)
		if err != nil {
			c.JSON(http.StatusNotFound, gin.H{"detail": "no Binance account found"})
			return
		}
		var price float64
		var positionSide string
		if req.Side == "buy" {
			price = bid
			positionSide = "LONG"
		} else {
			price = ask
			positionSide = "SHORT"
		}
		body, status, err := PlaceBinanceOrder(ctx, creds, "XAUUSDT",
			req.Side, "LIMIT", positionSide,
			FormatQty(req.Quantity), FormatPrice(price))
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"detail": err.Error()})
			return
		}
		c.Data(status, "application/json", body)

	case "bybit":
		payload := map[string]interface{}{
			"symbol":     "XAUUSD+",
			"volume":     req.Quantity,
			"order_type": "market",
			"side":       req.Side,
		}
		b, _ := json.Marshal(payload)
		body, status, err := callMT5(ctx, http.MethodPost, "/mt5/order", b)
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"detail": err.Error()})
			return
		}
		c.Data(status, "application/json", body)

	default:
		c.JSON(http.StatusBadRequest, gin.H{"detail": "exchange must be 'binance' or 'bybit'"})
	}
}

// ManualCloseAll POST /api/v1/trading/manual/close-all
func ManualCloseAll(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	bid, ask, _ := market.GetTick()
	var results []gin.H

	creds, err := loadCredsByPlatform(ctx, userID, PlatformBinance)
	if err == nil {
		posBody, _, err := GetBinancePositions(ctx, creds, "XAUUSDT")
		if err == nil {
			var positions []struct {
				PositionAmt  string `json:"positionAmt"`
				PositionSide string `json:"positionSide"`
			}
			if json.Unmarshal(posBody, &positions) == nil {
				for _, pos := range positions {
					amt, _ := strconv.ParseFloat(pos.PositionAmt, 64)
					if amt == 0 {
						continue
					}
					var side, posSide, price string
					if amt > 0 {
						side, posSide, price = "SELL", "LONG", FormatPrice(ask)
					} else {
						side, posSide, price = "BUY", "SHORT", FormatPrice(bid)
						amt = -amt
					}
					rb, st, _ := PlaceBinanceOrder(ctx, creds, "XAUUSDT",
						side, "LIMIT", posSide, FormatQty(amt), price)
					results = append(results, gin.H{
						"exchange":      "binance",
						"position_side": posSide,
						"quantity":      amt,
						"status":        st,
						"response":      json.RawMessage(rb),
					})
				}
			}
		}
	}

	rb, st, err := callMT5(ctx, http.MethodPost, "/mt5/position/close-all", nil)
	if err == nil {
		results = append(results, gin.H{
			"exchange": "bybit",
			"status":   st,
			"response": json.RawMessage(rb),
		})
	}

	c.JSON(http.StatusOK, gin.H{
		"success": true,
		"results": results,
		"message": "close-all executed",
	})
}

// ManualCloseLong POST /api/v1/trading/manual/close-long
func ManualCloseLong(c *gin.Context) {
	userID := c.GetString("user_id")
	var req closePosReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	bid, _, _ := market.GetTick()

	switch req.Exchange {
	case "binance":
		creds, err := loadCredsByPlatform(ctx, userID, PlatformBinance)
		if err != nil {
			c.JSON(http.StatusNotFound, gin.H{"detail": "no Binance account"})
			return
		}
		body, status, err := PlaceBinanceOrder(ctx, creds, "XAUUSDT",
			"SELL", "LIMIT", "LONG",
			FormatQty(req.Quantity), FormatPrice(bid))
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"detail": err.Error()})
			return
		}
		c.Data(status, "application/json", body)

	case "bybit":
		payload, _ := json.Marshal(map[string]interface{}{
			"symbol":         "XAUUSD+",
			"volume":         req.Quantity,
			"order_type":     "market",
			"side":           "sell",
			"close_position": true,
		})
		body, status, err := callMT5(ctx, http.MethodPost, "/mt5/position/close", payload)
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"detail": err.Error()})
			return
		}
		c.Data(status, "application/json", body)

	default:
		c.JSON(http.StatusBadRequest, gin.H{"detail": "exchange must be 'binance' or 'bybit'"})
	}
}

// ManualCloseShort POST /api/v1/trading/manual/close-short
func ManualCloseShort(c *gin.Context) {
	userID := c.GetString("user_id")
	var req closePosReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	_, ask, _ := market.GetTick()

	switch req.Exchange {
	case "binance":
		creds, err := loadCredsByPlatform(ctx, userID, PlatformBinance)
		if err != nil {
			c.JSON(http.StatusNotFound, gin.H{"detail": "no Binance account"})
			return
		}
		body, status, err := PlaceBinanceOrder(ctx, creds, "XAUUSDT",
			"BUY", "LIMIT", "SHORT",
			FormatQty(req.Quantity), FormatPrice(ask))
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"detail": err.Error()})
			return
		}
		c.Data(status, "application/json", body)

	case "bybit":
		payload, _ := json.Marshal(map[string]interface{}{
			"symbol":         "XAUUSD+",
			"volume":         req.Quantity,
			"order_type":     "market",
			"side":           "buy",
			"close_position": true,
		})
		body, status, err := callMT5(ctx, http.MethodPost, "/mt5/position/close", payload)
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"detail": err.Error()})
			return
		}
		c.Data(status, "application/json", body)

	default:
		c.JSON(http.StatusBadRequest, gin.H{"detail": "exchange must be 'binance' or 'bybit'"})
	}
}

// ManualCancelAll POST /api/v1/trading/manual/cancel-all
func ManualCancelAll(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	var results []gin.H

	creds, err := loadCredsByPlatform(ctx, userID, PlatformBinance)
	if err == nil {
		body, status, _ := CancelAllBinanceOrders(ctx, creds, "XAUUSDT")
		results = append(results, gin.H{
			"exchange": "binance",
			"status":   status,
			"response": json.RawMessage(body),
		})
	}

	body, status, err := callMT5(ctx, http.MethodPost, "/mt5/order/cancel-all", nil)
	if err == nil {
		results = append(results, gin.H{
			"exchange": "bybit",
			"status":   status,
			"response": json.RawMessage(body),
		})
	}

	c.JSON(http.StatusOK, gin.H{
		"success": true,
		"results": results,
		"message": "cancel-all executed",
	})
}

// ManualProcess POST /api/v1/trading/orders/:order_id/manual-process
func ManualProcess(c *gin.Context) {
	orderID := c.Param("order_id")
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	tag, err := db.Pool().Exec(ctx,
		`UPDATE order_records SET status='manually_processed', update_time=NOW()
		 WHERE order_id=$1::uuid
		 AND account_id IN (SELECT account_id FROM accounts WHERE user_id=$2::uuid)`,
		orderID, userID)
	if err != nil || tag.RowsAffected() == 0 {
		c.JSON(http.StatusNotFound, gin.H{"detail": "order not found or no permission"})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"success":    true,
		"order_id":   orderID,
		"new_status": "manually_processed",
	})
}

// RealtimeOrders GET /api/v1/trading/orders/realtime
func RealtimeOrders(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	creds, err := loadCredsByPlatform(ctx, userID, PlatformBinance)
	if err != nil {
		c.JSON(http.StatusOK, []gin.H{})
		return
	}

	body, status, err := GetBinanceOpenOrders(ctx, creds, "XAUUSDT")
	if err != nil || status != 200 {
		c.JSON(http.StatusOK, []gin.H{})
		return
	}

	var raw []map[string]interface{}
	if err := json.Unmarshal(body, &raw); err != nil {
		c.JSON(http.StatusOK, []gin.H{})
		return
	}

	var orders []gin.H
	for _, o := range raw {
		orderTime, _ := o["time"].(float64)
		ts := time.Unix(0, int64(orderTime)*int64(time.Millisecond)).Format(time.RFC3339)
		qty, _ := strconv.ParseFloat(mapStr(o["origQty"]), 64)
		price, _ := strconv.ParseFloat(mapStr(o["price"]), 64)
		side := strings.ToLower(mapStr(o["side"]))
		statusStr := strings.ToLower(mapStr(o["status"]))
		symbolStr := mapStr(o["symbol"])
		orders = append(orders, gin.H{
			"id":        mapStr(o["orderId"]),
			"timestamp": ts,
			"exchange":  "Binance",
			"side":      side,
			"quantity":  qty,
			"price":     price,
			"status":    statusStr,
			"symbol":    symbolStr,
			"source":    "strategy",
		})
	}
	if orders == nil {
		orders = []gin.H{}
	}
	c.JSON(http.StatusOK, orders)
}

// RealtimeHistory GET /api/v1/trading/history/realtime
func RealtimeHistory(c *gin.Context) {
	userID := c.GetString("user_id")
	startTimeStr := c.Query("start_time")
	endTimeStr := c.Query("end_time")

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	const layout = "2006-01-02 15:04:05"
	var startMs, endMs int64
	if t, err := time.ParseInLocation(layout, startTimeStr, time.FixedZone("CST", 8*3600)); err == nil {
		startMs = t.UTC().UnixMilli()
	}
	if t, err := time.ParseInLocation(layout, endTimeStr, time.FixedZone("CST", 8*3600)); err == nil {
		endMs = t.UTC().UnixMilli()
	}

	var binanceTrades json.RawMessage = []byte("[]")
	var realizedPnL float64

	if creds, err := loadCredsByPlatform(ctx, userID, PlatformBinance); err == nil {
		if body, st, err := GetBinanceUserTrades(ctx, creds, "XAUUSDT", startMs, endMs, 1000); err == nil && st == 200 {
			binanceTrades = body
		}
		if incBody, st, err := GetBinanceIncome(ctx, creds, "XAUUSDT", "REALIZED_PNL", startMs, endMs); err == nil && st == 200 {
			var incomeList []struct {
				Income string `json:"income"`
			}
			if json.Unmarshal(incBody, &incomeList) == nil {
				for _, item := range incomeList {
					v, _ := strconv.ParseFloat(item.Income, 64)
					realizedPnL += v
				}
			}
		}
	}

	var mt5Trades json.RawMessage = []byte("[]")
	mt5Path := "/mt5/history/deals"
	if startMs > 0 && endMs > 0 {
		mt5Path += "?start_time=" + strconv.FormatInt(startMs, 10) + "&end_time=" + strconv.FormatInt(endMs, 10)
	}
	if mt5Body, mt5St, mt5Err := callMT5(ctx, http.MethodGet, mt5Path, nil); mt5Err == nil && mt5St == 200 {
		// MT5 bridge returns {"deals":[...]} — extract the array
		var mt5Resp map[string]json.RawMessage
		if json.Unmarshal(mt5Body, &mt5Resp) == nil {
			if deals, ok := mt5Resp["deals"]; ok {
				mt5Trades = deals
			} else {
				mt5Trades = mt5Body
			}
		} else {
			mt5Trades = mt5Body
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"accountTrades": json.RawMessage(binanceTrades),
		"mt5Trades":     mt5Trades,
		"stats": gin.H{
			"realizedPnL": realizedPnL,
		},
		"timeZone": "Asia/Shanghai (UTC+8)",
	})
}

// SyncTrades POST /api/v1/trading/sync-trades
func SyncTrades(c *gin.Context) {
	userID := c.GetString("user_id")
	days := 7
	if d := c.Query("days"); d != "" {
		if v, err := strconv.Atoi(d); err == nil && v > 0 && v <= 30 {
			days = v
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	creds, err := loadCredsByPlatform(ctx, userID, PlatformBinance)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"success": true, "synced_count": 0, "errors": nil})
		return
	}

	endMs := time.Now().UnixMilli()
	startMs := time.Now().AddDate(0, 0, -days).UnixMilli()

	body, status, err := GetBinanceUserTrades(ctx, creds, "XAUUSDT", startMs, endMs, 500)
	if err != nil || status != 200 {
		c.JSON(http.StatusOK, gin.H{"success": false, "detail": "exchange error", "synced_count": 0})
		return
	}

	var trades []map[string]interface{}
	if json.Unmarshal(body, &trades) != nil {
		c.JSON(http.StatusOK, gin.H{"success": true, "synced_count": 0})
		return
	}

	synced := 0
	for _, trade := range trades {
		platformOrderID := mapStr(trade["orderId"])
		if platformOrderID == "" {
			continue
		}
		side := strings.ToLower(mapStr(trade["side"]))
		tradeType := strings.ToLower(mapStr(trade["type"]))
		price, _ := strconv.ParseFloat(mapStr(trade["price"]), 64)
		qty, _ := strconv.ParseFloat(mapStr(trade["qty"]), 64)
		commission, _ := strconv.ParseFloat(mapStr(trade["commission"]), 64)
		tradeTimeMs, _ := trade["time"].(float64)
		tradeTime := time.Unix(0, int64(tradeTimeMs)*int64(time.Millisecond))

		tag, dbErr := db.Pool().Exec(ctx,
			`INSERT INTO order_records
			 (account_id, symbol, order_side, order_type, price, qty, filled_qty,
			  fee, status, source, platform_order_id, create_time)
			 VALUES ($1::uuid,$2,$3,$4,$5,$6,$6,$7,'filled','sync',$8,$9)
			 ON CONFLICT (platform_order_id, account_id) DO NOTHING`,
			creds.AccountID, "XAUUSDT", side, tradeType,
			price, qty, commission, platformOrderID, tradeTime,
		)
		if dbErr == nil && tag.RowsAffected() > 0 {
			synced++
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"success":      true,
		"synced_count": synced,
		"errors":       nil,
	})
}

// ── helpers ────────────────────────────────────────────────────────────────

func mapStr(v interface{}) string {
	if v == nil {
		return ""
	}
	switch t := v.(type) {
	case string:
		return t
	case float64:
		return strconv.FormatFloat(t, 'f', -1, 64)
	default:
		b, _ := json.Marshal(v)
		return string(b)
	}
}
