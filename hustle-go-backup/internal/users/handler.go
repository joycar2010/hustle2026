package users

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
	"hustle-go/internal/db"
)

type userRow struct {
	UserID        string    `json:"user_id"`
	Username      string    `json:"username"`
	Email         string    `json:"email"`
	Role          string    `json:"role"`
	FeishuOpenID  *string   `json:"feishu_open_id"`
	FeishuMobile  *string   `json:"feishu_mobile"`
	FeishuUnionID *string   `json:"feishu_union_id"`
	IsActive      bool      `json:"is_active"`
	CreateTime    time.Time `json:"create_time"`
	UpdateTime    time.Time `json:"update_time"`
	RbacRoles     []gin.H   `json:"rbac_roles"`
}

func scanUser(row interface{ Scan(...any) error }) (*userRow, error) {
	u := &userRow{RbacRoles: []gin.H{}}
	return u, row.Scan(
		&u.UserID, &u.Username, &u.Email, &u.Role,
		&u.FeishuOpenID, &u.FeishuMobile, &u.FeishuUnionID,
		&u.IsActive, &u.CreateTime, &u.UpdateTime,
	)
}

const selectUser = `SELECT user_id::text, username, COALESCE(email,''), role,
	feishu_open_id, feishu_mobile, feishu_union_id,
	is_active, create_time, update_time FROM users`

func GetMe(c *gin.Context) {
	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	u, err := scanUser(db.Pool().QueryRow(ctx, selectUser+` WHERE user_id=$1::uuid`, userID))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "用户不存在"})
		return
	}
	c.JSON(http.StatusOK, u)
}

func UpdateMe(c *gin.Context) {
	userID := c.GetString("user_id")
	var body struct {
		Email         *string `json:"email"`
		Password      *string `json:"password"`
		FeishuOpenID  *string `json:"feishu_open_id"`
		FeishuMobile  *string `json:"feishu_mobile"`
		FeishuUnionID *string `json:"feishu_union_id"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if body.Password != nil {
		hash, _ := bcrypt.GenerateFromPassword([]byte(*body.Password), bcrypt.DefaultCost)
		db.Pool().Exec(ctx, `UPDATE users SET password_hash=$1, update_time=NOW() WHERE user_id=$2::uuid`, string(hash), userID)
	}
	if body.Email != nil {
		db.Pool().Exec(ctx, `UPDATE users SET email=NULLIF($1,''), update_time=NOW() WHERE user_id=$2::uuid`, *body.Email, userID)
	}
	if body.FeishuOpenID != nil {
		db.Pool().Exec(ctx, `UPDATE users SET feishu_open_id=NULLIF($1,''), update_time=NOW() WHERE user_id=$2::uuid`, *body.FeishuOpenID, userID)
	}
	if body.FeishuMobile != nil {
		db.Pool().Exec(ctx, `UPDATE users SET feishu_mobile=NULLIF($1,''), update_time=NOW() WHERE user_id=$2::uuid`, *body.FeishuMobile, userID)
	}
	if body.FeishuUnionID != nil {
		db.Pool().Exec(ctx, `UPDATE users SET feishu_union_id=NULLIF($1,''), update_time=NOW() WHERE user_id=$2::uuid`, *body.FeishuUnionID, userID)
	}
	u, err := scanUser(db.Pool().QueryRow(ctx, selectUser+` WHERE user_id=$1::uuid`, userID))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "用户不存在"})
		return
	}
	c.JSON(http.StatusOK, u)
}

func ChangePassword(c *gin.Context) {
	userID := c.GetString("user_id")
	var body struct {
		CurrentPassword string `json:"current_password" binding:"required"`
		NewPassword     string `json:"new_password" binding:"required,min=8"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var hash string
	if err := db.Pool().QueryRow(ctx, `SELECT password_hash FROM users WHERE user_id=$1::uuid`, userID).Scan(&hash); err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "用户不存在"})
		return
	}
	if bcrypt.CompareHashAndPassword([]byte(hash), []byte(body.CurrentPassword)) != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "当前密码不正确"})
		return
	}
	newHash, _ := bcrypt.GenerateFromPassword([]byte(body.NewPassword), bcrypt.DefaultCost)
	db.Pool().Exec(ctx, `UPDATE users SET password_hash=$1, update_time=NOW() WHERE user_id=$2::uuid`, string(newHash), userID)
	c.JSON(http.StatusOK, gin.H{"message": "密码修改成功"})
}

func ListUsers(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	rows, err := db.Pool().Query(ctx, selectUser+` ORDER BY create_time DESC`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var users []gin.H
	for rows.Next() {
		u, err := scanUser(rows)
		if err != nil {
			continue
		}
		rrows, _ := db.Pool().Query(ctx,
			`SELECT r.role_id::text, r.role_name, r.role_code FROM roles r
			 JOIN user_roles ur ON ur.role_id = r.role_id WHERE ur.user_id=$1::uuid`, u.UserID)
		if rrows != nil {
			for rrows.Next() {
				var rid, rname, rcode string
				rrows.Scan(&rid, &rname, &rcode)
				u.RbacRoles = append(u.RbacRoles, gin.H{"role_id": rid, "role_name": rname, "role_code": rcode})
			}
			rrows.Close()
		}
		users = append(users, gin.H{
			"user_id": u.UserID, "username": u.Username, "email": u.Email,
			"role": u.Role, "feishu_open_id": u.FeishuOpenID, "feishu_mobile": u.FeishuMobile,
			"feishu_union_id": u.FeishuUnionID, "rbac_roles": u.RbacRoles,
			"is_active": u.IsActive, "create_time": u.CreateTime, "update_time": u.UpdateTime,
		})
	}
	if users == nil {
		users = []gin.H{}
	}
	c.JSON(http.StatusOK, gin.H{"users": users})
}

func CreateUser(c *gin.Context) {
	var body struct {
		Username      string  `json:"username" binding:"required,min=3,max=50"`
		Password      string  `json:"password" binding:"required,min=8"`
		Email         *string `json:"email"`
		Role          *string `json:"role"`
		IsActive      *bool   `json:"is_active"`
		FeishuOpenID  *string `json:"feishu_open_id"`
		FeishuMobile  *string `json:"feishu_mobile"`
		FeishuUnionID *string `json:"feishu_union_id"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var exists bool
	db.Pool().QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM users WHERE username=$1)`, body.Username).Scan(&exists)
	if exists {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "用户名已存在"})
		return
	}
	hash, _ := bcrypt.GenerateFromPassword([]byte(body.Password), bcrypt.DefaultCost)
	role := "交易员"
	if body.Role != nil && *body.Role != "" {
		role = *body.Role
	}
	isActive := true
	if body.IsActive != nil {
		isActive = *body.IsActive
	}
	u, err := scanUser(db.Pool().QueryRow(ctx,
		`INSERT INTO users (username, password_hash, email, role, is_active, feishu_open_id, feishu_mobile, feishu_union_id)
		 VALUES ($1,$2,NULLIF($3,''),$4,$5,NULLIF($6,''),NULLIF($7,''),NULLIF($8,''))
		 RETURNING user_id::text, username, COALESCE(email,''), role,
		   feishu_open_id, feishu_mobile, feishu_union_id, is_active, create_time, update_time`,
		body.Username, string(hash), strOrEmpty(body.Email), role, isActive,
		strOrEmpty(body.FeishuOpenID), strOrEmpty(body.FeishuMobile), strOrEmpty(body.FeishuUnionID),
	))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, u)
}

func UpdateUser(c *gin.Context) {
	targetID := c.Param("user_id")
	var body struct {
		Email         *string `json:"email"`
		Password      *string `json:"password"`
		Role          *string `json:"role"`
		IsActive      *bool   `json:"is_active"`
		FeishuOpenID  *string `json:"feishu_open_id"`
		FeishuMobile  *string `json:"feishu_mobile"`
		FeishuUnionID *string `json:"feishu_union_id"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if body.Password != nil {
		hash, _ := bcrypt.GenerateFromPassword([]byte(*body.Password), bcrypt.DefaultCost)
		db.Pool().Exec(ctx, `UPDATE users SET password_hash=$1, update_time=NOW() WHERE user_id=$2::uuid`, string(hash), targetID)
	}
	if body.Email != nil {
		db.Pool().Exec(ctx, `UPDATE users SET email=NULLIF($1,''), update_time=NOW() WHERE user_id=$2::uuid`, *body.Email, targetID)
	}
	if body.Role != nil {
		db.Pool().Exec(ctx, `UPDATE users SET role=$1, update_time=NOW() WHERE user_id=$2::uuid`, *body.Role, targetID)
	}
	if body.IsActive != nil {
		db.Pool().Exec(ctx, `UPDATE users SET is_active=$1, update_time=NOW() WHERE user_id=$2::uuid`, *body.IsActive, targetID)
	}
	if body.FeishuOpenID != nil {
		db.Pool().Exec(ctx, `UPDATE users SET feishu_open_id=NULLIF($1,''), update_time=NOW() WHERE user_id=$2::uuid`, *body.FeishuOpenID, targetID)
	}
	if body.FeishuMobile != nil {
		db.Pool().Exec(ctx, `UPDATE users SET feishu_mobile=NULLIF($1,''), update_time=NOW() WHERE user_id=$2::uuid`, *body.FeishuMobile, targetID)
	}
	if body.FeishuUnionID != nil {
		db.Pool().Exec(ctx, `UPDATE users SET feishu_union_id=NULLIF($1,''), update_time=NOW() WHERE user_id=$2::uuid`, *body.FeishuUnionID, targetID)
	}
	u, err := scanUser(db.Pool().QueryRow(ctx, selectUser+` WHERE user_id=$1::uuid`, targetID))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "用户不存在"})
		return
	}
	c.JSON(http.StatusOK, u)
}

func DeleteUser(c *gin.Context) {
	targetID := c.Param("user_id")
	callerID := c.GetString("user_id")
	if targetID == callerID {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "不能删除自己的账户"})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var role string
	db.Pool().QueryRow(ctx, `SELECT role FROM users WHERE user_id=$1::uuid`, callerID).Scan(&role)
	adminRoles := map[string]bool{"系统管理员": true, "管理员": true, "admin": true, "super_admin": true}
	if !adminRoles[role] {
		c.JSON(http.StatusForbidden, gin.H{"detail": "只有管理员可以删除用户"})
		return
	}
	// Complex cascaded delete delegated to Python
	c.JSON(http.StatusNotImplemented, gin.H{"detail": "请使用 Python API 删除用户"})
}

func strOrEmpty(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
