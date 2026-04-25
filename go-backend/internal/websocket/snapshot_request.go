package ws

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"hustle-go/internal/db"
)

// requestSnapshot publishes a request to Python so it pushes a fresh
// position_snapshot to the requesting user. Bypasses the 1s broadcast cycle.
func requestSnapshot(userID, pairCode string) {
	rdb := db.Redis()
	if rdb == nil {
		return
	}
	payload := map[string]interface{}{
		"user_id":   userID,
		"pair_code": pairCode,
		"ts":        time.Now().UnixMilli(),
	}
	b, err := json.Marshal(payload)
	if err != nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := rdb.Publish(ctx, "ws:snapshot_request", string(b)).Err(); err != nil {
		log.Printf("[WS] snapshot_request publish error: %v", err)
	}
}

// requestData publishes a generic data request to Python via Redis.
func requestData(userID, channel string, params map[string]interface{}) {
	rdb := db.Redis()
	if rdb == nil {
		return
	}
	payload := map[string]interface{}{
		"user_id": userID,
		"channel": channel,
		"params":  params,
		"ts":      time.Now().UnixMilli(),
	}
	b, err := json.Marshal(payload)
	if err != nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := rdb.Publish(ctx, "ws:data_request", string(b)).Err(); err != nil {
		log.Printf("[WS] data_request publish error: %v", err)
	}
}
