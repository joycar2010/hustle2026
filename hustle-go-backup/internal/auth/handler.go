package auth

import (
	"context"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
	"hustle-go/internal/db"
)

type loginReq struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

type registerReq struct {
	Username string `json:"username" binding:"required,min=3,max=50"`
	Password string `json:"password" binding:"required,min=8,max=128"`
	Email    string `json:"email"`
	Role     string `json:"role"`
}

type verifyPwdReq struct {
	Password string `json:"password" binding:"required"`
}

func jwtSecret() []byte {
	s := os.Getenv("SECRET_KEY")
	if s == "" {
		s = "your-secret-key-change-this-in-production"
	}
	return []byte(s)
}

func makeToken(userID string) (string, error) {
	expireMinutes := 480
	claims := jwt.MapClaims{
		"sub": userID,
		"exp": time.Now().Add(time.Duration(expireMinutes) * time.Minute).Unix(),
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(jwtSecret())
}

// Login handles POST /api/v1/auth/login
func Login(c *gin.Context) {
	var req loginReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	var userID, passwordHash, username string
	var isActive bool
	err := db.Pool().QueryRow(ctx,
		`SELECT user_id::text, password_hash, username, is_active FROM users WHERE username=$1`,
		req.Username,
	).Scan(&userID, &passwordHash, &username, &isActive)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"detail": "Incorrect username or password"})
		return
	}

	if !isActive {
		c.JSON(http.StatusForbidden, gin.H{"detail": "User account is inactive"})
		return
	}

	if err := bcrypt.CompareHashAndPassword([]byte(passwordHash), []byte(req.Password)); err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"detail": "Incorrect username or password"})
		return
	}

	token, err := makeToken(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "Token generation failed"})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"access_token": token,
		"token_type":   "bearer",
		"user_id":      userID,
		"username":     username,
	})
}

// Register handles POST /api/v1/auth/register
func Register(c *gin.Context) {
	var req registerReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Check username uniqueness
	var exists bool
	db.Pool().QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM users WHERE username=$1)`, req.Username).Scan(&exists)
	if exists {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "Username already registered"})
		return
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "Password hashing failed"})
		return
	}

	role := req.Role
	if role == "" {
		role = "交易员"
	}

	var userID, username, email, userRole string
	var isActive bool
	var createTime, updateTime time.Time
	err = db.Pool().QueryRow(ctx,
		`INSERT INTO users (username, password_hash, email, role, is_active)
		 VALUES ($1, $2, NULLIF($3,), $4, true)
		 RETURNING user_id::text, username, COALESCE(email,), role, is_active, create_time, update_time`,
		req.Username, string(hash), req.Email, role,
	).Scan(&userID, &username, &email, &userRole, &isActive, &createTime, &updateTime)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"user_id":     userID,
		"username":    username,
		"email":       email,
		"role":        userRole,
		"is_active":   isActive,
		"create_time": createTime,
		"update_time": updateTime,
	})
}

// VerifyPassword handles POST /api/v1/auth/verify-password
func VerifyPassword(c *gin.Context) {
	var req verifyPwdReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}

	userID := c.GetString("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	var passwordHash string
	err := db.Pool().QueryRow(ctx,
		`SELECT password_hash FROM users WHERE user_id=$1::uuid`, userID,
	).Scan(&passwordHash)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "User not found"})
		return
	}

	valid := bcrypt.CompareHashAndPassword([]byte(passwordHash), []byte(req.Password)) == nil
	c.JSON(http.StatusOK, gin.H{"valid": valid})
}
