package sysops

import (
	"github.com/gin-gonic/gin"
	"hustle-go/internal/proxy"
)

// All system/security/ssl/proxies/sounds ops are forwarded to Python.
// These are low-frequency admin endpoints; no value in reimplementing.

func Wildcard(c *gin.Context) {
	proxy.ToPython(c, c.Request.URL.Path)
}
