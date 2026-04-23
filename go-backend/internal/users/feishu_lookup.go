package users

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
)

// FeishuLookup POST /api/v1/users/feishu-lookup
// Body: { "mobile": "13800138000" }
// Returns: { "open_id": "ou_xxx", "union_id": "on_xxx", "name": "..." }
func FeishuLookup(c *gin.Context) {
	callerID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	if !isAdmin(ctx, callerID) {
		c.JSON(http.StatusForbidden, gin.H{"detail": "仅管理员可操作"})
		return
	}

	var req struct {
		Mobile string `json:"mobile" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}

	// 1. Get feishu app credentials from DB
	var configData json.RawMessage
	err := db.Pool().QueryRow(ctx,
		`SELECT config_data FROM notification_configs WHERE service_type='feishu' AND is_enabled=true`,
	).Scan(&configData)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "飞书配置未找到或未启用"})
		return
	}

	var cfg struct {
		AppID     string `json:"app_id"`
		AppSecret string `json:"app_secret"`
	}
	json.Unmarshal(configData, &cfg)
	if cfg.AppID == "" || cfg.AppSecret == "" {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "飞书 app_id/app_secret 缺失"})
		return
	}

	// 2. Get tenant_access_token
	tokenBody, _ := json.Marshal(map[string]string{
		"app_id":     cfg.AppID,
		"app_secret": cfg.AppSecret,
	})
	tokenResp, err := http.Post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
		"application/json", bytes.NewReader(tokenBody))
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"detail": "飞书认证请求失败: " + err.Error()})
		return
	}
	defer tokenResp.Body.Close()
	tokenRaw, _ := io.ReadAll(tokenResp.Body)

	var tokenResult struct {
		Code              int    `json:"code"`
		Msg               string `json:"msg"`
		TenantAccessToken string `json:"tenant_access_token"`
	}
	json.Unmarshal(tokenRaw, &tokenResult)
	if tokenResult.Code != 0 || tokenResult.TenantAccessToken == "" {
		c.JSON(http.StatusBadGateway, gin.H{"detail": "飞书Token获取失败: " + tokenResult.Msg})
		return
	}
	token := tokenResult.TenantAccessToken

	// 3. batch_get_id by mobile (get open_id)
	batchBody, _ := json.Marshal(map[string][]string{"mobiles": {req.Mobile}})
	batchReq, _ := http.NewRequest("POST",
		"https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id",
		bytes.NewReader(batchBody))
	batchReq.Header.Set("Authorization", "Bearer "+token)
	batchReq.Header.Set("Content-Type", "application/json")

	batchResp, err := http.DefaultClient.Do(batchReq)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"detail": "飞书查询请求失败: " + err.Error()})
		return
	}
	defer batchResp.Body.Close()
	batchRaw, _ := io.ReadAll(batchResp.Body)

	var batchResult struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
		Data struct {
			UserList []struct {
				UserID string `json:"user_id"`
			} `json:"user_list"`
		} `json:"data"`
	}
	json.Unmarshal(batchRaw, &batchResult)
	if batchResult.Code != 0 {
		c.JSON(http.StatusBadGateway, gin.H{"detail": "飞书查询失败: " + batchResult.Msg})
		return
	}
	if len(batchResult.Data.UserList) == 0 || batchResult.Data.UserList[0].UserID == "" {
		c.JSON(http.StatusNotFound, gin.H{"detail": fmt.Sprintf("未找到手机号 %s 对应的飞书用户", req.Mobile)})
		return
	}
	openID := batchResult.Data.UserList[0].UserID

	// 4. Get user detail (for union_id and name)
	detailReq, _ := http.NewRequest("GET",
		fmt.Sprintf("https://open.feishu.cn/open-apis/contact/v3/users/%s?user_id_type=open_id", openID),
		nil)
	detailReq.Header.Set("Authorization", "Bearer "+token)

	detailResp, err := http.DefaultClient.Do(detailReq)
	if err != nil {
		// Return at least open_id
		c.JSON(http.StatusOK, gin.H{"open_id": openID, "union_id": "", "name": ""})
		return
	}
	defer detailResp.Body.Close()
	detailRaw, _ := io.ReadAll(detailResp.Body)

	var detailResult struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
		Data struct {
			User struct {
				OpenID  string `json:"open_id"`
				UnionID string `json:"union_id"`
				Name    string `json:"name"`
			} `json:"user"`
		} `json:"data"`
	}
	json.Unmarshal(detailRaw, &detailResult)

	unionID := detailResult.Data.User.UnionID
	name := detailResult.Data.User.Name
	if openID == "" {
		openID = detailResult.Data.User.OpenID
	}

	c.JSON(http.StatusOK, gin.H{
		"open_id":  openID,
		"union_id": unionID,
		"name":     name,
	})
}
