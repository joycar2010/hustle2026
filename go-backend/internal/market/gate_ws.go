package market

import (
	"encoding/json"
	"log"
	"time"

	"github.com/gorilla/websocket"
)

type gateWSMsg struct {
	Channel string                   `json:"channel"`
	Event   string                   `json:"event"`
	Result  []map[string]interface{} `json:"result"`
}

func RunGateWS(symbols []string) {
	if len(symbols) == 0 {
		return
	}
	for {
		connectGateWS(symbols)
		log.Println("[GateWS] disconnected, reconnecting in 3s...")
		time.Sleep(3 * time.Second)
	}
}

func connectGateWS(symbols []string) {
	url := "wss://fx-ws.gateio.ws/v4/ws/usdt"
	c, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		log.Printf("[GateWS] dial error: %v", err)
		return
	}
	defer c.Close()
	log.Printf("[GateWS] Connected, subscribing to %d symbols", len(symbols))

	// Subscribe
	subMsg, _ := json.Marshal(map[string]interface{}{
		"channel": "futures.tickers",
		"event":   "subscribe",
		"payload": symbols,
	})
	if err := c.WriteMessage(websocket.TextMessage, subMsg); err != nil {
		log.Printf("[GateWS] subscribe error: %v", err)
		return
	}

	// Ping every 15s
	go func() {
		for {
			time.Sleep(15 * time.Second)
			ping, _ := json.Marshal(map[string]interface{}{
				"channel": "futures.ping",
			})
			if err := c.WriteMessage(websocket.TextMessage, ping); err != nil {
				return
			}
		}
	}()

	count := 0
	for {
		_, msg, err := c.ReadMessage()
		if err != nil {
			log.Printf("[GateWS] read error: %v", err)
			return
		}

		var m gateWSMsg
		if err := json.Unmarshal(msg, &m); err != nil {
			continue
		}
		if m.Channel != "futures.tickers" || m.Event != "update" || len(m.Result) == 0 {
			continue
		}

		for _, d := range m.Result {
			contract := toString(d["contract"])
			if contract == "" {
				continue
			}
			bid := parseFloat(toString(d["highest_bid"]))
			ask := parseFloat(toString(d["lowest_ask"]))
			// Fallback to mark_price if no bid/ask
			if bid == 0 || ask == 0 {
				mp := parseFloat(toString(d["mark_price"]))
				if mp > 0 {
					bid = mp - 0.01
					ask = mp + 0.01
				}
			}
			if bid > 0 && ask > 0 {
				GlobalTicks.Update(4, contract, bid, ask)
				count++
				if count <= 10 {
					log.Printf("[GateWS] tick #%d: %s bid=%.4f ask=%.4f", count, contract, bid, ask)
				}
			}
		}
	}
}
