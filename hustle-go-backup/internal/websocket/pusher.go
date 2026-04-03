package ws

import (
	"time"
)

// TickSource is a function that returns the latest bid/ask/timestamp
type TickSource func() (bid, ask float64, ts int64)

// SpreadSource is a function that returns the latest spread data
type SpreadSource func() interface{}

// RunTickPusher pushes Binance tick to all WS clients at the given interval
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
			"bid_price": bid,
			"ask_price": ask,
			"spread":    ask - bid,
			"timestamp": ts,
		})
	}
}

// RunSpreadPusher pushes spread data to all WS clients at the given interval
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
