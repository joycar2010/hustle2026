package proxy

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
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
	return "http://127.0.0.1:8001"
}

// ForwardTo proxies the current request to baseURL+path, preserving method/headers/body/query.
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

// ToPython proxies to the Python service.
func ToPython(c *gin.Context, path string) {
	ForwardTo(c, pythonBase(), path)
}

// ToMT5 proxies to the Windows MT5 microservice.
func ToMT5(c *gin.Context, path string) {
	ForwardTo(c, mt5Base(), path)
}

// ToMT5Auth proxies to the MT5 microservice adding X-Api-Key header.
func ToMT5Auth(c *gin.Context, path string) {
	if k := os.Getenv("MT5_API_KEY"); k != "" {
		c.Request.Header.Set("X-Api-Key", k)
	}
	ForwardTo(c, mt5Base(), path)
}
