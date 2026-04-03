package db

import (
	"log"
	"sync"

	"github.com/redis/go-redis/v9"
)

var (
	rdb    *redis.Client
	rdOnce sync.Once
)

func InitRedis(url string) {
	rdOnce.Do(func() {
		opt, err := redis.ParseURL(url)
		if err != nil {
			log.Fatalf("[Redis] Invalid URL: %v", err)
		}
		rdb = redis.NewClient(opt)
		log.Println("[Redis] client initialized")
	})
}

func Redis() *redis.Client {
	return rdb
}
