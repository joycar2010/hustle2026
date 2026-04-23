package pairs

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"

	"hustle-go/internal/mt5config"

	"github.com/jackc/pgx/v5/pgxpool"
)

type PairConfig struct {
	PairCode         string
	ASymbol          string  // A-side symbol (Binance XAUUSDT, OKX XAUUSDT-SWAP, Gate XAU_USDT, etc.)
	MT5Symbol        string  // B-side MT5 symbol
	ConversionFactor float64
	BridgeURL        string
	MT5PlatformID    int
	APlatformID      int
}

type Registry struct {
	pairs []PairConfig
	byPC  map[string]*PairConfig
	mu    sync.RWMutex
}

var Global = &Registry{
	byPC: make(map[string]*PairConfig),
}

func (r *Registry) Load(pool *pgxpool.Pool) error {
	bridgeByPlatform := mt5config.GetSystemBridges()
	log.Printf("[Pairs] Bridge URLs by platform: %v", bridgeByPlatform)

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
		if err := rows.Scan(&pc.PairCode, &pc.ASymbol, &pc.MT5Symbol,
			&pc.ConversionFactor, &pc.MT5PlatformID, &pc.APlatformID); err != nil {
			log.Printf("[Pairs] scan error: %v", err)
			continue
		}
		if url, ok := bridgeByPlatform[pc.MT5PlatformID]; ok {
			pc.BridgeURL = url
		} else {
			log.Printf("[Pairs] WARNING: no system bridge for platform %d (pair %s)", pc.MT5PlatformID, pc.PairCode)
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

func (r *Registry) Get(pairCode string) *PairConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.byPC[pairCode]
}

func (r *Registry) All() []PairConfig {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]PairConfig, len(r.pairs))
	copy(out, r.pairs)
	return out
}

func (r *Registry) PairCodes() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	codes := make([]string, len(r.pairs))
	for i, p := range r.pairs {
		codes[i] = p.PairCode
	}
	return codes
}

// SymbolsByPlatform returns unique A-side symbols for a given platform ID.
func (r *Registry) SymbolsByPlatform(platformID int) []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	seen := make(map[string]bool)
	var out []string
	for _, p := range r.pairs {
		if p.APlatformID == platformID && !seen[p.ASymbol] {
			seen[p.ASymbol] = true
			out = append(out, p.ASymbol)
		}
	}
	return out
}

// BuildBinanceStreamsURL constructs a combined Binance WS URL for platform 1 symbols only.
func (r *Registry) BuildBinanceStreamsURL() string {
	symbols := r.SymbolsByPlatform(1)
	streams := make([]string, len(symbols))
	for i, s := range symbols {
		streams[i] = strings.ToLower(s) + "@bookTicker"
	}
	return "wss://fstream.binance.com/stream?streams=" + strings.Join(streams, "/")
}

func (r *Registry) FindByASymbol(symbol string) *PairConfig {
	low := strings.ToLower(symbol)
	r.mu.RLock()
	defer r.mu.RUnlock()
	for i := range r.pairs {
		if strings.ToLower(r.pairs[i].ASymbol) == low {
			return &r.pairs[i]
		}
	}
	return nil
}
