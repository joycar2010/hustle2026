package rbac

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"hustle-go/internal/db"
)

// ── Roles ──────────────────────────────────────────────────────────────────

type roleRow struct {
	RoleID      string    `json:"role_id"`
	RoleName    string    `json:"role_name"`
	RoleCode    string    `json:"role_code"`
	Description *string   `json:"description"`
	IsActive    bool      `json:"is_active"`
	IsSystem    bool      `json:"is_system"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}

func scanRole(row interface{ Scan(...any) error }) (*roleRow, error) {
	r := &roleRow{}
	return r, row.Scan(&r.RoleID, &r.RoleName, &r.RoleCode, &r.Description,
		&r.IsActive, &r.IsSystem, &r.CreatedAt, &r.UpdatedAt)
}

const selectRole = `SELECT role_id::text, role_name, role_code, description,
	is_active, is_system, created_at, updated_at FROM roles`

// ListRoles GET /api/v1/rbac/roles
func ListRoles(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := db.Pool().Query(ctx, selectRole+` ORDER BY created_at`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var roles []*roleRow
	for rows.Next() {
		r, err := scanRole(rows)
		if err == nil {
			roles = append(roles, r)
		}
	}
	if roles == nil {
		roles = []*roleRow{}
	}
	c.JSON(http.StatusOK, roles)
}

// GetRole GET /api/v1/rbac/roles/:role_id
func GetRole(c *gin.Context) {
	roleID := c.Param("role_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	r, err := scanRole(db.Pool().QueryRow(ctx, selectRole+` WHERE role_id=$1::uuid`, roleID))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Role not found"})
		return
	}
	c.JSON(http.StatusOK, r)
}

// CreateRole POST /api/v1/rbac/roles
func CreateRole(c *gin.Context) {
	callerID := c.GetString("user_id")
	var body struct {
		RoleName    string  `json:"role_name" binding:"required"`
		RoleCode    string  `json:"role_code" binding:"required"`
		Description *string `json:"description"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	r, err := scanRole(db.Pool().QueryRow(ctx,
		`INSERT INTO roles (role_name, role_code, description, created_by, updated_by)
		 VALUES ($1, $2, $3, $4::uuid, $4::uuid)
		 RETURNING role_id::text, role_name, role_code, description, is_active, is_system, created_at, updated_at`,
		body.RoleName, body.RoleCode, body.Description, callerID))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, r)
}

// UpdateRole PUT /api/v1/rbac/roles/:role_id
func UpdateRole(c *gin.Context) {
	roleID := c.Param("role_id")
	callerID := c.GetString("user_id")
	var body struct {
		RoleName    *string `json:"role_name"`
		Description *string `json:"description"`
		IsActive    *bool   `json:"is_active"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if body.RoleName != nil {
		db.Pool().Exec(ctx, `UPDATE roles SET role_name=$1, updated_by=$2::uuid WHERE role_id=$3::uuid`, *body.RoleName, callerID, roleID)
	}
	if body.Description != nil {
		db.Pool().Exec(ctx, `UPDATE roles SET description=$1, updated_by=$2::uuid WHERE role_id=$3::uuid`, *body.Description, callerID, roleID)
	}
	if body.IsActive != nil {
		db.Pool().Exec(ctx, `UPDATE roles SET is_active=$1, updated_by=$2::uuid WHERE role_id=$3::uuid`, *body.IsActive, callerID, roleID)
	}
	r, err := scanRole(db.Pool().QueryRow(ctx, selectRole+` WHERE role_id=$1::uuid`, roleID))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Role not found"})
		return
	}
	c.JSON(http.StatusOK, r)
}

// DeleteRole DELETE /api/v1/rbac/roles/:role_id
func DeleteRole(c *gin.Context) {
	roleID := c.Param("role_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	// Prevent deleting system roles
	var isSystem bool
	db.Pool().QueryRow(ctx, `SELECT is_system FROM roles WHERE role_id=$1::uuid`, roleID).Scan(&isSystem)
	if isSystem {
		c.JSON(http.StatusForbidden, gin.H{"detail": "Cannot delete system role"})
		return
	}
	tag, err := db.Pool().Exec(ctx, `DELETE FROM roles WHERE role_id=$1::uuid`, roleID)
	if err != nil || tag.RowsAffected() == 0 {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Role not found"})
		return
	}
	c.Status(http.StatusNoContent)
}

// ── Permissions ────────────────────────────────────────────────────────────

type permRow struct {
	PermissionID   string    `json:"permission_id"`
	PermissionName string    `json:"permission_name"`
	PermissionCode string    `json:"permission_code"`
	ResourceType   string    `json:"resource_type"`
	ResourcePath   *string   `json:"resource_path"`
	HTTPMethod     *string   `json:"http_method"`
	Description    *string   `json:"description"`
	ParentID       *string   `json:"parent_id"`
	SortOrder      int       `json:"sort_order"`
	IsActive       bool      `json:"is_active"`
	CreatedAt      time.Time `json:"created_at"`
}

func scanPerm(row interface{ Scan(...any) error }) (*permRow, error) {
	p := &permRow{}
	return p, row.Scan(&p.PermissionID, &p.PermissionName, &p.PermissionCode,
		&p.ResourceType, &p.ResourcePath, &p.HTTPMethod, &p.Description,
		&p.ParentID, &p.SortOrder, &p.IsActive, &p.CreatedAt)
}

const selectPerm = `SELECT permission_id::text, permission_name, permission_code,
	resource_type, resource_path, http_method, description,
	parent_id::text, COALESCE(sort_order,0), is_active, created_at FROM permissions`

// ListPermissions GET /api/v1/rbac/permissions
func ListPermissions(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := db.Pool().Query(ctx, selectPerm+` ORDER BY sort_order, created_at`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var perms []*permRow
	for rows.Next() {
		p, err := scanPerm(rows)
		if err == nil {
			perms = append(perms, p)
		}
	}
	if perms == nil {
		perms = []*permRow{}
	}
	c.JSON(http.StatusOK, perms)
}

// ── Role-Permission assignments ────────────────────────────────────────────

// GetRolePermissions GET /api/v1/rbac/roles/:role_id/permissions
func GetRolePermissions(c *gin.Context) {
	roleID := c.Param("role_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := db.Pool().Query(ctx,
		`SELECT p.permission_id::text, p.permission_name, p.permission_code,
		 p.resource_type, p.resource_path, p.http_method, p.description,
		 p.parent_id::text, COALESCE(p.sort_order,0), p.is_active, p.created_at
		 FROM permissions p
		 JOIN role_permissions rp ON rp.permission_id = p.permission_id
		 WHERE rp.role_id=$1::uuid ORDER BY p.sort_order`, roleID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var perms []*permRow
	for rows.Next() {
		p, err := scanPerm(rows)
		if err == nil {
			perms = append(perms, p)
		}
	}
	if perms == nil {
		perms = []*permRow{}
	}
	c.JSON(http.StatusOK, perms)
}

// AssignPermission POST /api/v1/rbac/roles/:role_id/permissions
func AssignPermission(c *gin.Context) {
	roleID := c.Param("role_id")
	callerID := c.GetString("user_id")
	var body struct {
		PermissionID string `json:"permission_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err := db.Pool().Exec(ctx,
		`INSERT INTO role_permissions (role_id, permission_id, granted_by)
		 VALUES ($1::uuid, $2::uuid, $3::uuid) ON CONFLICT DO NOTHING`,
		roleID, body.PermissionID, callerID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"message": "Permission assigned"})
}

// RevokePermission DELETE /api/v1/rbac/roles/:role_id/permissions/:permission_id
func RevokePermission(c *gin.Context) {
	roleID := c.Param("role_id")
	permID := c.Param("permission_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	db.Pool().Exec(ctx,
		`DELETE FROM role_permissions WHERE role_id=$1::uuid AND permission_id=$2::uuid`,
		roleID, permID)
	c.Status(http.StatusNoContent)
}

// ── User-Role assignments ──────────────────────────────────────────────────

// GetUserRoles GET /api/v1/rbac/users/:user_id/roles
func GetUserRoles(c *gin.Context) {
	targetUserID := c.Param("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := db.Pool().Query(ctx,
		`SELECT r.role_id::text, r.role_name, r.role_code, r.description,
		 r.is_active, r.is_system, r.created_at, r.updated_at
		 FROM roles r JOIN user_roles ur ON ur.role_id = r.role_id
		 WHERE ur.user_id=$1::uuid`, targetUserID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var roles []*roleRow
	for rows.Next() {
		r, err := scanRole(rows)
		if err == nil {
			roles = append(roles, r)
		}
	}
	if roles == nil {
		roles = []*roleRow{}
	}
	c.JSON(http.StatusOK, roles)
}

// AssignUserRole POST /api/v1/rbac/users/:user_id/roles
func AssignUserRole(c *gin.Context) {
	targetUserID := c.Param("user_id")
	callerID := c.GetString("user_id")
	var body struct {
		RoleID string `json:"role_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err := db.Pool().Exec(ctx,
		`INSERT INTO user_roles (user_id, role_id, assigned_by)
		 VALUES ($1::uuid, $2::uuid, $3::uuid) ON CONFLICT DO NOTHING`,
		targetUserID, body.RoleID, callerID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"message": "Role assigned"})
}

// RevokeUserRole DELETE /api/v1/rbac/users/:user_id/roles/:role_id
func RevokeUserRole(c *gin.Context) {
	targetUserID := c.Param("user_id")
	roleID := c.Param("role_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	db.Pool().Exec(ctx,
		`DELETE FROM user_roles WHERE user_id=$1::uuid AND role_id=$2::uuid`,
		targetUserID, roleID)
	c.Status(http.StatusNoContent)
}
