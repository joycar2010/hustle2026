package strategies

import (
	"bytes"
	"io"
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
)

type strategyRow struct {
	ID        int             `json:"id"`
	UserID    string          `json:"user_id"`
	Name      string          `json:"name"`
	Symbol    string          `json:"symbol"`
	Direction string          `json:"direction"`
	MinSpread float64         `json:"min_spread"`
	Status    string          `json:"status"`
	Params    json.RawMessage `json:"params"`
	CreatedAt time.Time       `json:"created_at"`
	UpdatedAt time.Time       `json:"updated_at"`
}

const selectStrategy = `SELECT id, user_id::text, name, symbol, direction,
	min_spread, status, COALESCE(params::text,'{}')::json, created_at, updated_at
	FROM strategies`

func scanStrategy(row interface{ Scan(...any) error }) (*strategyRow, error) {
	s := &strategyRow{}
	return s, row.Scan(&s.ID, &s.UserID, &s.Name, &s.Symbol, &s.Direction,
		&s.MinSpread, &s.Status, &s.Params, &s.CreatedAt, &s.UpdatedAt)
}

// ListStrategies GET /api/v1/strategies
func ListStrategies(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := db.Pool().Query(ctx, selectStrategy+` WHERE user_id=$1::uuid ORDER BY created_at DESC`, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var strategies []*strategyRow
	for rows.Next() {
		s, err := scanStrategy(rows)
		if err == nil {
			strategies = append(strategies, s)
		}
	}
	if strategies == nil {
		strategies = []*strategyRow{}
	}
	c.JSON(http.StatusOK, strategies)
}

// GetStrategy GET /api/v1/strategies/:id
func GetStrategy(c *gin.Context) {
	userID := c.GetString("user_id")
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "Invalid strategy id"})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	s, err := scanStrategy(db.Pool().QueryRow(ctx,
		selectStrategy+` WHERE id=$1 AND user_id=$2::uuid`, id, userID))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Strategy not found"})
		return
	}
	c.JSON(http.StatusOK, s)
}

// CreateStrategy POST /api/v1/strategies
func CreateStrategy(c *gin.Context) {
	userID := c.GetString("user_id")
	var body struct {
		Name      string          `json:"name" binding:"required"`
		Symbol    string          `json:"symbol" binding:"required"`
		Direction string          `json:"direction" binding:"required"`
		MinSpread float64         `json:"min_spread"`
		Status    string          `json:"status"`
		Params    json.RawMessage `json:"params"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	status := "inactive"
	if body.Status != "" {
		status = body.Status
	}
	params := json.RawMessage(`{}`)
	if body.Params != nil {
		params = body.Params
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	s, err := scanStrategy(db.Pool().QueryRow(ctx,
		`INSERT INTO strategies (user_id, name, symbol, direction, min_spread, status, params, created_at, updated_at)
		 VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, NOW(), NOW())
		 RETURNING id, user_id::text, name, symbol, direction, min_spread, status,
		   COALESCE(params::text,'{}')::json, created_at, updated_at`,
		userID, body.Name, body.Symbol, body.Direction, body.MinSpread, status, params))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, s)
}

// UpdateStrategy PUT /api/v1/strategies/:id
func UpdateStrategy(c *gin.Context) {
	userID := c.GetString("user_id")
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "Invalid strategy id"})
		return
	}
	var body struct {
		Name      *string         `json:"name"`
		Symbol    *string         `json:"symbol"`
		Direction *string         `json:"direction"`
		MinSpread *float64        `json:"min_spread"`
		Status    *string         `json:"status"`
		Params    json.RawMessage `json:"params"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	var exists bool
	db.Pool().QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM strategies WHERE id=$1 AND user_id=$2::uuid)`, id, userID).Scan(&exists)
	if !exists {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Strategy not found"})
		return
	}

	if body.Name != nil {
		db.Pool().Exec(ctx, `UPDATE strategies SET name=$1, updated_at=NOW() WHERE id=$2`, *body.Name, id)
	}
	if body.Symbol != nil {
		db.Pool().Exec(ctx, `UPDATE strategies SET symbol=$1, updated_at=NOW() WHERE id=$2`, *body.Symbol, id)
	}
	if body.Direction != nil {
		db.Pool().Exec(ctx, `UPDATE strategies SET direction=$1, updated_at=NOW() WHERE id=$2`, *body.Direction, id)
	}
	if body.MinSpread != nil {
		db.Pool().Exec(ctx, `UPDATE strategies SET min_spread=$1, updated_at=NOW() WHERE id=$2`, *body.MinSpread, id)
	}
	if body.Status != nil {
		db.Pool().Exec(ctx, `UPDATE strategies SET status=$1, updated_at=NOW() WHERE id=$2`, *body.Status, id)
	}
	if body.Params != nil {
		db.Pool().Exec(ctx, `UPDATE strategies SET params=$1, updated_at=NOW() WHERE id=$2`, body.Params, id)
	}

	s, err := scanStrategy(db.Pool().QueryRow(ctx, selectStrategy+` WHERE id=$1`, id))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, s)
}

// DeleteStrategy DELETE /api/v1/strategies/:id
func DeleteStrategy(c *gin.Context) {
	userID := c.GetString("user_id")
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "Invalid strategy id"})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	tag, err := db.Pool().Exec(ctx, `DELETE FROM strategies WHERE id=$1 AND user_id=$2::uuid`, id, userID)
	if err != nil || tag.RowsAffected() == 0 {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Strategy not found"})
		return
	}
	c.Status(http.StatusNoContent)
}

// ── Strategy Configs (timing-configs) ─────────────────────────────────────

type strategyConfigRow struct {
	ConfigID          string          `json:"config_id"`
	UserID            string          `json:"user_id"`
	StrategyType      string          `json:"strategy_type"`
	TargetSpread      float64         `json:"target_spread"`
	OrderQty          float64         `json:"order_qty"`
	RetryTimes        int             `json:"retry_times"`
	MT5StuckThreshold int             `json:"mt5_stuck_threshold"`
	IsEnabled         bool            `json:"is_enabled"`
	OpeningSyncCount  int             `json:"opening_sync_count"`
	ClosingSyncCount  int             `json:"closing_sync_count"`
	MCoin             float64         `json:"m_coin"`
	Ladders           json.RawMessage `json:"ladders"`
	OpeningMCoin      float64         `json:"opening_m_coin"`
	ClosingMCoin      float64         `json:"closing_m_coin"`
	CreateTime        time.Time       `json:"create_time"`
	UpdateTime        time.Time       `json:"update_time"`
}

const selectConfig = `SELECT config_id::text, user_id::text, strategy_type,
	target_spread, order_qty, retry_times, mt5_stuck_threshold, is_enabled,
	opening_sync_count, closing_sync_count, m_coin, ladders,
	opening_m_coin, closing_m_coin, create_time, update_time
	FROM strategy_configs`

func scanConfig(row interface{ Scan(...any) error }) (*strategyConfigRow, error) {
	r := &strategyConfigRow{}
	return r, row.Scan(
		&r.ConfigID, &r.UserID, &r.StrategyType,
		&r.TargetSpread, &r.OrderQty, &r.RetryTimes, &r.MT5StuckThreshold, &r.IsEnabled,
		&r.OpeningSyncCount, &r.ClosingSyncCount, &r.MCoin, &r.Ladders,
		&r.OpeningMCoin, &r.ClosingMCoin, &r.CreateTime, &r.UpdateTime,
	)
}

// ListStrategyConfigs GET /api/v1/strategies/configs
func ListStrategyConfigs(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := db.Pool().Query(ctx, selectConfig+` WHERE user_id=$1::uuid ORDER BY create_time`, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var configs []*strategyConfigRow
	for rows.Next() {
		r, err := scanConfig(rows)
		if err == nil {
			configs = append(configs, r)
		}
	}
	if configs == nil {
		configs = []*strategyConfigRow{}
	}
	c.JSON(http.StatusOK, configs)
}

// GetStrategyConfig GET /api/v1/strategies/configs/:config_id
func GetStrategyConfig(c *gin.Context) {
	userID := c.GetString("user_id")
	configID := c.Param("config_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	r, err := scanConfig(db.Pool().QueryRow(ctx,
		selectConfig+` WHERE config_id=$1::uuid AND user_id=$2::uuid`, configID, userID))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Config not found"})
		return
	}
	c.JSON(http.StatusOK, r)
}

// GetStrategyConfigByType GET /api/v1/strategies/configs/by-type/:strategy_type
func GetStrategyConfigByType(c *gin.Context) {
	userID := c.GetString("user_id")
	strategyType := c.Param("strategy_type")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	r, err := scanConfig(db.Pool().QueryRow(ctx,
		selectConfig+` WHERE user_id=$1::uuid AND strategy_type=$2`, userID, strategyType))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Config not found"})
		return
	}
	c.JSON(http.StatusOK, r)
}

// UpsertStrategyConfig PUT /api/v1/strategies/configs/:strategy_type
func UpsertStrategyConfig(c *gin.Context) {
	userID := c.GetString("user_id")
	strategyType := c.Param("strategy_type")
	var body struct {
		TargetSpread      *float64        `json:"target_spread"`
		OrderQty          *float64        `json:"order_qty"`
		RetryTimes        *int            `json:"retry_times"`
		MT5StuckThreshold *int            `json:"mt5_stuck_threshold"`
		IsEnabled         *bool           `json:"is_enabled"`
		OpeningSyncCount  *int            `json:"opening_sync_count"`
		ClosingSyncCount  *int            `json:"closing_sync_count"`
		MCoin             *float64        `json:"m_coin"`
		Ladders           json.RawMessage `json:"ladders"`
		OpeningMCoin      *float64        `json:"opening_m_coin"`
		ClosingMCoin      *float64        `json:"closing_m_coin"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Check if exists
	var configID string
	db.Pool().QueryRow(ctx,
		`SELECT config_id::text FROM strategy_configs WHERE user_id=$1::uuid AND strategy_type=$2`,
		userID, strategyType).Scan(&configID)

	if configID == "" {
		// Insert with defaults
		ts := 1.0
		if body.TargetSpread != nil {
			ts = *body.TargetSpread
		}
		qty := 1.0
		if body.OrderQty != nil {
			qty = *body.OrderQty
		}
		retry := 3
		if body.RetryTimes != nil {
			retry = *body.RetryTimes
		}
		mt5 := 5
		if body.MT5StuckThreshold != nil {
			mt5 = *body.MT5StuckThreshold
		}
		enabled := false
		if body.IsEnabled != nil {
			enabled = *body.IsEnabled
		}
		openSync := 3
		if body.OpeningSyncCount != nil {
			openSync = *body.OpeningSyncCount
		}
		closeSync := 3
		if body.ClosingSyncCount != nil {
			closeSync = *body.ClosingSyncCount
		}
		mCoin := 5.0
		if body.MCoin != nil {
			mCoin = *body.MCoin
		}
		ladders := json.RawMessage(`[]`)
		if body.Ladders != nil {
			ladders = body.Ladders
		}
		openM := ts
		if body.OpeningMCoin != nil {
			openM = *body.OpeningMCoin
		}
		closeM := ts
		if body.ClosingMCoin != nil {
			closeM = *body.ClosingMCoin
		}
		r, err := scanConfig(db.Pool().QueryRow(ctx,
			`INSERT INTO strategy_configs
			(config_id, user_id, strategy_type, target_spread, order_qty, retry_times,
			 mt5_stuck_threshold, is_enabled, opening_sync_count, closing_sync_count,
			 m_coin, ladders, opening_m_coin, closing_m_coin, create_time, update_time)
			VALUES (gen_random_uuid(),$1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW(),NOW())
			RETURNING config_id::text, user_id::text, strategy_type,
			  target_spread, order_qty, retry_times, mt5_stuck_threshold, is_enabled,
			  opening_sync_count, closing_sync_count, m_coin, ladders,
			  opening_m_coin, closing_m_coin, create_time, update_time`,
			userID, strategyType, ts, qty, retry, mt5, enabled, openSync, closeSync,
			mCoin, ladders, openM, closeM))
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
			return
		}
		c.JSON(http.StatusCreated, r)
		return
	}

	// Update existing
	if body.TargetSpread != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET target_spread=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.TargetSpread, configID)
	}
	if body.OrderQty != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET order_qty=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.OrderQty, configID)
	}
	if body.RetryTimes != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET retry_times=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.RetryTimes, configID)
	}
	if body.MT5StuckThreshold != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET mt5_stuck_threshold=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.MT5StuckThreshold, configID)
	}
	if body.IsEnabled != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET is_enabled=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.IsEnabled, configID)
	}
	if body.OpeningSyncCount != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET opening_sync_count=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.OpeningSyncCount, configID)
	}
	if body.ClosingSyncCount != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET closing_sync_count=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.ClosingSyncCount, configID)
	}
	if body.MCoin != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET m_coin=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.MCoin, configID)
	}
	if body.Ladders != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET ladders=$1, update_time=NOW() WHERE config_id=$2::uuid`, body.Ladders, configID)
	}
	if body.OpeningMCoin != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET opening_m_coin=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.OpeningMCoin, configID)
	}
	if body.ClosingMCoin != nil {
		db.Pool().Exec(ctx, `UPDATE strategy_configs SET closing_m_coin=$1, update_time=NOW() WHERE config_id=$2::uuid`, *body.ClosingMCoin, configID)
	}

	r, err := scanConfig(db.Pool().QueryRow(ctx, selectConfig+` WHERE config_id=$1::uuid`, configID))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, r)
}

// UpsertStrategyConfigByBody POST /api/v1/strategies/configs/upsert
// Reads strategy_type from the JSON body (frontend compatibility shim)
func UpsertStrategyConfigByBody(c *gin.Context) {
	// Peek at strategy_type from body
	var peek struct {
		StrategyType string `json:"strategy_type"`
	}
	body, err := c.GetRawData()
	if err != nil || len(body) == 0 {
		c.JSON(422, gin.H{"detail": "missing body"})
		return
	}
	if err := json.Unmarshal(body, &peek); err != nil || peek.StrategyType == "" {
		c.JSON(422, gin.H{"detail": "strategy_type required in body"})
		return
	}
	// Re-inject body so ShouldBindJSON can read it
	c.Request.Body = io.NopCloser(bytes.NewReader(body))
	// Override URL param
	paramsMap := gin.Params{{Key: "strategy_type", Value: peek.StrategyType}}
	c.Params = append(paramsMap, c.Params...)
	UpsertStrategyConfig(c)
}
