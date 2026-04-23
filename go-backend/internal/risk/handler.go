package risk

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
	"hustle-go/internal/proxy"
)

// ── Risk Settings ──────────────────────────────────────────────────────────
//
// All threshold columns (binance_net_asset, forward_open_price, mt5_lag_count,
// etc.) are NULLABLE in the DB. NULL means "alert disabled for this metric".
// The Go scan code uses *float64 / *int so a NULL column maps to a JSON null,
// and the frontend treats null as "empty input" → user can clear the field
// to disable that specific alert.

type riskSettingsRow struct {
	SettingsID                  string    `json:"settings_id"`
	UserID                      string    `json:"user_id"`
	BinanceNetAsset             *float64  `json:"binanceNetAsset"`
	BybitMT5NetAsset            *float64  `json:"bybitMT5NetAsset"`
	TotalNetAsset               *float64  `json:"totalNetAsset"`
	BinanceLiquidationDistance  *float64  `json:"binanceLiquidationDistance"`
	BybitMT5LiquidationDistance *float64  `json:"bybitMT5LiquidationDistance"`
	MT5LagCount                 *int      `json:"mt5LagCount"`
	ReverseOpenPrice            *float64  `json:"reverseOpenPrice"`
	ReverseOpenSyncCount        *int      `json:"reverseOpenSyncCount"`
	ReverseClosePrice           *float64  `json:"reverseClosePrice"`
	ReverseCloseSyncCount       *int      `json:"reverseCloseSyncCount"`
	ForwardOpenPrice            *float64  `json:"forwardOpenPrice"`
	ForwardOpenSyncCount        *int      `json:"forwardOpenSyncCount"`
	ForwardClosePrice           *float64  `json:"forwardClosePrice"`
	ForwardCloseSyncCount       *int      `json:"forwardCloseSyncCount"`
	SpreadAlertSound            *string   `json:"spreadAlertSound"`
	SpreadAlertRepeatCount      int       `json:"spreadAlertRepeatCount"`
	NetAssetAlertSound          *string   `json:"netAssetAlertSound"`
	NetAssetAlertRepeatCount    int       `json:"netAssetAlertRepeatCount"`
	MT5AlertSound               *string   `json:"mt5AlertSound"`
	MT5AlertRepeatCount         int       `json:"mt5AlertRepeatCount"`
	LiquidationAlertSound       *string   `json:"liquidationAlertSound"`
	LiquidationAlertRepeatCount int       `json:"liquidationAlertRepeatCount"`
	SingleLegAlertSound         *string   `json:"singleLegAlertSound"`
	SingleLegAlertRepeatCount   int       `json:"singleLegAlertRepeatCount"`
	CreateTime                  time.Time `json:"create_time"`
	UpdateTime                  time.Time `json:"update_time"`
}

func scanRiskSettings(row interface{ Scan(...any) error }) (*riskSettingsRow, error) {
	r := &riskSettingsRow{}
	return r, row.Scan(
		&r.SettingsID, &r.UserID,
		&r.BinanceNetAsset, &r.BybitMT5NetAsset, &r.TotalNetAsset,
		&r.BinanceLiquidationDistance, &r.BybitMT5LiquidationDistance,
		&r.MT5LagCount,
		&r.ReverseOpenPrice, &r.ReverseOpenSyncCount,
		&r.ReverseClosePrice, &r.ReverseCloseSyncCount,
		&r.ForwardOpenPrice, &r.ForwardOpenSyncCount,
		&r.ForwardClosePrice, &r.ForwardCloseSyncCount,
		&r.SpreadAlertSound, &r.SpreadAlertRepeatCount,
		&r.NetAssetAlertSound, &r.NetAssetAlertRepeatCount,
		&r.MT5AlertSound, &r.MT5AlertRepeatCount,
		&r.LiquidationAlertSound, &r.LiquidationAlertRepeatCount,
		&r.SingleLegAlertSound, &r.SingleLegAlertRepeatCount,
		&r.CreateTime, &r.UpdateTime,
	)
}

const selectRiskSettings = `SELECT settings_id::text, user_id::text,
	binance_net_asset, bybit_mt5_net_asset, total_net_asset,
	binance_liquidation_price, bybit_mt5_liquidation_price,
	mt5_lag_count,
	reverse_open_price, reverse_open_sync_count,
	reverse_close_price, reverse_close_sync_count,
	forward_open_price, forward_open_sync_count,
	forward_close_price, forward_close_sync_count,
	spread_alert_sound, spread_alert_repeat_count,
	net_asset_alert_sound, net_asset_alert_repeat_count,
	mt5_alert_sound, mt5_alert_repeat_count,
	liquidation_alert_sound, liquidation_alert_repeat_count,
	single_leg_alert_sound, single_leg_alert_repeat_count,
	create_time, update_time
	FROM risk_settings`

// GetAlertSettings GET /api/v1/risk/alert-settings
func GetAlertSettings(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	r, err := scanRiskSettings(db.Pool().QueryRow(ctx,
		selectRiskSettings+` WHERE user_id=$1::uuid`, userID))
	if err != nil {
		// Return defaults if not found
		c.JSON(http.StatusOK, gin.H{})
		return
	}
	c.JSON(http.StatusOK, r)
}

// SaveAlertSettings POST /api/v1/risk/alert-settings
//
// Per-field semantics:
//   - field absent in payload  → keep current DB value
//   - field present with value → write the value
//   - field present with null  → write NULL (disable that alert)
//
// We parse the body as map[string]json.RawMessage to know exactly which keys
// are present and whether each is null. UPDATE is built dynamically so absent
// fields are not touched. This lets the user clear any individual threshold to
// disable that one alert without affecting the others.
func SaveAlertSettings(c *gin.Context) {
	userID := c.GetString("user_id")

	bodyBytes, err := c.GetRawData()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	var rawBody map[string]json.RawMessage
	if err := json.Unmarshal(bodyBytes, &rawBody); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}

	// Map JSON keys → DB columns + SQL cast type
	type fieldDef struct {
		dbCol string
		cast  string // "double precision", "integer", "varchar"
	}
	fields := []struct {
		jsonKey string
		def     fieldDef
	}{
		{"binanceNetAsset", fieldDef{"binance_net_asset", "double precision"}},
		{"bybitMT5NetAsset", fieldDef{"bybit_mt5_net_asset", "double precision"}},
		{"totalNetAsset", fieldDef{"total_net_asset", "double precision"}},
		{"binanceLiquidationDistance", fieldDef{"binance_liquidation_price", "double precision"}},
		{"bybitMT5LiquidationDistance", fieldDef{"bybit_mt5_liquidation_price", "double precision"}},
		{"mt5LagCount", fieldDef{"mt5_lag_count", "integer"}},
		{"reverseOpenPrice", fieldDef{"reverse_open_price", "double precision"}},
		{"reverseOpenSyncCount", fieldDef{"reverse_open_sync_count", "integer"}},
		{"reverseClosePrice", fieldDef{"reverse_close_price", "double precision"}},
		{"reverseCloseSyncCount", fieldDef{"reverse_close_sync_count", "integer"}},
		{"forwardOpenPrice", fieldDef{"forward_open_price", "double precision"}},
		{"forwardOpenSyncCount", fieldDef{"forward_open_sync_count", "integer"}},
		{"forwardClosePrice", fieldDef{"forward_close_price", "double precision"}},
		{"forwardCloseSyncCount", fieldDef{"forward_close_sync_count", "integer"}},
		{"spreadAlertSound", fieldDef{"spread_alert_sound", "varchar"}},
		{"spreadAlertRepeatCount", fieldDef{"spread_alert_repeat_count", "integer"}},
		{"netAssetAlertSound", fieldDef{"net_asset_alert_sound", "varchar"}},
		{"netAssetAlertRepeatCount", fieldDef{"net_asset_alert_repeat_count", "integer"}},
		{"mt5AlertSound", fieldDef{"mt5_alert_sound", "varchar"}},
		{"mt5AlertRepeatCount", fieldDef{"mt5_alert_repeat_count", "integer"}},
		{"liquidationAlertSound", fieldDef{"liquidation_alert_sound", "varchar"}},
		{"liquidationAlertRepeatCount", fieldDef{"liquidation_alert_repeat_count", "integer"}},
		{"singleLegAlertSound", fieldDef{"single_leg_alert_sound", "varchar"}},
		{"singleLegAlertRepeatCount", fieldDef{"single_leg_alert_repeat_count", "integer"}},
	}

	var setParts []string
	args := []any{userID}
	argIdx := 2
	for _, f := range fields {
		rawVal, present := rawBody[f.jsonKey]
		if !present {
			continue
		}
		if string(rawVal) == "null" {
			setParts = append(setParts, fmt.Sprintf("%s=NULL", f.def.dbCol))
			continue
		}
		switch f.def.cast {
		case "double precision":
			var v float64
			if err := json.Unmarshal(rawVal, &v); err != nil {
				continue
			}
			args = append(args, v)
			setParts = append(setParts, fmt.Sprintf("%s=$%d::double precision", f.def.dbCol, argIdx))
			argIdx++
		case "integer":
			var v int
			if err := json.Unmarshal(rawVal, &v); err != nil {
				continue
			}
			args = append(args, v)
			setParts = append(setParts, fmt.Sprintf("%s=$%d::integer", f.def.dbCol, argIdx))
			argIdx++
		case "varchar":
			var v string
			if err := json.Unmarshal(rawVal, &v); err != nil {
				continue
			}
			args = append(args, v)
			setParts = append(setParts, fmt.Sprintf("%s=$%d::varchar", f.def.dbCol, argIdx))
			argIdx++
		}
	}

	if len(setParts) == 0 {
		c.JSON(http.StatusOK, gin.H{"message": "No fields to update"})
		return
	}
	setParts = append(setParts, "update_time=NOW()")

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Try UPDATE first
	updateSQL := fmt.Sprintf("UPDATE risk_settings SET %s WHERE user_id=$1::uuid AND pair_code='XAU'", strings.Join(setParts, ", "))
	tag, err := db.Pool().Exec(ctx, updateSQL, args...)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	// If no row exists yet, INSERT a default row and re-run the UPDATE
	if tag.RowsAffected() == 0 {
		_, err := db.Pool().Exec(ctx,
			`INSERT INTO risk_settings (user_id, pair_code) VALUES ($1::uuid, 'XAU') ON CONFLICT (user_id, pair_code) DO NOTHING`,
			userID)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
			return
		}
		if _, err := db.Pool().Exec(ctx, updateSQL, args...); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
			return
		}
	}

	c.JSON(http.StatusOK, gin.H{"message": "Alert settings saved successfully"})
}

// ── Risk Alerts ────────────────────────────────────────────────────────────

// GetAlerts GET /api/v1/risk/alerts
func GetAlerts(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := db.Pool().Query(ctx,
		`SELECT alert_id::text, alert_level, alert_message, create_time, expire_time
		 FROM risk_alerts WHERE user_id=$1::uuid
		 AND (expire_time IS NULL OR expire_time > NOW())
		 ORDER BY create_time DESC`, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var alerts []gin.H
	for rows.Next() {
		var id, level, msg string
		var createTime time.Time
		var expireTime *time.Time
		rows.Scan(&id, &level, &msg, &createTime, &expireTime)
		a := gin.H{
			"alert_id":    id,
			"level":       level,
			"message":     msg,
			"create_time": createTime,
			"expire_time": expireTime,
		}
		alerts = append(alerts, a)
	}
	if alerts == nil {
		alerts = []gin.H{}
	}
	c.JSON(http.StatusOK, alerts)
}

// ClearExpiredAlerts DELETE /api/v1/risk/alerts/expired
func ClearExpiredAlerts(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	db.Pool().Exec(ctx, `DELETE FROM risk_alerts WHERE expire_time IS NOT NULL AND expire_time <= NOW()`)
	c.JSON(http.StatusOK, gin.H{"message": "Expired alerts cleared"})
}

// ── Emergency Stop (Redis-backed) ──────────────────────────────────────────

const emergencyStopKey = "emergency_stop"

// GetEmergencyStopStatus GET /api/v1/risk/emergency-stop/status
func GetEmergencyStopStatus(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	val, err := db.Redis().Get(ctx, emergencyStopKey).Result()
	active := err == nil && val == "1"
	c.JSON(http.StatusOK, gin.H{"active": active})
}

// ActivateEmergencyStop POST /api/v1/risk/emergency-stop/activate
func ActivateEmergencyStop(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	db.Redis().Set(ctx, emergencyStopKey, "1", 0)
	c.JSON(http.StatusOK, gin.H{"message": "Emergency stop activated", "active": true})
}

// DeactivateEmergencyStop POST /api/v1/risk/emergency-stop/deactivate
func DeactivateEmergencyStop(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	db.Redis().Del(ctx, emergencyStopKey)
	c.JSON(http.StatusOK, gin.H{"message": "Emergency stop deactivated", "active": false})
}

// GetRiskStatus GET /api/v1/risk/status
func GetRiskStatus(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	val, err := db.Redis().Get(ctx, emergencyStopKey).Result()
	emergencyStop := err == nil && val == "1"

	var activeAlerts int
	db.Pool().QueryRow(ctx,
		`SELECT COUNT(*) FROM risk_alerts WHERE user_id=$1::uuid AND (expire_time IS NULL OR expire_time > NOW())`,
		userID).Scan(&activeAlerts)

	c.JSON(http.StatusOK, gin.H{
		"emergency_stop_active": emergencyStop,
		"active_alerts":         activeAlerts,
		"mt5_status":            "正常",
	})
}

// ProxyToRiskMT5Stuck GET /api/v1/risk/mt5/stuck — proxy to Python
func ProxyToRiskMT5Stuck(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/risk/mt5/stuck")
}

// ProxyToAccountRisk GET /api/v1/risk/account/:account_id/risk — proxy to Python
func ProxyToAccountRisk(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/risk/account/"+c.Param("account_id")+"/risk")
}

// ProxyToAlertSoundUpload POST /api/v1/risk/alert-sound/upload — proxy to Python
func ProxyToAlertSoundUpload(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/risk/alert-sound/upload")
}
