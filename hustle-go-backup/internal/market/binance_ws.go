package market

import (
	"encoding/json"
	"log"
	"strconv"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

type BinanceTick struct {
	Bid       float64
	Ask       float64
	Timestamp int64
	mu        sync.RWMutex
}

var GlobalTick = &BinanceTick{}

// BookTickerMsg matches Binance futures bookTicker stream exactly.
// Note: JSON has both "e" (string event type) and "E" (int64 event time).
// Go's encoding/json is case-insensitive by default, so we must declare both
// to prevent "E" (number) from being matched to the "e" (string) field.
type BookTickerMsg struct {
	EventType  string `json:"e"`  // "bookTicker"
	EventTime  int64  `json:"E"`  // event time ms (must be declared to avoid collision)
	UpdateID   int64  `json:"u"`
	Symbol     string `json:"s"`
	BidPrice   string `json:"b"`
	BidQty     string `json:"B"`
	AskPrice   string `json:"a"`
	AskQty     string `json:"A"`
	TradeTime  int64  `json:"T"`
}

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

	msgCount := 0
	for {
		_, msg, err := conn.ReadMessage()
		if err != nil {
			log.Printf("[BinanceWS] Read error: %v", err)
			return
		}

		var tick BookTickerMsg
		if err := json.Unmarshal(msg, &tick); err != nil {
			log.Printf("[BinanceWS] Unmarshal error: %v", err)
			continue
		}

		bid, errB := strconv.ParseFloat(tick.BidPrice, 64)
		ask, errA := strconv.ParseFloat(tick.AskPrice, 64)
		if errB != nil || errA != nil || bid <= 0 || ask <= 0 {
			continue
		}

		GlobalTick.mu.Lock()
		GlobalTick.Bid = bid
		GlobalTick.Ask = ask
		GlobalTick.Timestamp = time.Now().UnixMilli()
		GlobalTick.mu.Unlock()

		msgCount++
		if msgCount <= 3 {
			log.Printf("[BinanceWS] tick #%d: bid=%.2f ask=%.2f", msgCount, bid, ask)
		}
	}
}

func GetTick() (bid, ask float64, ts int64) {
	GlobalTick.mu.RLock()
	defer GlobalTick.mu.RUnlock()
	return GlobalTick.Bid, GlobalTick.Ask, GlobalTick.Timestamp
}
