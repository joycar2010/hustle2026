package monitor

import (
	"context"
	"crypto/x509"
	"encoding/pem"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
)

var sslCertPaths = []string{
	"/etc/letsencrypt/live/go.hustle2026.xyz/fullchain.pem",
	"/etc/letsencrypt/live/admin.hustle2026.xyz/fullchain.pem",
	"/etc/letsencrypt/live/www.hustle2026.xyz/fullchain.pem",
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
		`SELECT is_active FROM notif_configs WHERE service_type='feishu' LIMIT 1`,
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
		SELECT mc.client_name, mc.mt5_login, mc.mt5_server, mc.connection_status, mc.is_active,
		       u.username
		FROM mt5_clients mc
		JOIN accounts a ON mc.account_id = a.account_id
		JOIN users u ON a.user_id = u.user_id
		ORDER BY mc.client_name
	`)
	if err != nil {
		return []map[string]interface{}{}
	}
	defer rows.Close()
	var results []map[string]interface{}
	for rows.Next() {
		var clientName, mt5Login, mt5Server, connectionStatus, username string
		var isActive bool
		if err := rows.Scan(&clientName, &mt5Login, &mt5Server, &connectionStatus, &isActive, &username); err != nil {
			continue
		}
		results = append(results, map[string]interface{}{
			"client_name":       clientName,
			"mt5_login":         mt5Login,
			"mt5_server":        mt5Server,
			"connection_status": connectionStatus,
			"is_active":         isActive,
			"username":          username,
			"online":            connectionStatus == "connected" && isActive,
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
