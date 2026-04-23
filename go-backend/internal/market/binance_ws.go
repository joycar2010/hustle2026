package market

import (
	"encoding/json"
	"log"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// BinanceTick holds the latest bid/ask for a single symbol.
type BinanceTick struct {
	Bid       float64
	Ask       float64
	Timestamp int64
}

// MultiTick stores ticks for multiple Binance symbols, keyed by lowercase symbol.
type MultiTick struct {
	ticks map[string]*BinanceTick
	mu    sync.RWMutex
}

// GlobalTicks is the multi-symbol tick store.
var GlobalTicks = &MultiTick{
	ticks: make(map[string]*BinanceTick),
}

// Update stores a new tick for the given symbol (case-insensitive key).
func (mt *MultiTick) Update(symbol string, bid, ask float64) {
	key := strings.ToLower(symbol)
	mt.mu.Lock()
	mt.ticks[key] = &BinanceTick{Bid: bid, Ask: ask, Timestamp: time.Now().UnixMilli()}
	mt.mu.Unlock()
}

// Get returns bid/ask/ts for a symbol. Returns zeros if not found.
func (mt *MultiTick) Get(symbol string) (bid, ask float64, ts int64) {
	key := strings.ToLower(symbol)
	mt.mu.RLock()
	defer mt.mu.RUnlock()
	t := mt.ticks[key]
	if t == nil {
		return 0, 0, 0
	}
	return t.Bid, t.Ask, t.Timestamp
}

// ── Backward compatibility ──────────────────────────────────────────────

// GlobalTick is kept for backward compatibility; it mirrors XAUUSDT data.
var GlobalTick = &legacyTick{}

type legacyTick struct {
	mu sync.RWMutex
	BinanceTick
}

// GetTick returns XAUUSDT bid/ask/ts (backward-compatible).
func GetTick() (bid, ask float64, ts int64) {
	GlobalTick.mu.RLock()
	defer GlobalTick.mu.RUnlock()
	return GlobalTick.Bid, GlobalTick.Ask, GlobalTick.Timestamp
}

// ── WebSocket connection ────────────────────────────────────────────────

// BookTickerMsg matches Binance futures bookTicker stream.
type BookTickerMsg struct {
	EventType string `json:"e"`
	EventTime int64  `json:"E"`
	UpdateID  int64  `json:"u"`
	Symbol    string `json:"s"`
	BidPrice  string `json:"b"`
	BidQty    string `json:"B"`
	AskPrice  string `json:"a"`
	AskQty   string `json:"A"`
	TradeTime int64  `json:"T"`
}

// CombinedStreamMsg wraps the combined-stream envelope.
type CombinedStreamMsg struct {
	Stream string          `json:"stream"` // e.g. "xauusdt@bookTicker"
	Data   json.RawMessage `json:"data"`
}

// RunBinanceWS connects to Binance WS and dispatches ticks to GlobalTicks.
// wsURL can be a single-stream URL or a combined-stream URL.
func RunBinanceWS(wsURL string) {
	for {
		connectBinanceWS(wsURL)
		log.Println("[BinanceWS] Reconnecting in 3s...")
		time.Sleep(3 * time.Second)
	}
}

func connectBinanceWS(wsURL string) {
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		log.Printf("[BinanceWS] Dial error: %v", err)
		return
	}
	defer conn.Close()
	log.Println("[BinanceWS] Connected to", wsURL)

	// Detect combined-stream mode (URL contains "/stream?streams=")
	isCombined := strings.Contains(wsURL, "/stream?streams=")

	msgCount := 0
	for {
		_, raw, err := conn.ReadMessage()
		if err != nil {
			log.Printf("[BinanceWS] Read error: %v", err)
			return
		}

		var tick BookTickerMsg

		if isCombined {
			// Combined stream: {"stream":"xauusdt@bookTicker","data":{...}}
			var envelope CombinedStreamMsg
			if err := json.Unmarshal(raw, &envelope); err != nil {
				continue
			}
			if err := json.Unmarshal(envelope.Data, &tick); err != nil {
				continue
			}
		} else {
			// Single stream: direct bookTicker message
			if err := json.Unmarshal(raw, &tick); err != nil {
				continue
			}
		}

		bid, errB := strconv.ParseFloat(tick.BidPrice, 64)
		ask, errA := strconv.ParseFloat(tick.AskPrice, 64)
		if errB != nil || errA != nil || bid <= 0 || ask <= 0 {
			continue
		}

		symbol := strings.ToUpper(tick.Symbol)

		// Store in multi-symbol map
		GlobalTicks.Update(symbol, bid, ask)

		// Mirror to legacy GlobalTick for backward compat (XAUUSDT only)
		if symbol == "XAUUSDT" {
			GlobalTick.mu.Lock()
			GlobalTick.Bid = bid
			GlobalTick.Ask = ask
			GlobalTick.Timestamp = time.Now().UnixMilli()
			GlobalTick.mu.Unlock()
		}

		msgCount++
		if msgCount <= 10 {
			log.Printf("[BinanceWS] tick #%d: %s bid=%.4f ask=%.4f", msgCount, symbol, bid, ask)
		}
	}
}
