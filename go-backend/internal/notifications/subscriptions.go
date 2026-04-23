package notifications

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
)

var adminRoles = map[string]bool{
	"超级管理员": true, "系统管理员": true, "安全管理员": true,
	"管理员": true, "admin": true, "super_admin": true,
}

func isAdmin(ctx context.Context, userID string) bool {
	var role string
	db.Pool().QueryRow(ctx, `SELECT role FROM users WHERE user_id=$1::uuid`, userID).Scan(&role)
	return adminRoles[role]
}

// GetActiveTemplates GET /api/v1/notifications/templates/active
func GetActiveTemplates(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	rows, err := db.Pool().Query(ctx,
		`SELECT template_id::text, template_key, template_name, category, enable_feishu
		 FROM notification_templates
		 WHERE is_active = true AND enable_feishu = true
		 ORDER BY category, template_name`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()

	var templates []gin.H
	for rows.Next() {
		var id, key, name, category string
		var feishu bool
		rows.Scan(&id, &key, &name, &category, &feishu)
		templates = append(templates, gin.H{
			"template_id":   id,
			"template_key":  key,
			"template_name": name,
			"category":      category,
			"enable_feishu": feishu,
		})
	}
	if templates == nil {
		templates = []gin.H{}
	}
	c.JSON(http.StatusOK, templates)
}

// GetSubscriptions GET /api/v1/notifications/subscriptions/:user_id
func GetSubscriptions(c *gin.Context) {
	targetUID := c.Param("user_id")
	callerID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if !isAdmin(ctx, callerID) {
		c.JSON(http.StatusForbidden, gin.H{"detail": "仅管理员可操作"})
		return
	}

	rows, err := db.Pool().Query(ctx,
		`SELECT ns.trader_user_id::text, u.username,
		        ns.template_id::text, nt.template_name, nt.category
		 FROM notification_subscriptions ns
		 JOIN users u ON u.user_id = ns.trader_user_id
		 JOIN notification_templates nt ON nt.template_id = ns.template_id
		 WHERE ns.subscriber_user_id = $1::uuid AND ns.is_enabled = true
		 ORDER BY u.username, nt.category, nt.template_name`, targetUID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()

	var subs []gin.H
	for rows.Next() {
		var traderID, username, templateID, templateName, category string
		rows.Scan(&traderID, &username, &templateID, &templateName, &category)
		subs = append(subs, gin.H{
			"trader_user_id": traderID,
			"username":       username,
			"template_id":    templateID,
			"template_name":  templateName,
			"category":       category,
		})
	}
	if subs == nil {
		subs = []gin.H{}
	}
	c.JSON(http.StatusOK, subs)
}

type templateSub struct {
	TraderUserID string   `json:"trader_user_id"`
	TemplateIDs  []string `json:"template_ids"`
}

// PutSubscriptions PUT /api/v1/notifications/subscriptions/:user_id
// Body: { "subscriptions": [{ "trader_user_id": "...", "template_ids": ["id1","id2"] }] }
func PutSubscriptions(c *gin.Context) {
	targetUID := c.Param("user_id")
	callerID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if !isAdmin(ctx, callerID) {
		c.JSON(http.StatusForbidden, gin.H{"detail": "仅管理员可操作"})
		return
	}

	var body struct {
		Subscriptions []templateSub `json:"subscriptions"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}

	tx, err := db.Pool().Begin(ctx)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer tx.Rollback(ctx)

	// Delete all existing subscriptions for this subscriber
	tx.Exec(ctx, `DELETE FROM notification_subscriptions WHERE subscriber_user_id = $1::uuid`, targetUID)

	// Insert new: one row per trader x template
	count := 0
	for _, sub := range body.Subscriptions {
		for _, tid := range sub.TemplateIDs {
			tx.Exec(ctx,
				`INSERT INTO notification_subscriptions
				 (subscriber_user_id, trader_user_id, template_id, is_enabled)
				 VALUES ($1::uuid, $2::uuid, $3::uuid, true) ON CONFLICT DO NOTHING`,
				targetUID, sub.TraderUserID, tid)
			count++
		}
	}

	if err := tx.Commit(ctx); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "通知订阅已保存", "count": count})
}
