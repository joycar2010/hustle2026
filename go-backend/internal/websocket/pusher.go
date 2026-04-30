package ws

import (
	"log"
	"time"

	"hustle-go/internal/market"
	"hustle-go/internal/pairs"
)

// TickSource is a function that returns the latest bid/ask/timestamp
type TickSource func() (bid, ask float64, ts int64)

// SpreadSource is a function that returns the latest spread data
type SpreadSource func() interface{}

// RunTickPusher pushes Binance tick to all WS clients at the given interval (legacy single-pair).
func RunTickPusher(source TickSource, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for range ticker.C {
		bid, ask, ts := source()
		if bid == 0 || ask == 0 {
			continue
		}
		GlobalHub.Broadcast(MsgTypeTick, map[string]interface{}{
			"symbol":    "XAUUSDT",
			"pair_code": "XAU",
			"bid_price": bid,
			"ask_price": ask,
			"spread":    ask - bid,
			"timestamp": ts,
		})
	}
}

// RunSpreadPusher pushes spread data to all WS clients at the given interval (legacy single-pair).
func RunSpreadPusher(source SpreadSource, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for range ticker.C {
		data := source()
		if data == nil {
			continue
		}
		GlobalHub.Broadcast(MsgTypeSpread, data)
	}
}

// RunMultiPairTickPusher pushes per-pair Binance ticks to subscribed room clients.
func RunMultiPairTickPusher(registry *pairs.Registry, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	diagTicker := time.NewTicker(10 * time.Second)
	defer diagTicker.Stop()
	var xauSent, xauSkip int
	for {
		select {
		case <-diagTicker.C:
			GlobalHub.mu.RLock()
			roomSize := len(GlobalHub.rooms["XAU"])
			GlobalHub.mu.RUnlock()
			log.Printf("[TickPusher] XAU diag: sent=%d skip=%d room_clients=%d", xauSent, xauSkip, roomSize)
			xauSent = 0
			xauSkip = 0
		case <-ticker.C:
		}
		for _, pair := range registry.All() {
			bid, ask, ts := market.GlobalTicks.Get(pair.APlatformID, pair.ASymbol)
			if bid == 0 || ask == 0 {
				if pair.PairCode == "XAU" { xauSkip++ }
				continue
			}
			if pair.PairCode == "XAU" { xauSent++ }
			GlobalHub.BroadcastToRoom(pair.PairCode, MsgTypeTick, map[string]interface{}{
				"symbol":    pair.ASymbol,
				"pair_code": pair.PairCode,
				"bid_price": bid,
				"ask_price": ask,
				"spread":    ask - bid,
				"timestamp": ts,
			})
		}
	}
}

// RunMultiPairSpreadPusher pushes per-pair spread data to subscribed room clients.
func RunMultiPairSpreadPusher(registry *pairs.Registry, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for range ticker.C {
		for _, pair := range registry.All() {
			data := market.ComputeSpreadForPair(pair)
			if data == nil {
				continue
			}
			GlobalHub.BroadcastToRoom(pair.PairCode, MsgTypeSpread, data)
		}
	}
}
