package db

import (
	"context"
	"log"
	"sync"

	"github.com/jackc/pgx/v5/pgxpool"
)

var (
	pool *pgxpool.Pool
	once sync.Once
)

func Init(dsn string) {
	once.Do(func() {
		var err error
		pool, err = pgxpool.New(context.Background(), dsn)
		if err != nil {
			log.Fatalf("[DB] Failed to connect: %v", err)
		}
		if err = pool.Ping(context.Background()); err != nil {
			log.Fatalf("[DB] Ping failed: %v", err)
		}
		log.Println("[DB] PostgreSQL connected")
	})
}

func Pool() *pgxpool.Pool {
	return pool
}
