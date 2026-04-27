package market

import (
	"encoding/json"
	"log"
	"time"

	"github.com/gorilla/websocket"
)

type bitgetWSArg struct {
	InstType string `json:"instType"`
	Channel  string `json:"channel"`
	InstId   string `json:"instId"`
}

type bitgetWSTickData struct {
	InstId string `json:"instId"`
	BidPr  string `json:"bidPr"`
	AskPr  string `json:"askPr"`
}

type bitgetWSMsg struct {
	Action string             `json:"action"`
	Arg    bitgetWSArg        `json:"arg"`
	Data   []bitgetWSTickData `json:"data"`
}

func RunBitgetWS(symbols []string) {
	if len(symbols) == 0 {
		return
	}
	for {
		connectBitgetWS(symbols)
		log.Println("[BitgetWS] disconnected, reconnecting in 3s...")
		time.Sleep(3 * time.Second)
	}
}

func connectBitgetWS(symbols []string) {
	wsURL := "wss://ws.bitget.com/v2/ws/public"
	c, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		log.Printf("[BitgetWS] dial error: %v", err)
		return
	}
	defer c.Close()
	log.Printf("[BitgetWS] Connected, subscribing to %d symbols", len(symbols))

	type subArg struct {
		InstType string `json:"instType"`
		Channel  string `json:"channel"`
		InstId   string `json:"instId"`
	}
	args := make([]subArg, len(symbols))
	for i, s := range symbols {
		args[i] = subArg{InstType: "USDT-FUTURES", Channel: "ticker", InstId: s}
	}
	subMsg, _ := json.Marshal(map[string]interface{}{"op": "subscribe", "args": args})
	if err := c.WriteMessage(websocket.TextMessage, subMsg); err != nil {
		log.Printf("[BitgetWS] subscribe error: %v", err)
		return
	}

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
			log.Printf("[BitgetWS] read error: %v", err)
			return
		}
		if string(msg) == "pong" {
			continue
		}

		var m bitgetWSMsg
		if err := json.Unmarshal(msg, &m); err != nil {
			continue
		}
		if len(m.Data) == 0 || m.Arg.Channel != "ticker" {
			continue
		}

		d := m.Data[0]
		instId := m.Arg.InstId
		if instId == "" {
			instId = d.InstId
		}
		bid := parseFloat(d.BidPr)
		ask := parseFloat(d.AskPr)
		if bid > 0 && ask > 0 {
			GlobalTicks.Update(6, instId, bid, ask)
			count++
			if count <= 10 {
				log.Printf("[BitgetWS] tick #%d: %s bid=%.4f ask=%.4f", count, instId, bid, ask)
			}
		}
	}
}
