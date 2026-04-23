package agentclient

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"hustle-go/internal/mt5config"
)

var httpClient = &http.Client{Timeout: 30 * time.Second}

func doRequest(ctx context.Context, method, path string, body string) ([]byte, int, error) {
	url := mt5config.AgentURL() + path
	var bodyReader io.Reader
	if body != "" {
		bodyReader = strings.NewReader(body)
	}

	req, err := http.NewRequestWithContext(ctx, method, url, bodyReader)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("X-API-Key", mt5config.AgentAPIKey())
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("agent unreachable: %v", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	return data, resp.StatusCode, nil
}

type HealthResponse struct {
	Status  string `json:"status"`
	Agent   string `json:"agent"`
	Version string `json:"version"`
}

func Health(ctx context.Context) (*HealthResponse, error) {
	data, code, err := doRequest(ctx, http.MethodGet, "/health", "")
	if err != nil {
		return nil, err
	}
	if code != 200 {
		return nil, fmt.Errorf("agent /health returned %d", code)
	}
	var h HealthResponse
	if err := json.Unmarshal(data, &h); err != nil {
		return nil, err
	}
	return &h, nil
}

type BridgeStatusResponse struct {
	ServiceName string `json:"service_name"`
	Status      string `json:"status"`
	IsRunning   bool   `json:"is_running"`
}

func BridgeStatus(ctx context.Context, serviceName string) (*BridgeStatusResponse, error) {
	data, code, err := doRequest(ctx, http.MethodGet, "/bridge/"+serviceName+"/status", "")
	if err != nil {
		return nil, err
	}
	if code != 200 {
		return nil, fmt.Errorf("bridge status returned %d: %s", code, string(data))
	}
	var s BridgeStatusResponse
	if err := json.Unmarshal(data, &s); err != nil {
		return nil, err
	}
	return &s, nil
}

func BridgeRestart(ctx context.Context, serviceName string) error {
	_, code, err := doRequest(ctx, http.MethodPost, "/bridge/"+serviceName+"/restart", "")
	if err != nil {
		return err
	}
	if code != 200 {
		return fmt.Errorf("bridge restart returned %d", code)
	}
	return nil
}

func BridgeStart(ctx context.Context, serviceName string) error {
	_, code, err := doRequest(ctx, http.MethodPost, "/bridge/"+serviceName+"/start", "")
	if err != nil {
		return err
	}
	if code != 200 {
		return fmt.Errorf("bridge start returned %d", code)
	}
	return nil
}

type InstanceInfo struct {
	Name         string `json:"instance_name"`
	IsRunning    bool   `json:"is_running"`
	HealthStatus struct {
		IsRunning bool `json:"is_running"`
		Details   struct {
			MemoryMB float64 `json:"memory_mb"`
		} `json:"details"`
	} `json:"health_status"`
}

func ListInstances(ctx context.Context) ([]InstanceInfo, error) {
	data, code, err := doRequest(ctx, http.MethodGet, "/instances", "")
	if err != nil {
		return nil, err
	}
	if code != 200 {
		return nil, fmt.Errorf("list instances returned %d", code)
	}
	var instances []InstanceInfo
	if err := json.Unmarshal(data, &instances); err != nil {
		return nil, err
	}
	return instances, nil
}

func BridgeHealthCheck(ctx context.Context, bridgeURL string) (bool, error) {
	url := bridgeURL + "/health"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return false, err
	}
	req.Header.Set("X-Api-Key", mt5config.BridgeAPIKey())

	resp, err := httpClient.Do(req)
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	return resp.StatusCode == 200, nil
}
