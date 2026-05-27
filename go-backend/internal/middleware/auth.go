package middleware

import (
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/auth"
	ws "hustle-go/internal/websocket"
)

const renewalThreshold = 2 * time.Hour

func JWTAuth() gin.HandlerFunc {
	return func(c *gin.Context) {
		var rawToken string
		if h := c.GetHeader("Authorization"); strings.HasPrefix(h, "Bearer ") {
			rawToken = strings.TrimPrefix(h, "Bearer ")
		}
		if rawToken == "" {
			rawToken = c.Query("token")
		}
		if rawToken == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "Not authenticated"})
			return
		}

		userID, exp, err := ws.ParseTokenExp(rawToken)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "Invalid token"})
			return
		}

		c.Set("user_id", userID)

		// Sliding window: set renewal header BEFORE handler writes the response
		remaining := time.Until(time.Unix(exp, 0))
		if remaining > 0 && remaining < renewalThreshold {
			if newToken, err := auth.MakeToken(userID); err == nil {
				c.Header("X-New-Token", newToken)
			}
		}

		c.Next()
	}
}
