package timingconfigs

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
)

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

// ListTimingConfigs GET /api/v1/timing-configs
func ListTimingConfigs(c *gin.Context) {
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

// GetTimingConfig GET /api/v1/timing-configs/:config_id
func GetTimingConfig(c *gin.Context) {
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

// CreateTimingConfig POST /api/v1/timing-configs
func CreateTimingConfig(c *gin.Context) {
	userID := c.GetString("user_id")
	var body struct {
		StrategyType      string          `json:"strategy_type" binding:"required"`
		TargetSpread      float64         `json:"target_spread" binding:"required"`
		OrderQty          float64         `json:"order_qty" binding:"required"`
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

	retryTimes := 3
	if body.RetryTimes != nil {
		retryTimes = *body.RetryTimes
	}
	mt5Stuck := 5
	if body.MT5StuckThreshold != nil {
		mt5Stuck = *body.MT5StuckThreshold
	}
	isEnabled := false
	if body.IsEnabled != nil {
		isEnabled = *body.IsEnabled
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
	openMCoin := body.TargetSpread
	if body.OpeningMCoin != nil {
		openMCoin = *body.OpeningMCoin
	}
	closeMCoin := body.TargetSpread
	if body.ClosingMCoin != nil {
		closeMCoin = *body.ClosingMCoin
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	r, err := scanConfig(db.Pool().QueryRow(ctx,
		`INSERT INTO strategy_configs
		(config_id, user_id, strategy_type, target_spread, order_qty, retry_times,
		 mt5_stuck_threshold, is_enabled, opening_sync_count, closing_sync_count,
		 m_coin, ladders, opening_m_coin, closing_m_coin, create_time, update_time)
		VALUES (gen_random_uuid(), $1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW(), NOW())
		RETURNING config_id::text, user_id::text, strategy_type,
		  target_spread, order_qty, retry_times, mt5_stuck_threshold, is_enabled,
		  opening_sync_count, closing_sync_count, m_coin, ladders,
		  opening_m_coin, closing_m_coin, create_time, update_time`,
		userID, body.StrategyType, body.TargetSpread, body.OrderQty,
		retryTimes, mt5Stuck, isEnabled, openSync, closeSync,
		mCoin, ladders, openMCoin, closeMCoin,
	))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, r)
}

// UpdateTimingConfig PUT /api/v1/timing-configs/:config_id
func UpdateTimingConfig(c *gin.Context) {
	userID := c.GetString("user_id")
	configID := c.Param("config_id")
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

	// Verify ownership
	var exists bool
	db.Pool().QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM strategy_configs WHERE config_id=$1::uuid AND user_id=$2::uuid)`,
		configID, userID).Scan(&exists)
	if !exists {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Config not found"})
		return
	}

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

// DeleteTimingConfig DELETE /api/v1/timing-configs/:config_id
func DeleteTimingConfig(c *gin.Context) {
	userID := c.GetString("user_id")
	configID := c.Param("config_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	tag, err := db.Pool().Exec(ctx,
		`DELETE FROM strategy_configs WHERE config_id=$1::uuid AND user_id=$2::uuid`, configID, userID)
	if err != nil || tag.RowsAffected() == 0 {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Config not found"})
		return
	}
	c.Status(http.StatusNoContent)
}

// GetTimingConfigByType GET /api/v1/timing-configs/by-type/:strategy_type
func GetTimingConfigByType(c *gin.Context) {
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

// GetTimingConfigEffective GET /api/v1/timing-configs/effective/:strategy_type
func GetTimingConfigEffective(c *gin.Context) {
	userID := c.GetString("user_id")
	strategyType := c.Param("strategy_type")
	instanceIDStr := c.Query("instance_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Try instance level first if instance_id provided
	if instanceIDStr != "" {
		instanceID, _ := strconv.Atoi(instanceIDStr)
		_ = instanceID
	}

	// Fall back to strategy_type level
	r, err := scanConfig(db.Pool().QueryRow(ctx,
		selectConfig+` WHERE user_id=$1::uuid AND strategy_type=$2`, userID, strategyType))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Config not found"})
		return
	}
	c.JSON(http.StatusOK, r)
}
