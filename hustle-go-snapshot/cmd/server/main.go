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
	"hustle-go/internal/monitor"
	"hustle-go/internal/mt5"
	"hustle-go/internal/notifications"
	"hustle-go/internal/opportunities"
	"hustle-go/internal/pairs"
	"hustle-go/internal/rbac"
	"hustle-go/internal/risk"
	"hustle-go/internal/sysops"
	"hustle-go/internal/timingconfigs"
	"hustle-go/internal/trading"
	"hustle-go/internal/users"
	ws "hustle-go/internal/websocket"
)

func main() {
	cfg := config.Load()
	db.Init(cfg.Postgres.DSN)
	db.InitRedis(cfg.Redis.URL)

	// ── Load active hedging pairs from DB ─────────────────────────────
	if err := pairs.Global.Load(db.Pool()); err != nil {
		log.Printf("[Server] WARNING: failed to load pairs: %v — falling back to XAU only", err)
	}

	gin.SetMode(cfg.Server.Mode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(middleware.CORS())

	// ── Market data: multi-symbol Binance WS ──────────────────────────
	allPairs := pairs.Global.All()
	if len(allPairs) > 0 {
		streamsURL := pairs.Global.BuildBinanceStreamsURL()
		log.Printf("[Server] Binance combined WS: %s", streamsURL)
		go market.RunBinanceWS(streamsURL)
	} else {
		// Fallback to legacy single-stream
		go market.RunBinanceWS(cfg.Binance.WSURL)
	}
	log.Println("[Server] Binance WS goroutine started")

	go ws.GlobalHub.Run()
	log.Println("[Server] WebSocket Hub started")
	go ws.RunRedisBridge(cfg.Redis.URL)
	log.Println("[Server] Redis bridge started")

	// ── Multi-pair pushers ────────────────────────────────────────────
	go ws.RunMultiPairTickPusher(pairs.Global, 250*time.Millisecond)
	go ws.RunMultiPairSpreadPusher(pairs.Global, 500*time.Millisecond)
	log.Printf("[Server] Multi-pair pushers started for %d pairs", len(allPairs))

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
				"pairs":       pairs.Global.PairCodes(),
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
			u.GET("/profit-chart/all", users.GetAllUsersProfitChart)
			u.POST("/feishu-lookup", users.FeishuLookup)
			u.GET("/ipipgo-orders", users.IPIPGOOrders)
			u.PUT("/me", users.UpdateMe)
			u.PUT("/password", users.ChangePassword)
			// u.GET("/", users.ListUsers)  // → Python handles (feishu fields)
			// u.POST("/", users.CreateUser)  // → Python handles
			// u.PUT("/:user_id", users.UpdateUser)  // → Python handles (feishu fields)
			// u.DELETE("/:user_id", users.DeleteUser)  // → Python handles
			u.GET("/:user_id/profit-chart", users.GetUserProfitChart)
				u.GET("/:user_id/profit-chart-v2", users.GetUserProfitChartV2)
		}

		// ── Accounts ──────────────────────────────────────────────────────
		acc := v1.Group("/accounts", middleware.JWTAuth())
		{
			// acc.GET("", accounts.ListAccounts)  // → Python (feishu/platform fields)
			// acc.POST("", accounts.CreateAccount)  // → Python
			acc.GET("/dashboard/aggregated", accounts.GetAggregatedDashboard)
			// acc.GET("/:account_id", accounts.GetAccount)  // → Python
			// acc.GET("/:account_id/secret", accounts.GetAccountSecret)  // → Python
			// acc.PUT("/:account_id", accounts.UpdateAccount)  // → Python
			// acc.DELETE("/:account_id", accounts.DeleteAccount)  // → Python
			acc.GET("/:account_id/balance", accounts.GetBalance)
			acc.GET("/:account_id/positions", accounts.GetPositions)
			acc.GET("/:account_id/pnl", accounts.GetPnL)
			acc.GET("/:account_id/dashboard", accounts.GetDashboard)
			acc.GET("/:account_id/mt5-clients", sysops.Wildcard)
			acc.POST("/:account_id/mt5-clients", sysops.Wildcard)
			acc.GET("/:account_id/proxy/:platform_id", accounts.GetAccountProxy)
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
			tc.POST("/reload", sysops.Wildcard)
			tc.GET("/history/:strategy_type", sysops.Wildcard)
			tc.GET("/templates/:strategy_type", sysops.Wildcard)
			tc.POST("/templates", sysops.Wildcard)
			tc.DELETE("/templates/:template_id", sysops.Wildcard)
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

		// ── Notifications ─────────────────────────────────────────────────
		notif := v1.Group("/notifications", middleware.JWTAuth())
		{
			notif.GET("", notifications.ListNotifications)
			notif.GET("/unread-count", notifications.GetUnreadCount)
			notif.PUT("/read-all", notifications.MarkAllRead)
			notif.PUT("/:notification_id/read", notifications.MarkRead)
			notif.DELETE("/:notification_id", notifications.DeleteNotification)
			notif.GET("/templates/active", notifications.GetActiveTemplates)
			notif.GET("/subscriptions/:user_id", notifications.GetSubscriptions)
			notif.PUT("/subscriptions/:user_id", notifications.PutSubscriptions)
			notif.GET("/configs", notifications.ListNotifConfigs)
			notif.PUT("/configs/:service_type", notifications.UpsertNotifConfig)
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
		tr := v1.Group("/trading", middleware.JWTAuth())
		{
			tr.GET("/orders", trading.GetOrders)
			tr.GET("/history", trading.GetTradingHistory)
			tr.GET("/history/all", trading.GetAllTradingHistory)
			tr.DELETE("/history/all", trading.DeleteAllTradingHistory)
			tr.GET("/orders/realtime", trading.RealtimeOrders)
			tr.GET("/history/realtime", trading.RealtimeHistory)
			tr.POST("/sync-trades", trading.SyncTrades)
			// tr.POST("/manual/order", trading.ManualOrder)  // → Python (pair_code + MT5 bridge routing)
			// tr.POST("/manual/close-all", trading.ManualCloseAll)  // → Python
			// tr.POST("/manual/close-short", trading.ManualCloseShort)  // → Python
			// tr.POST("/manual/close-long", trading.ManualCloseLong)  // → Python
			// tr.POST("/manual/cancel-all", trading.ManualCancelAll)  // → Python
			// tr.POST("/orders/:order_id/manual-process", trading.ManualProcess)  // → Python
		}

		// ── Risk ──────────────────────────────────────────────────────────
		rk := v1.Group("/risk", middleware.JWTAuth())
		{
			// rk.GET("/status", risk.GetRiskStatus)  // → Python
			// rk.GET("/alert-settings", risk.GetAlertSettings)  // → Python (pair_code support)
			// rk.POST("/alert-settings", risk.SaveAlertSettings)  // → Python (pair_code support)
			// rk.GET("/alerts", risk.GetAlerts)  // → Python
			// rk.DELETE("/alerts/expired", risk.ClearExpiredAlerts)  // → Python
			// rk.GET("/emergency-stop/status", risk.GetEmergencyStopStatus)  // → Python
			// rk.POST("/emergency-stop/activate", risk.ActivateEmergencyStop)  // → Python
			// rk.POST("/emergency-stop/deactivate", risk.DeactivateEmergencyStop)  // → Python
			rk.GET("/mt5/stuck", risk.ProxyToRiskMT5Stuck)
			rk.GET("/account/:account_id/risk", risk.ProxyToAccountRisk)
			rk.POST("/alert-sound/upload", risk.ProxyToAlertSoundUpload)
		}

		// ── Automation ────────────────────────────────────────────────────
		auto := v1.Group("/automation", middleware.JWTAuth())
		{
			auto.POST("/strategies/:strategy_id/start", automation.StartStrategy)
			auto.POST("/strategies/:strategy_id/stop", automation.StopStrategy)
			auto.GET("/strategies/running", automation.RunningStrategies)
			auto.POST("/position-monitor/start", automation.StartPositionMonitor)
			auto.POST("/position-monitor/stop", automation.StopPositionMonitor)
			auto.GET("/position-monitor/status", automation.PositionMonitorStatus)
		}

		// ── Hedge ratio (proxied to Python) ─────────────
		hr := v1.Group("/hedge-ratio", middleware.JWTAuth())
		{
			hr.GET("", sysops.Wildcard)
			hr.PUT("", sysops.Wildcard)
			hr.PUT("/toggle", sysops.Wildcard)
		}

		// ── Pair-Account bindings (proxied to Python) ────────
		pa := v1.Group("/pair-accounts", middleware.JWTAuth())
		{
			pa.GET("", sysops.Wildcard)
			pa.GET("/:pair_code", sysops.Wildcard)
			pa.PUT("", sysops.Wildcard)
			pa.DELETE("/:pair_code", sysops.Wildcard)
		}

		// ── MT5 microservice ──────────────────────────────────────────────
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

		// ── MT5 user bridge ───────────────────────────────────────────────
		m5user := v1.Group("/mt5-user", middleware.JWTAuth())
		{
			m5user.GET("/positions", mt5.UserPositions)
			m5user.GET("/account/balance", mt5.UserAccountBalance)
			m5user.GET("/account/info", mt5.UserAccountInfo)
			m5user.GET("/connection/status", mt5.UserConnectionStatus)
		}

		// ── Sysops proxies ────────────────────────────────────────────────
		mc := v1.Group("/mt5-clients", middleware.JWTAuth())
		mc.PUT("/:client_id", sysops.Wildcard)
		mc.DELETE("/:client_id", sysops.Wildcard)
		mc.POST("/:client_id/connect", sysops.Wildcard)
		mc.POST("/:client_id/disconnect", sysops.Wildcard)
		mc.GET("/:client_id", sysops.Wildcard)
		mc.GET("/:client_id/status", sysops.Wildcard)
		mc.GET("/all", sysops.Wildcard)

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
		v1.GET("/ws/config", ws.HandleWS)
	}

	r.NoRoute(func(c *gin.Context) {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
	})

	addr := ":" + cfg.Server.Port
	log.Printf("[Server] hustle-go listening on %s (%d pairs active)", addr, len(allPairs))
	if err := r.Run(addr); err != nil {
		log.Fatalf("[Server] Failed to start: %v", err)
	}
}
