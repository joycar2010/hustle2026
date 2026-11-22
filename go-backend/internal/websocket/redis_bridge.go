package ws

import (
	"context"
	"encoding/json"
	"log"

	"github.com/redis/go-redis/v9"
)

// Python publishes business events to these Redis channels
// Go subscribes and forwards to all WS clients
var bridgeChannels = []string{
	"ws:broadcast",
	"ws:market_data",
	"ws:account_balance",
	"ws:risk_metrics",
	"ws:order_update",
	"ws:position_update",
	"ws:user_event",
}

// RunRedisBridge subscribes to Python-published channels and forwards to WS Hub
func RunRedisBridge(redisURL string) {
	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		log.Printf("[RedisBridge] Invalid Redis URL: %v", err)
		return
	}
	rdb := redis.NewClient(opt)
	ctx := context.Background()

	for {
		if err := subscribeBridge(ctx, rdb); err != nil {
			log.Printf("[RedisBridge] Subscribe error: %v, retrying...", err)
		}
	}
}

func subscribeBridge(ctx context.Context, rdb *redis.Client) error {
	pubsub := rdb.Subscribe(ctx, bridgeChannels...)
	defer pubsub.Close()

	if _, err := pubsub.Receive(ctx); err != nil {
		return err
	}
	log.Printf("[RedisBridge] Subscribed to channels: %v", bridgeChannels)

	ch := pubsub.Channel()
	for msg := range ch {
		var payload map[string]interface{}
		if err := json.Unmarshal([]byte(msg.Payload), &payload); err != nil {
			log.Printf("[RedisBridge] Invalid JSON on channel %s: %v", msg.Channel, err)
			continue
		}

		// Per-user events — route to specific user
		if msg.Channel == "ws:user_event" {
			userID, _ := payload["user_id"].(string)
			evtType, _ := payload["type"].(string)
			evtData, _ := payload["data"]
			if userID != "" && evtType != "" && evtData != nil {
				GlobalHub.SendToUser(userID, evtType, evtData)
			}
			continue
		}

		// Determine message type
		msgType, _ := payload["type"].(string)
		if msgType == "" {
			switch msg.Channel {
			case "ws:market_data":
				msgType = "market_data"
			case "ws:account_balance":
				msgType = "account_balance"
			case "ws:risk_metrics":
				msgType = "risk_metrics"
			case "ws:order_update":
				msgType = "order_update"
			case "ws:position_update":
				msgType = "position_update"
			default:
				msgType = "event"
			}
		}

		data, _ := payload["data"]
		if data == nil {
			data = payload
		}

		// Market data: route to pair room if pair_code present
		if msg.Channel == "ws:market_data" {
			pairCode, _ := payload["pair_code"].(string)
			if pairCode != "" {
				GlobalHub.BroadcastToRoom(pairCode, msgType, data)
				continue
			}
		}

		// Everything else: global broadcast
		GlobalHub.Broadcast(msgType, data)
	}
	return nil
}
