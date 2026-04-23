package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	ws "hustle-go/internal/websocket"
)

// JWTAuth extracts and validates Bearer token, sets user_id in context
func JWTAuth() gin.HandlerFunc {
	return func(c *gin.Context) {
		var token string

		// Try Authorization header first
		auth := c.GetHeader("Authorization")
		if strings.HasPrefix(auth, "Bearer ") {
			token = strings.TrimPrefix(auth, "Bearer ")
		}
		// Fallback to query param (for WS compat)
		if token == "" {
			token = c.Query("token")
		}

		if token == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "Not authenticated"})
			return
		}

		userID, err := ws.ValidateToken(token)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "Invalid token"})
			return
		}

		c.Set("user_id", userID)
		c.Next()
	}
}
