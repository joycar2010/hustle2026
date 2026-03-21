package risk

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
	"hustle-go/internal/proxy"
)

// ── Risk Settings ──────────────────────────────────────────────────────────

type riskSettingsRow struct {
	SettingsID                  string    `json:"settings_id"`
	UserID                      string    `json:"user_id"`
	BinanceNetAsset             float64   `json:"binanceNetAsset"`
	BybitMT5NetAsset            float64   `json:"bybitMT5NetAsset"`
	TotalNetAsset               float64   `json:"totalNetAsset"`
	BinanceLiquidationDistance  float64   `json:"binanceLiquidationDistance"`
	BybitMT5LiquidationDistance float64   `json:"bybitMT5LiquidationDistance"`
	MT5LagCount                 int       `json:"mt5LagCount"`
	ReverseOpenPrice            float64   `json:"reverseOpenPrice"`
	ReverseOpenSyncCount        int       `json:"reverseOpenSyncCount"`
	ReverseClosePrice           float64   `json:"reverseClosePrice"`
	ReverseCloseSyncCount       int       `json:"reverseCloseSyncCount"`
	ForwardOpenPrice            float64   `json:"forwardOpenPrice"`
	ForwardOpenSyncCount        int       `json:"forwardOpenSyncCount"`
	ForwardClosePrice           float64   `json:"forwardClosePrice"`
	ForwardCloseSyncCount       int       `json:"forwardCloseSyncCount"`
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
func SaveAlertSettings(c *gin.Context) {
	userID := c.GetString("user_id")
	var body struct {
		BinanceNetAsset             *float64 `json:"binanceNetAsset"`
		BybitMT5NetAsset            *float64 `json:"bybitMT5NetAsset"`
		TotalNetAsset               *float64 `json:"totalNetAsset"`
		BinanceLiquidationDistance  *float64 `json:"binanceLiquidationDistance"`
		BybitMT5LiquidationDistance *float64 `json:"bybitMT5LiquidationDistance"`
		MT5LagCount                 *int     `json:"mt5LagCount"`
		ReverseOpenPrice            *float64 `json:"reverseOpenPrice"`
		ReverseOpenSyncCount        *int     `json:"reverseOpenSyncCount"`
		ReverseClosePrice           *float64 `json:"reverseClosePrice"`
		ReverseCloseSyncCount       *int     `json:"reverseCloseSyncCount"`
		ForwardOpenPrice            *float64 `json:"forwardOpenPrice"`
		ForwardOpenSyncCount        *int     `json:"forwardOpenSyncCount"`
		ForwardClosePrice           *float64 `json:"forwardClosePrice"`
		ForwardCloseSyncCount       *int     `json:"forwardCloseSyncCount"`
		SpreadAlertSound            *string  `json:"spreadAlertSound"`
		SpreadAlertRepeatCount      *int     `json:"spreadAlertRepeatCount"`
		NetAssetAlertSound          *string  `json:"netAssetAlertSound"`
		NetAssetAlertRepeatCount    *int     `json:"netAssetAlertRepeatCount"`
		MT5AlertSound               *string  `json:"mt5AlertSound"`
		MT5AlertRepeatCount         *int     `json:"mt5AlertRepeatCount"`
		LiquidationAlertSound       *string  `json:"liquidationAlertSound"`
		LiquidationAlertRepeatCount *int     `json:"liquidationAlertRepeatCount"`
		SingleLegAlertSound         *string  `json:"singleLegAlertSound"`
		SingleLegAlertRepeatCount   *int     `json:"singleLegAlertRepeatCount"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	_, err := db.Pool().Exec(ctx,
		`INSERT INTO risk_settings (user_id,
			binance_net_asset, bybit_mt5_net_asset, total_net_asset,
			binance_liquidation_price, bybit_mt5_liquidation_price, mt5_lag_count,
			reverse_open_price, reverse_open_sync_count,
			reverse_close_price, reverse_close_sync_count,
			forward_open_price, forward_open_sync_count,
			forward_close_price, forward_close_sync_count,
			spread_alert_sound, spread_alert_repeat_count,
			net_asset_alert_sound, net_asset_alert_repeat_count,
			mt5_alert_sound, mt5_alert_repeat_count,
			liquidation_alert_sound, liquidation_alert_repeat_count,
			single_leg_alert_sound, single_leg_alert_repeat_count)
		VALUES ($1::uuid,
			COALESCE($2,10000), COALESCE($3,10000), COALESCE($4,20000),
			COALESCE($5,2000), COALESCE($6,2000), COALESCE($7,5),
			COALESCE($8,0.5), COALESCE($9,3),
			COALESCE($10,0.2), COALESCE($11,3),
			COALESCE($12,0.5), COALESCE($13,3),
			COALESCE($14,0.2), COALESCE($15,3),
			$16, COALESCE($17,3),
			$18, COALESCE($19,3),
			$20, COALESCE($21,3),
			$22, COALESCE($23,3),
			$24, COALESCE($25,3))
		ON CONFLICT (user_id) DO UPDATE SET
			binance_net_asset=COALESCE($2, risk_settings.binance_net_asset),
			bybit_mt5_net_asset=COALESCE($3, risk_settings.bybit_mt5_net_asset),
			total_net_asset=COALESCE($4, risk_settings.total_net_asset),
			binance_liquidation_price=COALESCE($5, risk_settings.binance_liquidation_price),
			bybit_mt5_liquidation_price=COALESCE($6, risk_settings.bybit_mt5_liquidation_price),
			mt5_lag_count=COALESCE($7, risk_settings.mt5_lag_count),
			reverse_open_price=COALESCE($8, risk_settings.reverse_open_price),
			reverse_open_sync_count=COALESCE($9, risk_settings.reverse_open_sync_count),
			reverse_close_price=COALESCE($10, risk_settings.reverse_close_price),
			reverse_close_sync_count=COALESCE($11, risk_settings.reverse_close_sync_count),
			forward_open_price=COALESCE($12, risk_settings.forward_open_price),
			forward_open_sync_count=COALESCE($13, risk_settings.forward_open_sync_count),
			forward_close_price=COALESCE($14, risk_settings.forward_close_price),
			forward_close_sync_count=COALESCE($15, risk_settings.forward_close_sync_count),
			spread_alert_sound=COALESCE($16, risk_settings.spread_alert_sound),
			spread_alert_repeat_count=COALESCE($17, risk_settings.spread_alert_repeat_count),
			net_asset_alert_sound=COALESCE($18, risk_settings.net_asset_alert_sound),
			net_asset_alert_repeat_count=COALESCE($19, risk_settings.net_asset_alert_repeat_count),
			mt5_alert_sound=COALESCE($20, risk_settings.mt5_alert_sound),
			mt5_alert_repeat_count=COALESCE($21, risk_settings.mt5_alert_repeat_count),
			liquidation_alert_sound=COALESCE($22, risk_settings.liquidation_alert_sound),
			liquidation_alert_repeat_count=COALESCE($23, risk_settings.liquidation_alert_repeat_count),
			single_leg_alert_sound=COALESCE($24, risk_settings.single_leg_alert_sound),
			single_leg_alert_repeat_count=COALESCE($25, risk_settings.single_leg_alert_repeat_count),
			update_time=NOW()`,
		userID,
		body.BinanceNetAsset, body.BybitMT5NetAsset, body.TotalNetAsset,
		body.BinanceLiquidationDistance, body.BybitMT5LiquidationDistance, body.MT5LagCount,
		body.ReverseOpenPrice, body.ReverseOpenSyncCount,
		body.ReverseClosePrice, body.ReverseCloseSyncCount,
		body.ForwardOpenPrice, body.ForwardOpenSyncCount,
		body.ForwardClosePrice, body.ForwardCloseSyncCount,
		body.SpreadAlertSound, body.SpreadAlertRepeatCount,
		body.NetAssetAlertSound, body.NetAssetAlertRepeatCount,
		body.MT5AlertSound, body.MT5AlertRepeatCount,
		body.LiquidationAlertSound, body.LiquidationAlertRepeatCount,
		body.SingleLegAlertSound, body.SingleLegAlertRepeatCount,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
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
