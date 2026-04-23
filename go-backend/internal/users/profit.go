package users

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
)

// GetUserProfitChart GET /api/v1/users/:user_id/profit-chart?granularity=day&start=2024-01-01&end=2024-12-31
// granularity: hour | day | week | month
//
// 数据源: account_snapshots 表（由 Python AccountBalanceStreamer 每 300s 写入一次）
// daily_pnl 字段存储每次轮询时的浮动盈亏，按时间段聚合取平均值作为该时段收益。
func GetUserProfitChart(c *gin.Context) {
	targetUserID := c.Param("user_id")
	granularity := c.DefaultQuery("granularity", "day")
	startStr := c.Query("start")
	endStr := c.Query("end")

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	// --- Admin check ---
	callerID := c.GetString("user_id")
	if !isAdmin(ctx, callerID) && callerID != targetUserID {
		c.JSON(http.StatusForbidden, gin.H{"detail": "无权查看该用户收益"})
		return
	}

	// --- Default time range ---
	now := time.Now()
	var start, end time.Time
	if startStr != "" {
		if t, err := time.ParseInLocation("2006-01-02T15:04:05", startStr, time.FixedZone("CST", 8*3600)); err == nil {
			start = t
		} else if t2, err2 := time.ParseInLocation("2006-01-02", startStr, time.FixedZone("CST", 8*3600)); err2 == nil {
			start = t2
		}
	}
	if endStr != "" {
		if t, err := time.ParseInLocation("2006-01-02T15:04:05", endStr, time.FixedZone("CST", 8*3600)); err == nil {
			end = t
		} else if t2, err2 := time.ParseInLocation("2006-01-02", endStr, time.FixedZone("CST", 8*3600)); err2 == nil {
			end = t2.Add(24*time.Hour - time.Second)
		}
	}
	if start.IsZero() {
		switch granularity {
		case "hour":
			start = now.Add(-24 * time.Hour)
		case "week":
			start = now.AddDate(0, -3, 0)
		case "month":
			start = now.AddDate(-1, 0, 0)
		default:
			start = now.AddDate(0, -1, 0)
		}
	}
	if end.IsZero() {
		end = now
	}

	// --- Build SQL based on granularity ---
	// 数据源: account_snapshots 通过 accounts 表关联到 user_id
	//
	// 正确聚合逻辑：每个时间段取该段内「最后一条快照」的 daily_pnl 之和。
	//
	// 原因：daily_pnl = 当天累计已实现盈亏(REALIZED_PNL) + 当前浮动盈亏(unrealized)，
	// 是当天到写入时刻的累计值，而非每条快照的增量值。
	// 若用 AVG() 会把"当天从0增长到最终值"的所有中间值平均，严重低估实际收益。
	// 正确做法：取该时间段最后一条（时间最晚）快照的值，代表该段的完整盈亏。
	//
	// DISTINCT ON (account_id, period) + ORDER BY timestamp DESC 取每账户每段最后一条，
	// 再对所有账户求和得到该时段用户总盈亏。
	var truncExpr string
	switch granularity {
	case "hour":
		truncExpr = "date_trunc('hour', s.timestamp)"
	case "week":
		truncExpr = "date_trunc('week', s.timestamp)"
	case "month":
		truncExpr = "date_trunc('month', s.timestamp)"
	default:
		truncExpr = "date_trunc('day', s.timestamp)"
	}

	query := fmt.Sprintf(`
		WITH last_per_period AS (
			SELECT DISTINCT ON (a.account_id, %s)
				a.account_id,
				%s AS period,
				s.daily_pnl,
				s.unrealized_pnl
			FROM account_snapshots s
			JOIN accounts a ON a.account_id = s.account_id
			WHERE a.user_id = $1::uuid
			  AND s.timestamp >= $2
			  AND s.timestamp <= $3
			ORDER BY a.account_id, %s, s.timestamp DESC
		)
		SELECT period,
			COALESCE(SUM(daily_pnl), 0)       AS pnl,
			COALESCE(SUM(unrealized_pnl), 0)  AS unrealized_pnl,
			0::float                           AS fee,
			COUNT(*)                           AS account_count
		FROM last_per_period
		GROUP BY period
		ORDER BY period ASC
	`, truncExpr, truncExpr, truncExpr)

	rows, err := db.Pool().Query(ctx, query, targetUserID, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()

	type dataPoint struct {
		Period         time.Time `json:"period"`
		PnL            float64   `json:"pnl"`
		UnrealizedPnL  float64   `json:"unrealized_pnl"`
		Fee            float64   `json:"fee"`
		TradeCount     int       `json:"trade_count"`
		CumPnL         float64   `json:"cum_pnl"`
	}

	var points []dataPoint
	var cumPnL float64
	for rows.Next() {
		var dp dataPoint
		if err := rows.Scan(&dp.Period, &dp.PnL, &dp.UnrealizedPnL, &dp.Fee, &dp.TradeCount); err != nil {
			continue
		}
		cumPnL += dp.PnL
		dp.CumPnL = cumPnL
		points = append(points, dp)
	}
	if points == nil {
		points = []dataPoint{}
	}

	// Summary
	var totalPnL, totalFee float64
	var totalTrades int
	for _, p := range points {
		totalPnL += p.PnL
		totalFee += p.Fee
		totalTrades += p.TradeCount
	}

	c.JSON(http.StatusOK, gin.H{
		"user_id":     targetUserID,
		"granularity": granularity,
		"start":       start.Format("2006-01-02T15:04:05"),
		"end":         end.Format("2006-01-02T15:04:05"),
		"data":        points,
		"summary": gin.H{
			"total_pnl":    totalPnL,
			"total_fee":    totalFee,
			"total_trades": totalTrades,
			"net_profit":   totalPnL - totalFee,
		},
	})
}

// GetAllUsersProfitChart GET /api/v1/users/profit-chart/all
func GetAllUsersProfitChart(c *gin.Context) {
	granularity := c.DefaultQuery("granularity", "day")
	startStr := c.Query("start")
	endStr := c.Query("end")

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	callerID := c.GetString("user_id")
	if !isAdmin(ctx, callerID) {
		c.JSON(http.StatusForbidden, gin.H{"detail": "仅管理员可查看全员收益"})
		return
	}

	now := time.Now()
	var start, end time.Time
	if startStr != "" {
		if t, err := time.ParseInLocation("2006-01-02T15:04:05", startStr, time.FixedZone("CST", 8*3600)); err == nil {
			start = t
		} else if t2, err2 := time.ParseInLocation("2006-01-02", startStr, time.FixedZone("CST", 8*3600)); err2 == nil {
			start = t2
		}
	}
	if endStr != "" {
		if t, err := time.ParseInLocation("2006-01-02T15:04:05", endStr, time.FixedZone("CST", 8*3600)); err == nil {
			end = t
		} else if t2, err2 := time.ParseInLocation("2006-01-02", endStr, time.FixedZone("CST", 8*3600)); err2 == nil {
			end = t2.Add(24*time.Hour - time.Second)
		}
	}
	if start.IsZero() {
		switch granularity {
		case "hour":
			start = now.Add(-24 * time.Hour)
		case "week":
			start = now.AddDate(0, -3, 0)
		case "month":
			start = now.AddDate(-1, 0, 0)
		default:
			start = now.AddDate(0, -1, 0)
		}
	}
	if end.IsZero() {
		end = now
	}

	var truncExpr string
	switch granularity {
	case "hour":
		truncExpr = "date_trunc('hour', s.timestamp)"
	case "week":
		truncExpr = "date_trunc('week', s.timestamp)"
	case "month":
		truncExpr = "date_trunc('month', s.timestamp)"
	default:
		truncExpr = "date_trunc('day', s.timestamp)"
	}

	query := fmt.Sprintf(`
		WITH last_per_period AS (
			SELECT DISTINCT ON (a.user_id, a.account_id, %s)
				u.username,
				a.user_id::text AS user_id,
				a.account_id,
				%s AS period,
				s.daily_pnl
			FROM account_snapshots s
			JOIN accounts a ON a.account_id = s.account_id
			JOIN users u ON u.user_id = a.user_id
			WHERE s.timestamp >= $1
			  AND s.timestamp <= $2
			ORDER BY a.user_id, a.account_id, %s, s.timestamp DESC
		)
		SELECT username, user_id, period,
			COALESCE(SUM(daily_pnl), 0) AS pnl,
			COUNT(*) AS account_count
		FROM last_per_period
		GROUP BY username, user_id, period
		ORDER BY period ASC
	`, truncExpr, truncExpr, truncExpr)

	rows, err := db.Pool().Query(ctx, query, start, end)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()

	type row struct {
		Username   string    `json:"username"`
		UserID     string    `json:"user_id"`
		Period     time.Time `json:"period"`
		PnL        float64   `json:"pnl"`
		TradeCount int       `json:"trade_count"`
	}

	var data []row
	for rows.Next() {
		var r row
		if err := rows.Scan(&r.Username, &r.UserID, &r.Period, &r.PnL, &r.TradeCount); err != nil {
			continue
		}
		data = append(data, r)
	}
	if data == nil {
		data = []row{}
	}

	c.JSON(http.StatusOK, gin.H{
		"granularity": granularity,
		"start":       start.Format("2006-01-02T15:04:05"),
		"end":         end.Format("2006-01-02T15:04:05"),
		"data":        data,
	})
}

// Helper: check admin
func isAdmin(ctx context.Context, userID string) bool {
	var role string
	db.Pool().QueryRow(ctx, `SELECT role FROM users WHERE user_id=$1::uuid`, userID).Scan(&role)
	adminRoles := map[string]bool{
		"超级管理员": true, "系统管理员": true, "安全管理员": true,
		"管理员": true, "admin": true, "super_admin": true,
	}
	return adminRoles[role]
}

// ── Profit Chart V2 — Python 聚合接口（低频调用）─────────────────────────────
// GetUserProfitChartV2 GET /api/v1/users/:user_id/profit-chart-v2
//
// 直接代理到 Python /api/v1/trading/profit-chart-summary。
// Python 侧一次性拉取全量 income 数据后在内存按粒度聚合，
// Binance API 调用次数 = 13段(7天/段) × 3类型 = 39次，而非原来的 N天×7对×3类型。
func GetUserProfitChartV2(c *gin.Context) {
	targetUserID := c.Param("user_id")

	callerID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	if !isAdmin(ctx, callerID) && callerID != targetUserID {
		c.JSON(http.StatusForbidden, gin.H{"detail": "无权查看该用户收益"})
		return
	}

	// Forward all query params to Python
	rawQuery := c.Request.URL.RawQuery
	url := fmt.Sprintf("http://127.0.0.1:8000/api/v1/trading/profit-chart-summary?%s", rawQuery)

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	req.Header.Set("Authorization", c.GetHeader("Authorization"))

	resp, err := (&http.Client{Timeout: 55 * time.Second}).Do(req)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"detail": "profit summary service unavailable: " + err.Error()})
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, "application/json; charset=utf-8", body)
}
