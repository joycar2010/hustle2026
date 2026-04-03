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
	"ws:broadcast",        // generic broadcast (strategy_status, position_snapshot, etc.)
	"ws:market_data",      // market data (will be replaced by Go native push, but keep for compat)
	"ws:account_balance",  // account balance updates
	"ws:risk_metrics",     // risk metrics
	"ws:order_update",     // order fill events
	"ws:position_update",  // position changes
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

	// Confirm subscription
	if _, err := pubsub.Receive(ctx); err != nil {
		return err
	}
	log.Printf("[RedisBridge] Subscribed to channels: %v", bridgeChannels)

	ch := pubsub.Channel()
	for msg := range ch {
		// Validate it's a JSON object before forwarding
		var payload map[string]interface{}
		if err := json.Unmarshal([]byte(msg.Payload), &payload); err != nil {
			log.Printf("[RedisBridge] Invalid JSON on channel %s: %v", msg.Channel, err)
			continue
		}

		// Determine message type from channel name or payload
		msgType, _ := payload["type"].(string)
		if msgType == "" {
			// Derive type from channel name
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
			data = payload // forward whole payload if no data wrapper
		}

		GlobalHub.Broadcast(msgType, data)
	}
	return nil
}
