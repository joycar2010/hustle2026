package notifications

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
)

type notificationRow struct {
	NotificationID string    `json:"notification_id"`
	UserID         string    `json:"user_id"`
	Type           string    `json:"type"`
	Title          string    `json:"title"`
	Message        string    `json:"message"`
	IsRead         bool      `json:"is_read"`
	CreatedAt      time.Time `json:"created_at"`
}

func scanNotification(row interface{ Scan(...any) error }) (*notificationRow, error) {
	n := &notificationRow{}
	return n, row.Scan(&n.NotificationID, &n.UserID, &n.Type, &n.Title, &n.Message, &n.IsRead, &n.CreatedAt)
}

const selectNotification = `SELECT notification_id::text, user_id::text, type, title, message, is_read, created_at
	FROM notifications`

// ListNotifications GET /api/v1/notifications
func ListNotifications(c *gin.Context) {
	userID := c.GetString("user_id")
	unreadOnly := c.Query("unread") == "true"
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	query := selectNotification + ` WHERE user_id=$1::uuid`
	if unreadOnly {
		query += ` AND is_read=false`
	}
	query += ` ORDER BY created_at DESC LIMIT 100`

	rows, err := db.Pool().Query(ctx, query, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var notifications []*notificationRow
	for rows.Next() {
		n, err := scanNotification(rows)
		if err == nil {
			notifications = append(notifications, n)
		}
	}
	if notifications == nil {
		notifications = []*notificationRow{}
	}
	c.JSON(http.StatusOK, notifications)
}

// MarkRead PUT /api/v1/notifications/:notification_id/read
func MarkRead(c *gin.Context) {
	userID := c.GetString("user_id")
	notifID := c.Param("notification_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	tag, err := db.Pool().Exec(ctx,
		`UPDATE notifications SET is_read=true WHERE notification_id=$1::uuid AND user_id=$2::uuid`,
		notifID, userID)
	if err != nil || tag.RowsAffected() == 0 {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Notification not found"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "Marked as read"})
}

// MarkAllRead PUT /api/v1/notifications/read-all
func MarkAllRead(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	db.Pool().Exec(ctx, `UPDATE notifications SET is_read=true WHERE user_id=$1::uuid`, userID)
	c.JSON(http.StatusOK, gin.H{"message": "All notifications marked as read"})
}

// DeleteNotification DELETE /api/v1/notifications/:notification_id
func DeleteNotification(c *gin.Context) {
	userID := c.GetString("user_id")
	notifID := c.Param("notification_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	tag, err := db.Pool().Exec(ctx,
		`DELETE FROM notifications WHERE notification_id=$1::uuid AND user_id=$2::uuid`,
		notifID, userID)
	if err != nil || tag.RowsAffected() == 0 {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Notification not found"})
		return
	}
	c.Status(http.StatusNoContent)
}

// GetUnreadCount GET /api/v1/notifications/unread-count
func GetUnreadCount(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var count int
	db.Pool().QueryRow(ctx,
		`SELECT COUNT(*) FROM notifications WHERE user_id=$1::uuid AND is_read=false`, userID).Scan(&count)
	c.JSON(http.StatusOK, gin.H{"unread_count": count})
}

// ── Notification Configs ───────────────────────────────────────────────────

type notifConfigRow struct {
	ConfigID    string          `json:"config_id"`
	ServiceType string          `json:"service_type"`
	IsEnabled   bool            `json:"is_enabled"`
	ConfigData  json.RawMessage `json:"config_data"`
	CreatedAt   time.Time       `json:"created_at"`
	UpdatedAt   time.Time       `json:"updated_at"`
}

func scanNotifConfig(row interface{ Scan(...any) error }) (*notifConfigRow, error) {
	n := &notifConfigRow{}
	return n, row.Scan(&n.ConfigID, &n.ServiceType, &n.IsEnabled, &n.ConfigData, &n.CreatedAt, &n.UpdatedAt)
}

const selectNotifConfig = `SELECT config_id::text, service_type, is_enabled, config_data, created_at, updated_at
	FROM notification_configs`

// ListNotifConfigs GET /api/v1/notifications/configs
func ListNotifConfigs(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := db.Pool().Query(ctx, selectNotifConfig+` ORDER BY service_type`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var configs []*notifConfigRow
	for rows.Next() {
		n, err := scanNotifConfig(rows)
		if err == nil {
			configs = append(configs, n)
		}
	}
	if configs == nil {
		configs = []*notifConfigRow{}
	}
	c.JSON(http.StatusOK, configs)
}

// UpsertNotifConfig PUT /api/v1/notifications/configs/:service_type
func UpsertNotifConfig(c *gin.Context) {
	serviceType := c.Param("service_type")
	var body struct {
		IsEnabled  *bool           `json:"is_enabled"`
		ConfigData json.RawMessage `json:"config_data"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	isEnabled := false
	if body.IsEnabled != nil {
		isEnabled = *body.IsEnabled
	}
	configData := json.RawMessage(`{}`)
	if body.ConfigData != nil {
		configData = body.ConfigData
	}

	n, err := scanNotifConfig(db.Pool().QueryRow(ctx,
		`INSERT INTO notification_configs (service_type, is_enabled, config_data)
		 VALUES ($1, $2, $3)
		 ON CONFLICT (service_type) DO UPDATE
		   SET is_enabled=$2, config_data=$3, updated_at=NOW()
		 RETURNING config_id::text, service_type, is_enabled, config_data, created_at, updated_at`,
		serviceType, isEnabled, configData))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, n)
}
