package market

import (
	"encoding/json"
	"log"
	"time"

	"github.com/gorilla/websocket"
)

type okxWSMsg struct {
	Arg  map[string]string        `json:"arg"`
	Data []map[string]interface{} `json:"data"`
}

func RunOKXWS(symbols []string) {
	if len(symbols) == 0 {
		return
	}
	for {
		connectOKXWS(symbols)
		log.Println("[OKXWS] disconnected, reconnecting in 3s...")
		time.Sleep(3 * time.Second)
	}
}

func connectOKXWS(symbols []string) {
	url := "wss://ws.okx.com:8443/ws/v5/public"
	c, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		log.Printf("[OKXWS] dial error: %v", err)
		return
	}
	defer c.Close()
	log.Printf("[OKXWS] Connected, subscribing to %d symbols", len(symbols))

	// Subscribe to tickers
	type subArg struct {
		Channel string `json:"channel"`
		InstId  string `json:"instId"`
	}
	args := make([]subArg, len(symbols))
	for i, s := range symbols {
		args[i] = subArg{Channel: "tickers", InstId: s}
	}
	subMsg, _ := json.Marshal(map[string]interface{}{"op": "subscribe", "args": args})
	if err := c.WriteMessage(websocket.TextMessage, subMsg); err != nil {
		log.Printf("[OKXWS] subscribe error: %v", err)
		return
	}

	// Ping ticker
	go func() {
		for {
			time.Sleep(25 * time.Second)
			if err := c.WriteMessage(websocket.TextMessage, []byte("ping")); err != nil {
				return
			}
		}
	}()

	count := 0
	for {
		_, msg, err := c.ReadMessage()
		if err != nil {
			log.Printf("[OKXWS] read error: %v", err)
			return
		}
		if string(msg) == "pong" {
			continue
		}

		var m okxWSMsg
		if err := json.Unmarshal(msg, &m); err != nil {
			continue
		}
		if len(m.Data) == 0 || m.Arg["channel"] != "tickers" {
			continue
		}

		instId := m.Arg["instId"]
		d := m.Data[0]
		bid := parseFloat(toString(d["bidPx"]))
		ask := parseFloat(toString(d["askPx"]))
		if bid > 0 && ask > 0 {
			GlobalTicks.Update(instId, bid, ask)
			count++
			if count <= 10 {
				log.Printf("[OKXWS] tick #%d: %s bid=%.4f ask=%.4f", count, instId, bid, ask)
			}
		}
	}
}

func toString(v interface{}) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
