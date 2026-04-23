package healthwatch

import (
	"context"
	"log"
	"strconv"
	"sync"
	"time"

	"hustle-go/internal/agentclient"
	"hustle-go/internal/mt5config"

	"github.com/redis/go-redis/v9"
)

type watcher struct {
	rdb          *redis.Client
	failCounts   map[int]int
	mu           sync.Mutex
	agentDown    bool
	lastAgentErr time.Time
}

func Run(rdb *redis.Client) {
	intervalStr := mt5config.Get("health_check_interval_sec")
	interval := 30
	if v, err := strconv.Atoi(intervalStr); err == nil && v > 0 {
		interval = v
	}

	w := &watcher{
		rdb:        rdb,
		failCounts: make(map[int]int),
	}

	log.Printf("[healthwatch] started, interval=%ds", interval)

	for {
		w.tick()
		time.Sleep(time.Duration(interval) * time.Second)
	}
}

func (w *watcher) tick() {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	_, err := agentclient.Health(ctx)
	if err != nil {
		if !w.agentDown {
			w.agentDown = true
			w.lastAgentErr = time.Now()
			log.Printf("[healthwatch] ALERT: MT5 Agent unreachable: %v", err)
			w.publishAlert(ctx, "MT5 Agent 离线: "+err.Error())
		}
		return
	}
	if w.agentDown {
		w.agentDown = false
		log.Printf("[healthwatch] MT5 Agent recovered")
		w.publishAlert(ctx, "MT5 Agent 已恢复在线")
	}

	clients := mt5config.GetAllClients()
	for _, c := range clients {
		if c.BridgeURL == "" {
			continue
		}

		healthy, err := agentclient.BridgeHealthCheck(ctx, c.BridgeURL)
		w.mu.Lock()

		if err != nil || !healthy {
			w.failCounts[c.ClientID]++
			count := w.failCounts[c.ClientID]
			w.mu.Unlock()

			if count == 3 {
				log.Printf("[healthwatch] ALERT: %s bridge down %d times, attempting restart", c.ClientName, count)
				w.publishAlert(ctx, c.ClientName+" Bridge 连续3次不可达，正在尝试重启")

				if c.BridgeServiceName != "" {
					if restartErr := agentclient.BridgeRestart(ctx, c.BridgeServiceName); restartErr != nil {
						log.Printf("[healthwatch] restart %s failed: %v", c.BridgeServiceName, restartErr)
						w.publishAlert(ctx, c.ClientName+" Bridge 重启失败: "+restartErr.Error())
					} else {
						log.Printf("[healthwatch] restart %s triggered", c.BridgeServiceName)
					}
				}

				_ = mt5config.UpdateConnectionStatus(c.ClientID, "error")
			}
		} else {
			prevFails := w.failCounts[c.ClientID]
			w.failCounts[c.ClientID] = 0
			w.mu.Unlock()

			if prevFails >= 3 || c.ConnectionStatus == "error" {
				log.Printf("[healthwatch] %s bridge recovered", c.ClientName)
				_ = mt5config.UpdateConnectionStatus(c.ClientID, "connected")
				w.publishAlert(ctx, c.ClientName+" Bridge 已恢复连接")
			} else if c.ConnectionStatus != "connected" {
				_ = mt5config.UpdateConnectionStatus(c.ClientID, "connected")
			}
		}
	}
}

func (w *watcher) publishAlert(ctx context.Context, msg string) {
	alertPayload := `{"type":"mt5_health_alert","message":"` + msg + `","timestamp":"` + time.Now().Format(time.RFC3339) + `"}`
	w.rdb.Publish(ctx, "ws:broadcast", alertPayload)
	log.Printf("[healthwatch] alert: %s", msg)
}
