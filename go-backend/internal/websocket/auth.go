package ws

import (
	"errors"
	"os"

	"github.com/golang-jwt/jwt/v5"
)

func getJWTSecret() []byte {
	s := os.Getenv("SECRET_KEY")
	if s == "" {
		s = "your-secret-key-change-this-in-production"
	}
	return []byte(s)
}

func ValidateToken(tokenStr string) (string, error) {
	if tokenStr == "" {
		return "", errors.New("empty token")
	}
	token, err := jwt.Parse(tokenStr, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return getJWTSecret(), nil
	})
	if err != nil || !token.Valid {
		return "", errors.New("invalid token")
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return "", errors.New("invalid claims")
	}
	sub, _ := claims["sub"].(string)
	if sub == "" {
		return "", errors.New("missing sub")
	}
	return sub, nil
}

// ParseTokenExp validates the token and returns (userID, expUnix, error).
func ParseTokenExp(tokenStr string) (string, int64, error) {
	if tokenStr == "" {
		return "", 0, errors.New("empty token")
	}
	token, err := jwt.Parse(tokenStr, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return getJWTSecret(), nil
	})
	if err != nil || !token.Valid {
		return "", 0, errors.New("invalid token")
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return "", 0, errors.New("invalid claims")
	}
	sub, _ := claims["sub"].(string)
	if sub == "" {
		return "", 0, errors.New("missing sub")
	}
	exp, err := claims.GetExpirationTime()
	if err != nil || exp == nil {
		return "", 0, errors.New("missing exp")
	}
	return sub, exp.Unix(), nil
}
