package main

import (
	"net/http"

	"crypto/md5"
	"encoding/hex"

	"github.com/google/uuid"

	"github.com/dgrijalva/jwt-go"
	"github.com/gin-gonic/gin"
)

// JSONResponse 通用的 JSON 响应结构体
type JSONResponse struct {
	Code int         `json:"code"`
	Msg  string      `json:"msg"`
	Data interface{} `json:"data,omitempty"`
}

func GenerateID() string {
	return uuid.New().String()
}

func EncryptPassword(password string) string {
	hasher := md5.New()
	hasher.Write([]byte(password))
	return hex.EncodeToString(hasher.Sum(nil))
}

// JSONSuccess 返回成功的 JSON 响应
func JSONSuccess(c *gin.Context, data interface{}) {
	response := JSONResponse{
		Code: http.StatusOK,
		Msg:  "Success",
		Data: data,
	}
	c.JSON(http.StatusOK, response)
}

// JSONError 返回错误的 JSON 响应
func JSONError(c *gin.Context, status int, message string) {
	response := JSONResponse{
		Code: status,
		Msg:  message,
		Data: nil,
	}
	c.JSON(status, response)
}
func AuthMiddleware() gin.HandlerFunc {
	issuer := "goview"
	return func(c *gin.Context) {
		tokenString := c.GetHeader("Authorization")
		if tokenString == "" {
			JSONError(c, http.StatusUnauthorized, "Authorization header is missing")
			c.Abort()
			return
		}

		token, err := jwt.Parse(tokenString, func(token *jwt.Token) (interface{}, error) {
			return []byte("secret"), nil // Change this with a secure key in production
		})

		if err != nil || !token.Valid {
			JSONError(c, http.StatusUnauthorized, err.Error())
			c.Abort()
			return
		}

		claims, ok := token.Claims.(jwt.MapClaims)
		if !ok || !claims.VerifyIssuer(issuer, true) {
			JSONError(c, http.StatusUnauthorized, "Invalid token")
			c.Abort()
			return
		}

		c.Set("claims", claims)
		c.Next()
	}
}
