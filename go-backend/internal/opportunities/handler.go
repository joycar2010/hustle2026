package opportunities

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
	"hustle-go/internal/proxy"
)

type opportunityRow struct {
	ID              string    `json:"id"`
	Symbol          string    `json:"symbol"`
	BinanceBid      float64   `json:"binance_bid"`
	BinanceAsk      float64   `json:"binance_ask"`
	BybitBid        float64   `json:"bybit_bid"`
	BybitAsk        float64   `json:"bybit_ask"`
	ForwardSpread   float64   `json:"forward_spread"`
	ReverseSpread   float64   `json:"reverse_spread"`
	OpportunityType string    `json:"opportunity_type"`
	TargetSpread    float64   `json:"target_spread"`
	Timestamp       time.Time `json:"timestamp"`
}

// List GET /api/v1/opportunities
func List(c *gin.Context) {
	symbol := c.DefaultQuery("symbol", "XAUUSDT")
	oppType := c.Query("opportunity_type")
	startTime := c.Query("start_time")
	endTime := c.Query("end_time")
	limit := 1000
	if v := c.Query("limit"); v != "" {
		if n, err := parseInt(v); err == nil && n > 0 && n <= 10000 {
			limit = n
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	query := `SELECT id::text, symbol, binance_bid, binance_ask, bybit_bid, bybit_ask,
		forward_spread, reverse_spread, opportunity_type, target_spread, timestamp
		FROM arbitrage_opportunities WHERE symbol=$1`
	args := []interface{}{symbol}
	idx := 2

	if startTime != "" {
		query += " AND timestamp >= $" + itoa(idx)
		args = append(args, startTime)
		idx++
	}
	if endTime != "" {
		query += " AND timestamp <= $" + itoa(idx)
		args = append(args, endTime)
		idx++
	}
	if oppType != "" {
		query += " AND opportunity_type = $" + itoa(idx)
		args = append(args, oppType)
		idx++
	}
	query += " ORDER BY timestamp DESC LIMIT $" + itoa(idx)
	args = append(args, limit)

	rows, err := db.Pool().Query(ctx, query, args...)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()

	var opps []*opportunityRow
	for rows.Next() {
		o := &opportunityRow{}
		if err := rows.Scan(&o.ID, &o.Symbol, &o.BinanceBid, &o.BinanceAsk,
			&o.BybitBid, &o.BybitAsk, &o.ForwardSpread, &o.ReverseSpread,
			&o.OpportunityType, &o.TargetSpread, &o.Timestamp); err == nil {
			opps = append(opps, o)
		}
	}
	if opps == nil {
		opps = []*opportunityRow{}
	}
	c.JSON(http.StatusOK, opps)
}

// Stats GET /api/v1/opportunities/stats
func Stats(c *gin.Context) {
	symbol := c.DefaultQuery("symbol", "XAUUSDT")
	startTime := c.Query("start_time")
	endTime := c.Query("end_time")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	where := "WHERE symbol=$1"
	args := []interface{}{symbol}
	idx := 2
	if startTime != "" {
		where += " AND timestamp >= $" + itoa(idx)
		args = append(args, startTime)
		idx++
	}
	if endTime != "" {
		where += " AND timestamp <= $" + itoa(idx)
		args = append(args, endTime)
		idx++
	}

	// Aggregate query using FILTER
	aggSQL := `SELECT
		COUNT(*),
		COUNT(*) FILTER (WHERE opportunity_type='forward_open'),
		COUNT(*) FILTER (WHERE opportunity_type='forward_close'),
		COUNT(*) FILTER (WHERE opportunity_type='reverse_open'),
		COUNT(*) FILTER (WHERE opportunity_type='reverse_close'),
		COALESCE(AVG(forward_spread),0),
		COALESCE(AVG(reverse_spread),0),
		COALESCE(MAX(forward_spread),0),
		COALESCE(MAX(reverse_spread),0)
		FROM arbitrage_opportunities ` + where

	var total, fwdOpen, fwdClose, revOpen, revClose int64
	var avgFwd, avgRev, maxFwd, maxRev float64
	err := db.Pool().QueryRow(ctx, aggSQL, args...).Scan(
		&total, &fwdOpen, &fwdClose, &revOpen, &revClose,
		&avgFwd, &avgRev, &maxFwd, &maxRev,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"total_count":        total,
		"forward_open_count": fwdOpen,
		"forward_close_count": fwdClose,
		"reverse_open_count": revOpen,
		"reverse_close_count": revClose,
		"avg_forward_spread": avgFwd,
		"avg_reverse_spread": avgRev,
		"max_forward_spread": maxFwd,
		"max_reverse_spread": maxRev,
	})
}

// Extract POST /api/v1/opportunities/extract — proxy to Python (complex extraction logic)
func Extract(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/opportunities/extract")
}

// Cleanup POST /api/v1/opportunities/cleanup
func Cleanup(c *gin.Context) {
	spreadDays := 1
	oppDays := 30
	if v := c.Query("spread_days"); v != "" {
		if n, err := parseInt(v); err == nil && n > 0 {
			spreadDays = n
		}
	}
	if v := c.Query("opportunity_days"); v != "" {
		if n, err := parseInt(v); err == nil && n > 0 {
			oppDays = n
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	spreadInterval := itoa(spreadDays) + " days"
	oppInterval := itoa(oppDays) + " days"

	tag1, err1 := db.Pool().Exec(ctx,
		`DELETE FROM spread_records WHERE timestamp < NOW() - $1::interval`, spreadInterval)
	tag2, err2 := db.Pool().Exec(ctx,
		`DELETE FROM arbitrage_opportunities WHERE timestamp < NOW() - $1::interval`, oppInterval)

	spreadDeleted := int64(0)
	oppDeleted := int64(0)
	if err1 == nil {
		spreadDeleted = tag1.RowsAffected()
	}
	if err2 == nil {
		oppDeleted = tag2.RowsAffected()
	}

	c.JSON(http.StatusOK, gin.H{
		"spread_records_deleted":    spreadDeleted,
		"opportunities_deleted":     oppDeleted,
	})
}

func parseInt(s string) (int, error) {
	n := 0
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, &parseError{}
		}
		n = n*10 + int(c-'0')
	}
	return n, nil
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	buf := [20]byte{}
	pos := 20
	for n > 0 {
		pos--
		buf[pos] = byte('0' + n%10)
		n /= 10
	}
	return string(buf[pos:])
}

type parseError struct{}

func (e *parseError) Error() string { return "parse error" }
