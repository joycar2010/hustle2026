package automation

import (
	"github.com/gin-gonic/gin"
	"hustle-go/internal/proxy"
)

func StartStrategy(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/automation/strategies/"+c.Param("strategy_id")+"/start")
}
func StopStrategy(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/automation/strategies/"+c.Param("strategy_id")+"/stop")
}
func RunningStrategies(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/automation/strategies/running")
}
func StartPositionMonitor(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/automation/position-monitor/start")
}
func StopPositionMonitor(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/automation/position-monitor/stop")
}
func PositionMonitorStatus(c *gin.Context) {
	proxy.ToPython(c, "/api/v1/automation/position-monitor/status")
}
