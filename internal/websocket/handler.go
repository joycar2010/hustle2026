package ws

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 4096,
	CheckOrigin:     func(r *http.Request) bool { return true },
}

// HandleWS upgrades HTTP to WebSocket, authenticates JWT, registers with Hub
func HandleWS(c *gin.Context) {
	token := c.Query("token")
	userID, err := ValidateToken(token)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "authentication failed"})
		return
	}

	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		log.Printf("[WS] Upgrade error: %v", err)
		return
	}

	client := &Client{
		send:   make(chan []byte, 256),
		hub:    GlobalHub,
		userID: userID,
	}
	GlobalHub.register <- client

	// Send welcome message (matches Python behavior)
	welcome, _ := json.Marshal(map[string]interface{}{
		"type":      "connection",
		"message":   "Connected to Hustle XAU Arbitrage System",
		"user_id":   userID,
		"service":   "hustle-go",
		"timestamp": time.Now().UnixMilli(),
	})
	client.send <- welcome

	// Write pump
	go func() {
		defer conn.Close()
		for msg := range client.send {
			conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		}
	}()

	// Read pump
	defer func() {
		GlobalHub.unregister <- client
		conn.Close()
	}()
	conn.SetReadLimit(4096)
	conn.SetReadDeadline(time.Now().Add(90 * time.Second))
	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(90 * time.Second))
		return nil
	})

	for {
		_, msg, err := conn.ReadMessage()
		if err != nil {
			break
		}
		conn.SetReadDeadline(time.Now().Add(90 * time.Second))

		// Handle client commands
		var cmd map[string]interface{}
		if json.Unmarshal(msg, &cmd) == nil {
			if cmd["type"] == "request_snapshot" {
				// Forward snapshot request to Python via Redis
				// Python will publish position_snapshot back through ws:broadcast
				log.Printf("[WS] user=%s requested snapshot", userID)
			}
		}
	}
}

// HandleStats returns WS connection stats
func HandleStats(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"connections": gin.H{
			"total": GlobalHub.ClientCount(),
		},
		"service":   "hustle-go",
		"timestamp": time.Now().UnixMilli(),
	})
}
