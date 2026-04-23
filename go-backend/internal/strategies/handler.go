package strategies

import (
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

