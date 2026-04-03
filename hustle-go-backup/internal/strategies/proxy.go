package strategies

import (
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
