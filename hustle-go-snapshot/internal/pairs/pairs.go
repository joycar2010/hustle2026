package pairs

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"

	"github.com/jackc/pgx/v5/pgxpool"
)

// PairConfig holds the symbol mapping for a single hedging pair.
type PairConfig struct {
	PairCode         string
	BinanceSymbol    string  // A-side symbol, e.g. "XAUUSDT" (Binance) or "XAU_USDT" (Gate)
	MT5Symbol        string  // B-side symbol, e.g. "XAUUSD+"
	ConversionFactor float64 // e.g. 100 for XAU
	BridgeURL        string  // MT5 Bridge URL for this pair's platform, e.g. "http://172.31.14.113:8887"
	MT5PlatformID    int     // platform_id of the B-side symbol
	APlatformID      int     // platform_id of the A-side symbol (1=Binance, 4=Gate, ...)
}

// Registry is a thread-safe lookup table for active pairs.
type Registry struct {
	pairs []PairConfig
	byPC  map[string]*PairConfig // pair_code → config
	mu    sync.RWMutex
}

var Global = &Registry{
	byPC: make(map[string]*PairConfig),
}

// Load reads active hedging pairs from the database and populates the registry.
func (r *Registry) Load(pool *pgxpool.Pool) error {
	// Step 1: load platform→bridge_url map from system-service MT5 clients
	bridgeByPlatform := map[int]string{}
	bRows, err := pool.Query(context.Background(), `
		SELECT a.platform_id, mc.bridge_url
		FROM mt5_clients mc
		JOIN accounts a ON mc.account_id = a.account_id
		WHERE mc.is_system_service = true AND mc.is_active = true
		  AND mc.bridge_url IS NOT NULL AND mc.bridge_url != ''
		ORDER BY mc.priority
	`)
	if err == nil {
		defer bRows.Close()
		for bRows.Next() {
			var pid int
			var burl string
			if err := bRows.Scan(&pid, &burl); err == nil {
				bridgeByPlatform[pid] = burl
			}
		}
	}
	log.Printf("[Pairs] Bridge URLs by platform: %v", bridgeByPlatform)

	// Step 2: load pair configs
	rows, err := pool.Query(context.Background(), `
		SELECT hp.pair_code, sa.symbol, sb.symbol, hp.conversion_factor, sb.platform_id, sa.platform_id
		FROM hedging_pairs hp
		JOIN platform_symbols sa ON hp.symbol_a_id = sa.id
		JOIN platform_symbols sb ON hp.symbol_b_id = sb.id
		WHERE hp.is_active = true
		ORDER BY hp.sort_order
	`)
	if err != nil {
		return fmt.Errorf("pairs.Load: %w", err)
	}
	defer rows.Close()

	var list []PairConfig
	idx := make(map[string]*PairConfig)
	for rows.Next() {
		var pc PairConfig
		if err := rows.Scan(&pc.PairCode, &pc.BinanceSymbol, &pc.MT5Symbol,
			&pc.ConversionFactor, &pc.MT5PlatformID, &pc.APlatformID); err != nil {
			log.Printf("[Pairs] scan error: %v", err)
			continue
		}
		// Assign bridge URL from system-service client for this platform
		if url, ok := bridgeByPlatform[pc.MT5PlatformID]; ok {
			pc.BridgeURL = url
		} else {
			// Fallback: use env var or default Bybit bridge
			pc.BridgeURL = ""
		}
		list = append(list, pc)
		idx[pc.PairCode] = &list[len(list)-1]
	}

	r.mu.Lock()
	r.pairs = list
	r.byPC = idx
	r.mu.Unlock()

	log.Printf("[Pairs] Loaded %d active pairs: %v", len(list), r.PairCodes())
	return nil
}

// Get returns a pair config by pair_code, or nil if not found.
func (r *Registry) Get(pairCode string) *PairConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.byPC[pairCode]
}

// All returns a copy of all active pair configs.
func (r *Registry) All() []PairConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]PairConfig, len(r.pairs))
	copy(out, r.pairs)
	return out
}

// PairCodes returns a slice of all active pair codes.
func (r *Registry) PairCodes() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	codes := make([]string, len(r.pairs))
	for i, p := range r.pairs {
		codes[i] = p.PairCode
	}
	return codes
}

// UniqueBinanceSymbols returns deduplicated lowercase Binance symbols.
func (r *Registry) UniqueBinanceSymbols() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	seen := make(map[string]bool)
	var out []string
	for _, p := range r.pairs {
		low := strings.ToLower(p.BinanceSymbol)
		if !seen[low] {
			seen[low] = true
			out = append(out, low)
		}
	}
	return out
}

// BuildBinanceStreamsURL constructs a combined Binance WS URL for all symbols.
// Format: wss://fstream.binance.com/stream?streams=xauusdt@bookTicker/xagusdt@bookTicker/...
func (r *Registry) BuildBinanceStreamsURL() string {
	symbols := r.UniqueBinanceSymbols()
	streams := make([]string, len(symbols))
	for i, s := range symbols {
		streams[i] = s + "@bookTicker"
	}
	return "wss://fstream.binance.com/stream?streams=" + strings.Join(streams, "/")
}

// FindByBinanceSymbol returns the first pair matching a Binance symbol (case-insensitive).
func (r *Registry) FindByBinanceSymbol(symbol string) *PairConfig {
	low := strings.ToLower(symbol)
	r.mu.RLock()
	defer r.mu.RUnlock()
	for i := range r.pairs {
		if strings.ToLower(r.pairs[i].BinanceSymbol) == low {
			return &r.pairs[i]
		}
	}
	return nil
}
