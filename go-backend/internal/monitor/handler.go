package monitor

import (
	"context"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
	"hustle-go/internal/mt5config"
	"hustle-go/internal/market"
)

// startTime records process start for uptime reporting in /system/status.
var startTime = time.Now()

var sslCertPaths = []string{
	"/etc/letsencrypt/live/go.hustle2026.xyz/fullchain.pem",
	"/etc/letsencrypt/live/admin.hustle2026.xyz/fullchain.pem",
	"/etc/letsencrypt/live/www.hustle2026.xyz/fullchain.pem",
	"/etc/letsencrypt/live/auto.hustle2026.xyz/fullchain.pem",
}

func checkRedis(ctx context.Context) map[string]interface{} {
	result := map[string]interface{}{"status": "error", "connected": false}
	r := db.Redis()
	if err := r.Ping(ctx).Err(); err != nil {
		result["error"] = err.Error()
		return result
	}
	info, err := r.Info(ctx, "server", "clients", "memory").Result()
	if err != nil {
		result["error"] = err.Error()
		return result
	}
	parsed := parseRedisInfo(info)
	result["status"] = "healthy"
	result["connected"] = true
	result["version"] = parsed["redis_version"]
	result["uptime_seconds"] = parsed["uptime_in_seconds"]
	result["connected_clients"] = parsed["connected_clients"]
	result["used_memory_human"] = parsed["used_memory_human"]
	result["error"] = nil
	return result
}

func parseRedisInfo(info string) map[string]string {
	m := map[string]string{}
	for _, line := range strings.Split(info, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "#") || line == "" {
			continue
		}
		parts := strings.SplitN(line, ":", 2)
		if len(parts) == 2 {
			m[strings.TrimSpace(parts[0])] = strings.TrimSpace(parts[1])
		}
	}
	return m
}

func checkSSL() []map[string]interface{} {
	var results []map[string]interface{}
	for _, path := range sslCertPaths {
		entry := map[string]interface{}{"cert_path": path}
		data, err := os.ReadFile(path)
		if err != nil {
			entry["status"] = "error"
			entry["exists"] = false
			entry["error"] = err.Error()
			results = append(results, entry)
			continue
		}
		block, _ := pem.Decode(data)
		if block == nil {
			entry["status"] = "error"
			entry["exists"] = true
			entry["error"] = "failed to decode PEM"
			results = append(results, entry)
			continue
		}
		cert, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			entry["status"] = "error"
			entry["exists"] = true
			entry["error"] = err.Error()
			results = append(results, entry)
			continue
		}
		now := time.Now().UTC()
		daysRemaining := int(cert.NotAfter.Sub(now).Hours() / 24)
		status := "healthy"
		if now.After(cert.NotAfter) {
			status = "expired"
		} else if daysRemaining <= 7 {
			status = "critical"
		} else if daysRemaining <= 30 {
			status = "warning"
		}
		var domains []string
		domains = append(domains, cert.DNSNames...)
		entry["status"] = status
		entry["exists"] = true
		entry["domain_names"] = domains
		entry["issuer"] = cert.Issuer.CommonName
		entry["issued_at"] = cert.NotBefore.Format(time.RFC3339)
		entry["expires_at"] = cert.NotAfter.Format(time.RFC3339)
		entry["days_remaining"] = daysRemaining
		entry["is_valid"] = now.Before(cert.NotAfter)
		entry["error"] = nil
		results = append(results, entry)
	}
	return results
}

func checkFeishu(ctx context.Context) map[string]interface{} {
	var isActive bool
	err := db.Pool().QueryRow(ctx,
		`SELECT is_enabled FROM notification_configs WHERE service_type='feishu' LIMIT 1`,
	).Scan(&isActive)
	if err != nil {
		return map[string]interface{}{
			"status":     "not_configured",
			"configured": false,
			"error":      "飞书服务未配置",
		}
	}
	status := "healthy"
	if !isActive {
		status = "disabled"
	}
	return map[string]interface{}{
		"status":     status,
		"configured": true,
		"error":      nil,
	}
}

func checkMT5Clients(ctx context.Context) []map[string]interface{} {
	rows, err := db.Pool().Query(ctx, `
		SELECT mc.client_name, mc.mt5_login, mc.connection_status, mc.is_active,
		       COALESCE(u.username, '--'), mc.bridge_service_port, mc.is_system_service
		FROM mt5_clients mc
		LEFT JOIN accounts a ON mc.account_id = a.account_id
		LEFT JOIN users u ON a.user_id = u.user_id
		ORDER BY mc.client_name
	`)
	if err != nil {
		return []map[string]interface{}{}
	}
	defer rows.Close()

	bridgeHost := os.Getenv("MT5_BRIDGE_HOST")
	if bridgeHost == "" {
		bridgeHost = "http://172.31.14.113"
	}
	bridgeHost = strings.TrimRight(bridgeHost, "/")
	httpClient := &http.Client{Timeout: 2 * time.Second}

	var results []map[string]interface{}
	for rows.Next() {
		var clientName, mt5Login, connectionStatus, username string
		var isActive, isSystemService bool
		var bridgePort *int
		if err := rows.Scan(&clientName, &mt5Login, &connectionStatus, &isActive, &username, &bridgePort, &isSystemService); err != nil {
			continue
		}
		// Real-time bridge health check
		online := false
		if bridgePort != nil && *bridgePort > 0 {
			url := fmt.Sprintf("%s:%d/health", bridgeHost, *bridgePort)
			if req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil); err == nil {
				if resp, err := httpClient.Do(req); err == nil {
					var body map[string]interface{}
					json.NewDecoder(resp.Body).Decode(&body)
					resp.Body.Close()
					if v, ok := body["mt5"].(bool); ok {
						online = v
					}
				}
			}
		}
		connStatus := "disconnected"
		if online {
			connStatus = "connected"
		}
		results = append(results, map[string]interface{}{
			"client_name":       clientName,
			"mt5_login":         mt5Login,
			"connection_status": connStatus,
			"is_active":         isActive,
			"username":          username,
			"online":            online,
			"is_system_service": isSystemService,
		})
	}
	if results == nil {
		results = []map[string]interface{}{}
	}
	return results
}

// Status GET /api/v1/monitor/status
func Status(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	c.JSON(http.StatusOK, gin.H{
		"timestamp":       time.Now().UTC().Format(time.RFC3339),
		"redis":           checkRedis(ctx),
		"ssl_certificate": checkSSL(),
		"feishu":          checkFeishu(ctx),
		"mt5_clients":     checkMT5Clients(ctx),
	})
}

// SSLCurrent GET /api/v1/monitor/ssl/current
// Returns the SSL certificate with the minimum days_remaining (the most urgent one).
func SSLCurrent(c *gin.Context) {
	certs := checkSSL()
	if len(certs) == 0 {
		c.JSON(http.StatusOK, gin.H{"status": "no_certificates"})
		return
	}
	// Pick the cert with the fewest days remaining (most urgent)
	best := certs[0]
	for _, cert := range certs[1:] {
		bestDays, _ := best["days_remaining"].(int)
		thisDays, _ := cert["days_remaining"].(int)
		if thisDays < bestDays {
			best = cert
		}
	}
	c.JSON(http.StatusOK, gin.H{
		"certificates": certs,
		"most_urgent":  best,
	})
}

// SystemStatus GET /api/v1/system/status
//
// Go-native replacement for the Python /system/status endpoint. Everything is
// derived from in-process state or local sockets, so this endpoint keeps
// working even if the Python backend is down.
//
// Response shape matches what SystemStatusModal.vue expects.
func SystemStatus(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	// ── Uptime ────────────────────────────────────────────────
	uptime := time.Since(startTime)
	uptimeHours := int(uptime.Hours())
	uptimeMinutes := int(uptime.Minutes()) % 60

	// ── DB pool stats (pgxpool) ───────────────────────────────
	var dbPool gin.H
	if pool := db.Pool(); pool != nil {
		stat := pool.Stat()
		dbPool = gin.H{
			"active": int(stat.AcquiredConns()),
			"idle":   int(stat.IdleConns()),
			"max":    int(stat.MaxConns()),
		}
	} else {
		dbPool = gin.H{"active": 0, "idle": 0, "max": 0}
	}

	// ── WebSocket: Binance futures stream health ──────────────
	// GlobalTick is updated on every tick message; if the last update was
	// within 10 seconds we consider the stream healthy.
	bid, ask, tickTs := market.GetTick()
	wsConnected := bid > 0 && ask > 0 && tickTs > 0 &&
		time.Since(time.UnixMilli(tickTs)) < 10*time.Second

	// ── Binance REST: tied to WS stream health for gold pair ──
	binanceOK := wsConnected

	// ── MT5 Bridge health: HTTP GET /health (short timeout) ───
	mt5OK := checkMT5BridgeHealth(ctx)

	// ── Bybit: currently the gold pair is served via MT5 bridge,
	// so bybit status mirrors mt5 status (same physical backend).
	bybitOK := mt5OK

	// ── Redis ping: reuse existing checker but only return bool
	redisOK := false
	if info := checkRedis(ctx); info != nil {
		if v, ok := info["connected"].(bool); ok {
			redisOK = v
		}
	}

	// ── Position monitor / strategy manager: these live in Python.
	// We expose the python-backend reachability as a proxy: if the Redis
	// bridge Python publishes to is healthy AND the DB pool is up, we
	// consider the background services healthy enough to show green.
	// Caller can still inspect /monitor/status for fine-grained detail.
	backgroundOK := redisOK && db.Pool() != nil

	c.JSON(http.StatusOK, gin.H{
		"success":          true,
		"backend":          true, // this Go process itself answered the request
		"positionMonitor":  backgroundOK,
		"strategyManager":  backgroundOK,
		"binance":          binanceOK,
		"bybit":            bybitOK,
		"mt5":              mt5OK,
		"websocket":        wsConnected,
		"dbPool":           dbPool,
		"uptime":           fmt.Sprintf("%dh %dm", uptimeHours, uptimeMinutes),
		"timestamp":        time.Now().Format(time.RFC3339),
	})
}

// checkMT5BridgeHealth performs a short GET on the MT5 bridge /health endpoint.
func checkMT5BridgeHealth(ctx context.Context) bool {
	client := &http.Client{Timeout: 2 * time.Second}
	for _, c := range mt5config.GetAllClients() {
		if !c.IsSystemService || c.BridgeURL == "" {
			continue
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.BridgeURL+"/health", nil)
		if err != nil {
			continue
		}
		req.Header.Set("X-Api-Key", mt5config.BridgeAPIKey())
		resp, err := client.Do(req)
		if err != nil {
			continue
		}
		resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			return true
		}
	}
	return false
}

