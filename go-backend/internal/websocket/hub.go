package ws

import (
	"encoding/json"
	"log"
	"sync"
	"time"
)

const (
	MsgTypeSpread = "spread"
	MsgTypeTick   = "tick"
)

type PushMessage struct {
	Type      string      `json:"type"`
	Data      interface{} `json:"data"`
	PairCode  string      `json:"pair_code,omitempty"`
	Timestamp int64       `json:"timestamp"`
}

type Client struct {
	send            chan []byte
	hub             *Hub
	userID          string
	subscribedPairs map[string]bool
	mu              sync.RWMutex

	// Sub-account projection — set at handshake if login user is_subaccount=true.
	// When isSub is true, userID has already been swapped to parent_user_id so the
	// existing routing logic (SendToUser matches by userID) delivers parent events
	// to this client; we then multiply monetary fields by multiplier before send.
	isSub      bool
	multiplier float64
}

type Hub struct {
	clients    map[*Client]bool
	rooms      map[string]map[*Client]bool // pair_code → set of clients
	broadcast  chan []byte
	register   chan *Client
	unregister chan *Client
	mu         sync.RWMutex
}

var GlobalHub = NewHub()

func NewHub() *Hub {
	return &Hub{
		clients:    make(map[*Client]bool),
		rooms:      make(map[string]map[*Client]bool),
		broadcast:  make(chan []byte, 512),
		register:   make(chan *Client, 64),
		unregister: make(chan *Client, 64),
	}
}

func (h *Hub) Run() {
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.clients[client] = true
			h.mu.Unlock()
			log.Printf("[Hub] user=%s connected, total=%d", client.userID, h.ClientCount())

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client]; ok {
				// Remove from all rooms
				client.mu.RLock()
				for pc := range client.subscribedPairs {
					if room, ok := h.rooms[pc]; ok {
						delete(room, client)
						if len(room) == 0 {
							delete(h.rooms, pc)
						}
					}
				}
				client.mu.RUnlock()
				delete(h.clients, client)
				close(client.send)
			}
			h.mu.Unlock()
			log.Printf("[Hub] user=%s disconnected, total=%d", client.userID, h.ClientCount())

		case msg := <-h.broadcast:
			h.mu.RLock()
			for client := range h.clients {
				select {
				case client.send <- msg:
				default:
					// slow client — drop message (don't force-disconnect)
				}
			}
			h.mu.RUnlock()
		}
	}
}

func (h *Hub) ClientCount() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}

// Broadcast sends a message to ALL connected clients (global events).
func (h *Hub) Broadcast(msgType string, data interface{}) {
	msg := PushMessage{
		Type:      msgType,
		Data:      data,
		Timestamp: time.Now().UnixMilli(),
	}
	b, err := json.Marshal(msg)
	if err != nil {
		return
	}
	select {
	case h.broadcast <- b:
	default:
		log.Println("[Hub] Broadcast channel full, dropping")
	}
}

// BroadcastToRoom sends a message only to clients subscribed to a specific pair.
func (h *Hub) BroadcastToRoom(pairCode, msgType string, data interface{}) {
	msg := PushMessage{
		Type:      msgType,
		Data:      data,
		PairCode:  pairCode,
		Timestamp: time.Now().UnixMilli(),
	}
	b, err := json.Marshal(msg)
	if err != nil {
		return
	}
	h.mu.RLock()
	room := h.rooms[pairCode]
	if room == nil {
		h.mu.RUnlock()
		return
	}
	for client := range room {
		select {
		case client.send <- b:
		default:
			// slow client — skip
		}
	}
	h.mu.RUnlock()
}

// Subscribe adds a client to a pair room.
func (h *Hub) Subscribe(client *Client, pairCode string) {
	h.mu.Lock()
	if h.rooms[pairCode] == nil {
		h.rooms[pairCode] = make(map[*Client]bool)
	}
	h.rooms[pairCode][client] = true
	h.mu.Unlock()

	client.mu.Lock()
	if client.subscribedPairs == nil {
		client.subscribedPairs = make(map[string]bool)
	}
	client.subscribedPairs[pairCode] = true
	client.mu.Unlock()

	log.Printf("[Hub] user=%s subscribed to %s", client.userID, pairCode)
}

// Unsubscribe removes a client from a pair room.
func (h *Hub) Unsubscribe(client *Client, pairCode string) {
	h.mu.Lock()
	if room, ok := h.rooms[pairCode]; ok {
		delete(room, client)
		if len(room) == 0 {
			delete(h.rooms, pairCode)
		}
	}
	h.mu.Unlock()

	client.mu.Lock()
	delete(client.subscribedPairs, pairCode)
	client.mu.Unlock()

	log.Printf("[Hub] user=%s unsubscribed from %s", client.userID, pairCode)
}

// SendToUser sends a message to a specific user. When the client is a
// sub-account AND the msgType carries monetary data, we project (multiply)
// the payload per-client before marshaling.
func (h *Hub) SendToUser(userID string, msgType string, data interface{}) {
	base := PushMessage{
		Type:      msgType,
		Data:      data,
		Timestamp: time.Now().UnixMilli(),
	}
	bPlain, err := json.Marshal(base)
	if err != nil {
		return
	}

	h.mu.RLock()
	defer h.mu.RUnlock()
	for client := range h.clients {
		if client.userID != userID {
			continue
		}
		payload := bPlain
		if client.isSub && shouldProject(msgType) && client.multiplier != 1.0 {
			projMsg := PushMessage{
				Type:      msgType,
				Data:      projectPayload(data, client.multiplier),
				Timestamp: base.Timestamp,
			}
			if b2, err2 := json.Marshal(projMsg); err2 == nil {
				payload = b2
			}
		}
		select {
		case client.send <- payload:
		default:
		}
	}
}
