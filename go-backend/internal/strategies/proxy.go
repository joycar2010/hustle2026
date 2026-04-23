package strategies

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net/http"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/proxy"
)

// ProxyExecute POST /api/v1/strategies/execute/:strategy_type → Python
func ProxyExecute(c *gin.Context) {
	proxy.ToPython(c, c.Request.URL.RequestURI())
}

// ProxyClose POST /api/v1/strategies/close/:strategy_type → Python
func ProxyClose(c *gin.Context) {
	proxy.ToPython(c, c.Request.URL.RequestURI())
}

// ProxyExecution GET|POST /api/v1/strategies/execution/:task_id/* → Python
func ProxyExecution(c *gin.Context) {
	proxy.ToPython(c, c.Request.URL.RequestURI())
}

// ProxyWildcard — catch-all for unimplemented strategy sub-paths → Python
func ProxyWildcard(c *gin.Context) {
	proxy.ToPython(c, c.Request.URL.RequestURI())
}

// ProxyConfigUpsert proxies config save to Python with validation + audit log.
// Python handles all fields including trigger_check_interval, ladders, m_coin etc.
// Hardening:
//   1. Reject empty/non-JSON bodies before reaching Python
//   2. Validate strategy_type early (forward/reverse only)
//   3. Audit log for accountability
//   4. Re-inject body so Python can read it
func ProxyConfigUpsert(c *gin.Context) {
	userID := c.GetString("user_id")

	// Read body once
	body, err := c.GetRawData()
	if err != nil || len(body) == 0 {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": "missing request body"})
		return
	}

	// Quick validation: must be valid JSON with strategy_type
	var peek struct {
		StrategyType string `json:"strategy_type"`
	}
	if err := json.Unmarshal(body, &peek); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": "invalid JSON body"})
		return
	}
	if peek.StrategyType == "" {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": "strategy_type required"})
		return
	}
	if peek.StrategyType != "forward" && peek.StrategyType != "reverse" {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": "strategy_type must be forward or reverse"})
		return
	}

	// Audit log
	log.Printf("[AUDIT] strategy config upsert: user=%s strategy_type=%s body_size=%d",
		userID, peek.StrategyType, len(body))

	// Re-inject body for downstream proxy
	c.Request.Body = io.NopCloser(bytes.NewReader(body))
	c.Request.ContentLength = int64(len(body))

	proxy.ToPython(c, c.Request.URL.RequestURI())
}

// ProxyConfigGet proxies config read to Python
func ProxyConfigGet(c *gin.Context) {
	proxy.ToPython(c, c.Request.URL.RequestURI())
}
