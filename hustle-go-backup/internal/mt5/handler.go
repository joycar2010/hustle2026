package mt5

import (
	"github.com/gin-gonic/gin"
	"hustle-go/internal/proxy"
)

// All MT5 routes are transparently forwarded to the Windows MT5 microservice.

func Positions(c *gin.Context)         { proxy.ToMT5Auth(c, "/mt5/positions") }
func PlaceOrder(c *gin.Context)        { proxy.ToMT5Auth(c, "/mt5/order") }
func ConnectionStatus(c *gin.Context)  { proxy.ToMT5Auth(c, "/mt5/connection/status") }
func Reconnect(c *gin.Context)         { proxy.ToMT5Auth(c, "/mt5/connection/reconnect") }
func AccountBalance(c *gin.Context)    { proxy.ToMT5Auth(c, "/mt5/account/balance") }
func AccountInfo(c *gin.Context)       { proxy.ToMT5Auth(c, "/mt5/account/info") }
func Symbols(c *gin.Context)           { proxy.ToMT5Auth(c, "/mt5/symbols") }
func Tick(c *gin.Context)              { proxy.ToMT5Auth(c, "/mt5/tick/"+c.Param("symbol")) }
func HistoryDeals(c *gin.Context)      { proxy.ToMT5Auth(c, "/mt5/history/deals") }
func HistoryOrders(c *gin.Context)     { proxy.ToMT5Auth(c, "/mt5/history/orders") }
func ClosePosition(c *gin.Context)     { proxy.ToMT5Auth(c, "/mt5/position/close") }
func CloseAll(c *gin.Context)          { proxy.ToMT5Auth(c, "/mt5/position/close-all") }
