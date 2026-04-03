package main

import (
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/accounts"
	"hustle-go/internal/auth"
	"hustle-go/internal/automation"
	"hustle-go/internal/config"
	"hustle-go/internal/db"
	"hustle-go/internal/market"
	"hustle-go/internal/middleware"
	"hustle-go/internal/mt5"
	"hustle-go/internal/notifications"
	"hustle-go/internal/rbac"
	"hustle-go/internal/risk"
	"hustle-go/internal/strategies"
	"hustle-go/internal/sysops"
	"hustle-go/internal/timingconfigs"
	"hustle-go/internal/trading"
	"hustle-go/internal/monitor"
	"hustle-go/internal/opportunities"
	"hustle-go/internal/users"
	ws "hustle-go/internal/websocket"
)

func main() {
	cfg := config.Load()
	db.Init(cfg.Postgres.DSN)
	db.InitRedis(cfg.Redis.URL)

	gin.SetMode(cfg.Server.Mode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(middleware.CORS())

	go market.RunBinanceWS(cfg.Binance.WSURL)
	log.Println("[Server] Binance WS goroutine started")
	go ws.GlobalHub.Run()
	log.Println("[Server] WebSocket Hub started")
	go ws.RunRedisBridge(cfg.Redis.URL)
	log.Println("[Server] Redis bridge started")
	go ws.RunTickPusher(market.GetTick, 250*time.Millisecond)
	go ws.RunSpreadPusher(func() interface{} {
		bid, ask, ts := market.GetTick()
		if bid == 0 || ask == 0 {
			return nil
		}
		bybit, err := market.GetBybitTicker("XAUUSDT")
		if err != nil {
			return nil
		}
		return map[string]interface{}{
			"binance_bid":          bid,
			"binance_ask":          ask,
			"bybit_bid":            bybit.Bid,
			"bybit_ask":            bybit.Ask,
			"forward_entry_spread": bybit.Bid - bid,
			"forward_exit_spread":  bybit.Ask - ask,
			"reverse_entry_spread": ask - bybit.Ask,
			"reverse_exit_spread":  bid - bybit.Bid,
			"timestamp":            ts,
		}
	}, 500*time.Millisecond)
	go market.RunTimeSyncLoop()

	v1 := r.Group("/api/v1")
	{
		v1.GET("/health", func(c *gin.Context) {
			bid, ask, ts := market.GetTick()
			wsOK := bid > 0 && ask > 0
			status := "ok"
			if !wsOK {
				status = "degraded"
			}
			c.JSON(http.StatusOK, gin.H{
				"status":      status,
				"service":     "hustle-go",
				"ws_binance":  wsOK,
				"ws_clients":  ws.GlobalHub.ClientCount(),
				"server_time": time.Now().UnixMilli(),
				"last_tick":   ts,
			})
		})

		// ── Auth ──────────────────────────────────────────────────────────
		a := v1.Group("/auth")
		{
			a.POST("/login", auth.Login)
			a.POST("/register", auth.Register)
			a.POST("/verify-password", middleware.JWTAuth(), auth.VerifyPassword)
		}

		// ── Users ─────────────────────────────────────────────────────────
		u := v1.Group("/users", middleware.JWTAuth())
		{
			u.GET("/me", users.GetMe)
			u.PUT("/me", users.UpdateMe)
			u.PUT("/password", users.ChangePassword)
			u.GET("/", users.ListUsers)
			u.POST("/", users.CreateUser)
			u.PUT("/:user_id", users.UpdateUser)
			u.DELETE("/:user_id", users.DeleteUser)
		}

		// ── Accounts ──────────────────────────────────────────────────────
		acc := v1.Group("/accounts", middleware.JWTAuth())
		{
			acc.GET("", accounts.ListAccounts)
			acc.POST("", accounts.CreateAccount)
			acc.GET("/dashboard/aggregated", accounts.GetAggregatedDashboard)
			acc.GET("/:account_id", accounts.GetAccount)
			acc.GET("/:account_id/secret", accounts.GetAccountSecret)
			acc.PUT("/:account_id", accounts.UpdateAccount)
			acc.DELETE("/:account_id", accounts.DeleteAccount)
			acc.GET("/:account_id/balance", accounts.GetBalance)
			acc.GET("/:account_id/positions", accounts.GetPositions)
			acc.GET("/:account_id/pnl", accounts.GetPnL)
			acc.GET("/:account_id/dashboard", accounts.GetDashboard)
			acc.GET("/:account_id/mt5-clients", sysops.Wildcard)
			acc.POST("/:account_id/mt5-clients", sysops.Wildcard)
		}

		// ── Market data ───────────────────────────────────────────────────
		mkt := v1.Group("/market")
		{
			mkt.GET("/binance/quote", market.GetBinanceQuote)
			mkt.GET("/spread", market.GetSpread)
			mkt.GET("/orderbook", market.GetOrderBook)
			mkt.GET("/funding-rate", market.GetFundingRate)
			mkt.GET("/bybit-swap-rate", market.GetBybitSwapRate)
			mkt.GET("/spread/history", sysops.Wildcard)
		}

		// ── Time sync ─────────────────────────────────────────────────────
		t := v1.Group("/time")
		{
			t.GET("/sync", market.SyncServerTime)
			t.GET("/offset", market.GetTimeOffset)
		}

		// ── Timing configs ────────────────────────────────────────────────
		tc := v1.Group("/timing-configs", middleware.JWTAuth())
		{
			tc.GET("", timingconfigs.ListTimingConfigs)
			tc.POST("", timingconfigs.CreateTimingConfig)
			tc.GET("/by-type/:strategy_type", timingconfigs.GetTimingConfigByType)
			tc.GET("/effective/:strategy_type", timingconfigs.GetTimingConfigEffective)
			tc.GET("/:config_id", timingconfigs.GetTimingConfig)
			tc.PUT("/:config_id", timingconfigs.UpdateTimingConfig)
			tc.DELETE("/:config_id", timingconfigs.DeleteTimingConfig)
			tc.POST("/reload",                      sysops.Wildcard)
			tc.GET("/history/:strategy_type",        sysops.Wildcard)
			tc.GET("/templates/:strategy_type",      sysops.Wildcard)
			tc.POST("/templates",                    sysops.Wildcard)
			tc.DELETE("/templates/:template_id",     sysops.Wildcard)
		}

		// ── RBAC ──────────────────────────────────────────────────────────
		rb := v1.Group("/rbac", middleware.JWTAuth())
		{
			rb.GET("/roles", rbac.ListRoles)
			rb.POST("/roles", rbac.CreateRole)
			rb.GET("/roles/:role_id", rbac.GetRole)
			rb.PUT("/roles/:role_id", rbac.UpdateRole)
			rb.DELETE("/roles/:role_id", rbac.DeleteRole)
			rb.GET("/roles/:role_id/permissions", rbac.GetRolePermissions)
			rb.POST("/roles/:role_id/permissions", rbac.AssignPermission)
			rb.DELETE("/roles/:role_id/permissions/:permission_id", rbac.RevokePermission)
			rb.GET("/permissions", rbac.ListPermissions)
			rb.GET("/users/:user_id/roles", rbac.GetUserRoles)
			rb.POST("/users/:user_id/roles", rbac.AssignUserRole)
			rb.DELETE("/users/:user_id/roles/:role_id", rbac.RevokeUserRole)
		}

		// ── Strategies ────────────────────────────────────────────────────
		strat := v1.Group("/strategies", middleware.JWTAuth())
		{
			strat.GET("", strategies.ListStrategies)
			strat.POST("", strategies.CreateStrategy)
			strat.GET("/configs", strategies.ListStrategyConfigs)
			strat.GET("/configs/by-type/:strategy_type", strategies.GetStrategyConfigByType)
			strat.GET("/configs/:config_id", strategies.GetStrategyConfig)
			strat.PUT("/configs/:strategy_type", strategies.UpsertStrategyConfig)
			strat.POST("/configs/upsert", strategies.UpsertStrategyConfigByBody)
			// Python-only strategy execution endpoints — proxy
			strat.POST("/execute/:strategy_type", strategies.ProxyExecute)
			strat.POST("/close/:strategy_type", strategies.ProxyClose)
			strat.Any("/execution/*path", strategies.ProxyExecution)
			strat.GET("/:id", strategies.GetStrategy)
			strat.PUT("/:id", strategies.UpdateStrategy)
			strat.DELETE("/:id", strategies.DeleteStrategy)
		}

		// ── Notifications ─────────────────────────────────────────────────
		notif := v1.Group("/notifications", middleware.JWTAuth())
		{
			notif.GET("", notifications.ListNotifications)
			notif.GET("/unread-count", notifications.GetUnreadCount)
			notif.PUT("/read-all", notifications.MarkAllRead)
			notif.PUT("/:notification_id/read", notifications.MarkRead)
			notif.DELETE("/:notification_id", notifications.DeleteNotification)
			notif.GET("/configs", notifications.ListNotifConfigs)
			notif.PUT("/configs/:service_type", notifications.UpsertNotifConfig)
			// Proxy Python feishu notification service (templates, config, logs, send, test)
			notif.GET("/config", sysops.Wildcard)
			notif.PUT("/config/:service_type", sysops.Wildcard)
			notif.GET("/feishu/status", sysops.Wildcard)
			notif.POST("/test/:service_type", sysops.Wildcard)
			notif.GET("/templates", sysops.Wildcard)
			notif.GET("/templates/:template_id", sysops.Wildcard)
			notif.PUT("/templates/:template_id", sysops.Wildcard)
			notif.GET("/logs", sysops.Wildcard)
			notif.POST("/send", sysops.Wildcard)
		}

		// ── Trading ───────────────────────────────────────────────────────
		// DB history/orders: Go native. Manual execution + realtime: proxy to Python.
		tr := v1.Group("/trading", middleware.JWTAuth())
		{
			tr.GET("/orders", trading.GetOrders)
			tr.GET("/history", trading.GetTradingHistory)
			tr.GET("/history/all", trading.GetAllTradingHistory)
			tr.DELETE("/history/all", trading.DeleteAllTradingHistory)
			tr.GET("/orders/realtime", trading.RealtimeOrders)
			tr.GET("/history/realtime", trading.RealtimeHistory)
			tr.POST("/sync-trades", trading.SyncTrades)
			tr.POST("/manual/order", trading.ManualOrder)
			tr.POST("/manual/close-all", trading.ManualCloseAll)
			tr.POST("/manual/close-short", trading.ManualCloseShort)
			tr.POST("/manual/close-long", trading.ManualCloseLong)
			tr.POST("/manual/cancel-all", trading.ManualCancelAll)
			tr.POST("/orders/:order_id/manual-process", trading.ManualProcess)
		}

		// ── Risk ──────────────────────────────────────────────────────────
		rk := v1.Group("/risk", middleware.JWTAuth())
		{
			rk.GET("/status", risk.GetRiskStatus)
			rk.GET("/alert-settings", risk.GetAlertSettings)
			rk.POST("/alert-settings", risk.SaveAlertSettings)
			rk.GET("/alerts", risk.GetAlerts)
			rk.DELETE("/alerts/expired", risk.ClearExpiredAlerts)
			rk.GET("/emergency-stop/status", risk.GetEmergencyStopStatus)
			rk.POST("/emergency-stop/activate", risk.ActivateEmergencyStop)
			rk.POST("/emergency-stop/deactivate", risk.DeactivateEmergencyStop)
			// Complex risk checks proxy to Python
			rk.GET("/mt5/stuck", risk.ProxyToRiskMT5Stuck)
			rk.GET("/account/:account_id/risk", risk.ProxyToAccountRisk)
			rk.POST("/alert-sound/upload", risk.ProxyToAlertSoundUpload)
		}

		// ── Automation — proxy to Python ──────────────────────────────────
		auto := v1.Group("/automation", middleware.JWTAuth())
		{
			auto.POST("/strategies/:strategy_id/start", automation.StartStrategy)
			auto.POST("/strategies/:strategy_id/stop", automation.StopStrategy)
			auto.GET("/strategies/running", automation.RunningStrategies)
			auto.POST("/position-monitor/start", automation.StartPositionMonitor)
			auto.POST("/position-monitor/stop", automation.StopPositionMonitor)
			auto.GET("/position-monitor/status", automation.PositionMonitorStatus)
		}

		// ── MT5 microservice — proxy to Windows :8001 ─────────────────────
		m5 := v1.Group("/mt5", middleware.JWTAuth())
		{
			m5.GET("/positions", mt5.Positions)
			m5.POST("/order", mt5.PlaceOrder)
			m5.GET("/connection/status", mt5.ConnectionStatus)
			m5.POST("/connection/reconnect", mt5.Reconnect)
			m5.GET("/account/balance", mt5.AccountBalance)
			m5.GET("/account/info", mt5.AccountInfo)
			m5.GET("/symbols", mt5.Symbols)
			m5.GET("/tick/:symbol", mt5.Tick)
			m5.GET("/history/deals", mt5.HistoryDeals)
			m5.GET("/history/orders", mt5.HistoryOrders)
			m5.POST("/position/close", mt5.ClosePosition)
			m5.POST("/position/close-all", mt5.CloseAll)
		}

		// ── System / Security / SSL / Proxies / Sounds — proxy to Python ──
		// Low-frequency admin ops; no value reimplementing in Go.
		// MT5-clients standalone routes (PUT/DELETE/connect/disconnect)
		mc := v1.Group("/mt5-clients", middleware.JWTAuth())
			mc.PUT("/:client_id",            sysops.Wildcard)
			mc.DELETE("/:client_id",         sysops.Wildcard)
			mc.POST("/:client_id/connect",   sysops.Wildcard)
			mc.POST("/:client_id/disconnect", sysops.Wildcard)
			mc.GET("/:client_id",             sysops.Wildcard)
			mc.GET("/:client_id/status",      sysops.Wildcard)
			mc.GET("/all",                    sysops.Wildcard)

		v1.Any("/system/*path", sysops.Wildcard)
		v1.Any("/security/*path", sysops.Wildcard)
		v1.Any("/ssl/*path", sysops.Wildcard)
		v1.Any("/proxies/*path", sysops.Wildcard)
		v1.Any("/sounds/*path", sysops.Wildcard)
		v1.Any("/keys/*path", sysops.Wildcard)
		v1.GET("/monitor/status", monitor.Status)
	v1.GET("/monitor/ssl/current", monitor.SSLCurrent)
		v1.GET("/monitor/websocket", sysops.Wildcard)
		opp := v1.Group("/opportunities", middleware.JWTAuth())
		opp.GET("", opportunities.List)
		opp.GET("/stats", opportunities.Stats)
		opp.POST("/extract", opportunities.Extract)
		opp.POST("/cleanup", opportunities.Cleanup)
		v1.Any("/qingguo/*path", sysops.Wildcard)

		// ── WebSocket ─────────────────────────────────────────────────────
		v1.GET("/ws", ws.HandleWS)
		v1.GET("/ws/stats", ws.HandleStats)
		v1.GET("/ws/config", ws.HandleWS) // legacy compat
	}

	r.NoRoute(func(c *gin.Context) {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
	})

	addr := ":" + cfg.Server.Port
	log.Printf("[Server] hustle-go listening on %s", addr)
	if err := r.Run(addr); err != nil {
		log.Fatalf("[Server] Failed to start: %v", err)
	}
}
