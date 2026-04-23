package ws

import (
	"context"
	"encoding/json"
	"log"
	"strings"
	"sync"
	"time"

	"hustle-go/internal/db"

	"github.com/jackc/pgx/v5/pgxpool"
)

// subAccountView represents the effective view for a WS client.
// For a regular user: isSub=false, dataUserID=loginUserID, multiplier=1.
// For a sub-account: isSub=true, dataUserID=parent_user_id, multiplier is cached.
type subAccountView struct {
	dataUserID string
	isSub      bool
	multiplier float64
	resolvedAt time.Time
}

var (
	subViewCache   = make(map[string]*subAccountView)
	subViewCacheMu sync.RWMutex
	// Refresh multiplier every 60 seconds; until then use cached value.
	subViewTTL = 60 * time.Second
)

// ResolveSubAccountView queries users + sub_account_subscriptions + aggregates
// parent's total assets to compute (dataUserID, isSub, multiplier).
// Returns (loginUserID, 1.0, false) for regular users — transparent.
func ResolveSubAccountView(loginUserID string) subAccountView {
	subViewCacheMu.RLock()
	if v, ok := subViewCache[loginUserID]; ok && time.Since(v.resolvedAt) < subViewTTL {
		subViewCacheMu.RUnlock()
		return *v
	}
	subViewCacheMu.RUnlock()

	pool := db.Pool()
	if pool == nil {
		return subAccountView{dataUserID: loginUserID, isSub: false, multiplier: 1.0, resolvedAt: time.Now()}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	view := resolveSubAccountViewFromDB(ctx, pool, loginUserID)
	subViewCacheMu.Lock()
	subViewCache[loginUserID] = &view
	subViewCacheMu.Unlock()
	return view
}

// InvalidateSubAccountView forces a re-resolve for a user (e.g. on subscription change).
func InvalidateSubAccountView(loginUserID string) {
	subViewCacheMu.Lock()
	delete(subViewCache, loginUserID)
	subViewCacheMu.Unlock()
}

func resolveSubAccountViewFromDB(ctx context.Context, pool *pgxpool.Pool, loginUserID string) subAccountView {
	// Is this login user a sub?
	var isSub bool
	var parentID *string
	err := pool.QueryRow(ctx,
		`SELECT is_subaccount, parent_user_id::text FROM users WHERE user_id = $1::uuid`,
		loginUserID,
	).Scan(&isSub, &parentID)
	if err != nil || !isSub || parentID == nil {
		return subAccountView{dataUserID: loginUserID, isSub: false, multiplier: 1.0, resolvedAt: time.Now()}
	}

	// Pull active subscription shares
	var subShares float64
	err = pool.QueryRow(ctx,
		`SELECT COALESCE(SUM(shares),0) FROM sub_account_subscriptions
		 WHERE sub_user_id = $1::uuid AND status = 'active'`,
		loginUserID,
	).Scan(&subShares)
	if err != nil || subShares <= 0 {
		// No active subscription — sub locked out (0% share)
		return subAccountView{dataUserID: *parentID, isSub: true, multiplier: 0.0, resolvedAt: time.Now()}
	}

	// Parent total assets (latest snapshot per account, summed)
	var totalAssets float64
	_ = pool.QueryRow(ctx,
		`SELECT COALESCE(SUM(total_assets_usdt), 0) FROM (
		   SELECT DISTINCT ON (account_id) total_assets_usdt
		   FROM account_snapshots
		   WHERE user_id = $1::uuid
		   ORDER BY account_id, snapshot_time DESC
		 ) q`,
		*parentID,
	).Scan(&totalAssets)

	// Total outstanding shares = parent_virtual + sum(active subs)
	var parentVirtualShares float64
	_ = pool.QueryRow(ctx,
		`SELECT COALESCE(MIN(parent_total_assets_at_join), 0)
		 FROM sub_account_subscriptions
		 WHERE parent_user_id = $1::uuid AND status = 'active'`,
		*parentID,
	).Scan(&parentVirtualShares)

	var allActiveShares float64
	_ = pool.QueryRow(ctx,
		`SELECT COALESCE(SUM(shares),0) FROM sub_account_subscriptions
		 WHERE parent_user_id = $1::uuid AND status = 'active'`,
		*parentID,
	).Scan(&allActiveShares)

	totalShares := parentVirtualShares + allActiveShares
	mult := 0.0
	if totalShares > 0 && totalAssets > 0 {
		nav := totalAssets / totalShares
		subValue := subShares * nav
		mult = subValue / totalAssets
	}
	return subAccountView{
		dataUserID: *parentID,
		isSub:      true,
		multiplier: mult,
		resolvedAt: time.Now(),
	}
}

// monetaryFieldNames — fields whose numeric values get multiplied for sub-accounts.
var scaleFields = map[string]bool{
	"balance": true, "available_balance": true, "frozen_assets": true, "frozen_balance": true,
	"total_assets": true, "total_assets_usdt": true, "total_balance": true, "wallet_balance": true,
	"net_assets": true, "equity": true, "available_equity": true,
	"binance_net_asset": true, "bybit_mt5_net_asset": true,
	"pnl": true, "realized_pnl": true, "unrealized_pnl": true, "cumulative_pnl": true, "net_pnl": true,
	"binance_pnl": true, "binance_funding": true, "mt5_pnl": true, "mt5_swap": true, "mt5_commission": true,
	"funding_fee": true, "commission": true, "swap": true,
	"max_drawdown": true, "max_runup": true,
	"size": true, "qty": true, "position_qty": true, "position_amt": true, "notional": true,
	"initial_margin": true, "maintenance_margin": true, "margin": true, "isolated_margin": true,
	"amount": true, "profit": true, "estimated_profit": true,
}

var neverScale = map[string]bool{
	"price": true, "mark_price": true, "entry_price": true, "liquidation_price": true, "avg_price": true,
	"tick_size": true, "step_size": true, "qty_step": true, "qty_precision": true, "price_precision": true,
	"qty_unit": true, "min_qty": true, "contract_unit": true,
	"fee_rate": true, "maker_fee_rate": true, "taker_fee_rate": true, "fee_per_lot": true,
	"margin_rate": true, "margin_rate_initial": true, "margin_rate_maintenance": true,
	"leverage": true, "spread": true, "forward_spread": true, "reverse_spread": true,
	"fx_cny_to_usdt": true, "fx_rate": true, "usd_usdt_rate": true,
	"ratio": true, "percent": true, "percentage": true,
	"win_rate": true, "annualized": true, "annual_return": true,
	"shares": true, "multiplier": true, "nav_per_share": true, "nav_per_share_at_join": true,
	"invested_cny": true, "invested_usdt": true,
	"count": true, "trade_count": true, "win_count": true, "broadcast_count": true,
	"platform_id": true, "user_id": true, "id": true, "account_id": true,
	"ts": true, "timestamp": true, "created_at": true, "updated_at": true, "snapshot_time": true,
}

// shouldScale mirrors the Python-side projector.
func shouldScale(k string) bool {
	kl := strings.ToLower(k)
	if neverScale[kl] {
		return false
	}
	if scaleFields[kl] {
		return true
	}
	for _, suffix := range []string{"_pnl", "_balance", "_amount", "_profit", "_margin", "_equity", "_assets", "_value_usdt", "_funding"} {
		if strings.HasSuffix(kl, suffix) {
			return true
		}
	}
	return false
}

// projectPayload walks the data interface and multiplies matched numeric fields.
// Operates on a copy; the input is not modified if it was a map reference, we
// clone per-element on-write to avoid polluting shared broadcast payloads.
func projectPayload(data interface{}, mult float64) interface{} {
	if mult == 1.0 {
		return data
	}
	return walkAndScale(data, mult)
}

func walkAndScale(v interface{}, m float64) interface{} {
	switch t := v.(type) {
	case map[string]interface{}:
		out := make(map[string]interface{}, len(t))
		for k, val := range t {
			if shouldScale(k) {
				if f, ok := toFloat(val); ok {
					out[k] = f * m
					continue
				}
			}
			out[k] = walkAndScale(val, m)
		}
		return out
	case []interface{}:
		out := make([]interface{}, len(t))
		for i, x := range t {
			out[i] = walkAndScale(x, m)
		}
		return out
	default:
		return v
	}
}

func toFloat(v interface{}) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case float32:
		return float64(x), true
	case int:
		return float64(x), true
	case int32:
		return float64(x), true
	case int64:
		return float64(x), true
	case json.Number:
		if f, err := x.Float64(); err == nil {
			return f, true
		}
	}
	return 0, false
}

// Msg types that carry per-user monetary data and require projection for subs.
var projectedMsgTypes = map[string]bool{
	"account_balance": true,
	"position_update": true,
	"order_update":    true,
	"risk_metrics":    true,
}

func shouldProject(msgType string) bool { return projectedMsgTypes[msgType] }

// Guard: if log spam.
var _ = log.Println
