package sysops

import (
	"github.com/gin-gonic/gin"
	"hustle-go/internal/monitor"
	"hustle-go/internal/proxy"
)

// All system/security/ssl/proxies/sounds ops are forwarded to Python.
// These are low-frequency admin endpoints; no value in reimplementing.
//
// Exception: /api/v1/system/status is intercepted and served Go-native so
// the status panel keeps working when the Python backend is down.

func Wildcard(c *gin.Context) {
	path := c.Request.URL.Path
	if path == "/api/v1/system/status" && c.Request.Method == "GET" {
		monitor.SystemStatus(c)
		return
	}
	proxy.ToPython(c, path)
}
