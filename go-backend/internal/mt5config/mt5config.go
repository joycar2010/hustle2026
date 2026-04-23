package mt5config

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// ClientInfo holds bridge connection details for one MT5 client.
type ClientInfo struct {
	ClientID          int
	ClientName        string
	BridgeURL         string
	BridgeServiceName string
	BridgeServicePort int
	IsSystemService   bool
	IsActive          bool
	Role              string // quote_source, trading, user
	MT5PlatformID     int    // resolved from accounts.platform_id
	ConnectionStatus  string
}

var (
	mu      sync.RWMutex
	configs map[string]string
	clients []ClientInfo
	dbpool  *pgxpool.Pool
)

func Init(p *pgxpool.Pool) {
	dbpool = p
	if err := reload(); err != nil {
		log.Fatalf("[mt5config] initial load failed: %v", err)
	}
	log.Printf("[mt5config] loaded %d config keys, %d MT5 clients", len(configs), len(clients))
}

func RunReloader(interval time.Duration) {
	for {
		time.Sleep(interval)
		if err := reload(); err != nil {
			log.Printf("[mt5config] reload error: %v", err)
		}
	}
}

func reload() error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	newCfg := make(map[string]string)
	rows, err := dbpool.Query(ctx, "SELECT key, value FROM mt5_config")
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var k, v string
		if err := rows.Scan(&k, &v); err != nil {
			return err
		}
		newCfg[k] = v
	}

	var newClients []ClientInfo
	crows, err := dbpool.Query(ctx, `
		SELECT mc.client_id, mc.client_name,
		       COALESCE(mc.bridge_url, ''), COALESCE(mc.bridge_service_name, ''),
		       COALESCE(mc.bridge_service_port, 0),
		       mc.is_system_service, mc.is_active,
		       COALESCE(mc.role, 'trading'), COALESCE(a.platform_id, 0),
		       COALESCE(mc.connection_status, 'unknown')
		FROM mt5_clients mc
		JOIN accounts a ON mc.account_id = a.account_id
		WHERE mc.is_active = true
		ORDER BY mc.priority, mc.client_id`)
	if err != nil {
		return err
	}
	defer crows.Close()
	for crows.Next() {
		var c ClientInfo
		if err := crows.Scan(&c.ClientID, &c.ClientName, &c.BridgeURL,
			&c.BridgeServiceName, &c.BridgeServicePort,
			&c.IsSystemService, &c.IsActive, &c.Role,
			&c.MT5PlatformID, &c.ConnectionStatus); err != nil {
			return err
		}
		newClients = append(newClients, c)
	}

	mu.Lock()
	configs = newCfg
	clients = newClients
	mu.Unlock()
	return nil
}

func Get(key string) string {
	mu.RLock()
	defer mu.RUnlock()
	return configs[key]
}

func AgentURL() string {
	if v := Get("agent_url"); v != "" {
		return v
	}
	return "http://172.31.14.113:8765"
}

func AgentAPIKey() string {
	if v := Get("agent_api_key"); v != "" {
		return v
	}
	return "HustleXAU_MT5_Agent_Key_2026"
}

func BridgeAPIKey() string {
	if v := Get("bridge_api_key"); v != "" {
		return v
	}
	return "OQ6bUimHZDmXEZzJKE"
}

func GetAllClients() []ClientInfo {
	mu.RLock()
	defer mu.RUnlock()
	out := make([]ClientInfo, len(clients))
	copy(out, clients)
	return out
}

func GetSystemBridges() map[int]string {
	mu.RLock()
	defer mu.RUnlock()
	m := make(map[int]string)
	for _, c := range clients {
		if c.IsSystemService && c.BridgeURL != "" {
			m[c.MT5PlatformID] = c.BridgeURL
		}
	}
	return m
}

func GetClientByName(name string) *ClientInfo {
	mu.RLock()
	defer mu.RUnlock()
	for _, c := range clients {
		if c.ClientName == name {
			cc := c
			return &cc
		}
	}
	return nil
}

func UpdateConnectionStatus(clientID int, status string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err := dbpool.Exec(ctx,
		"UPDATE mt5_clients SET connection_status=$1, updated_at=now() WHERE client_id=$2",
		status, clientID)
	return err
}
