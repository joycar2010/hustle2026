package proxy

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/mt5config"
)

var httpClient = &http.Client{Timeout: 60 * time.Second}

func pythonBase() string {
	if u := os.Getenv("PYTHON_SERVICE_URL"); u != "" {
		return u
	}
	return "http://127.0.0.1:8000"
}

func mt5Base() string {
	if u := os.Getenv("MT5_SERVICE_URL"); u != "" {
		return u
	}
	bridges := mt5config.GetSystemBridges()
	if url, ok := bridges[2]; ok {
		return url
	}
	for _, url := range bridges {
		return url
	}
	return "http://127.0.0.1:8001"
}

func ForwardTo(c *gin.Context, baseURL, path string) {
	target := fmt.Sprintf("%s%s", baseURL, path)
	if c.Request.URL.RawQuery != "" {
		target += "?" + c.Request.URL.RawQuery
	}

	req, err := http.NewRequest(c.Request.Method, target, c.Request.Body)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	req.Header = c.Request.Header.Clone()

	resp, err := httpClient.Do(req)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"detail": "upstream error: " + err.Error()})
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	ct := resp.Header.Get("Content-Type")
	if ct == "" {
		ct = "application/json"
	}
	c.Data(resp.StatusCode, ct, body)
}

func ToPython(c *gin.Context, path string) {
	ForwardTo(c, pythonBase(), path)
}

func ToMT5(c *gin.Context, path string) {
	ForwardTo(c, mt5Base(), path)
}

func ToMT5Auth(c *gin.Context, path string) {
	k := os.Getenv("MT5_API_KEY")
	if k == "" {
		k = mt5config.BridgeAPIKey()
	}
	if k != "" {
		c.Request.Header.Set("X-Api-Key", k)
	}
	ForwardTo(c, mt5Base(), path)
}

func mt5UserBase() string {
	if u := os.Getenv("MT5_USER_SERVICE_URL"); u != "" {
		return u
	}
	for _, c := range mt5config.GetAllClients() {
		if !c.IsSystemService && c.BridgeURL != "" {
			return c.BridgeURL
		}
	}
	return "http://127.0.0.1:8002"
}

func ToMT5UserAuth(c *gin.Context, path string) {
	k := os.Getenv("MT5_API_KEY")
	if k == "" {
		k = mt5config.BridgeAPIKey()
	}
	if k != "" {
		c.Request.Header.Set("X-Api-Key", k)
	}
	ForwardTo(c, mt5UserBase(), path)
}
