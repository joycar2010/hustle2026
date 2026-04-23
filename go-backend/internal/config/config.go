package config

import (
	"os"
	"github.com/spf13/viper"
)

type Config struct {
	Server   ServerConfig
	Redis    RedisConfig
	Postgres PostgresConfig
	Binance  BinanceConfig
}

type ServerConfig struct {
	Port string
	Mode string // gin mode: debug/release
}

type RedisConfig struct {
	URL string
}

type PostgresConfig struct {
	DSN string
}

type BinanceConfig struct {
	WSURL string // WebSocket URL for market data
}

func Load() *Config {
	viper.SetDefault("SERVER_PORT", "8080")
	viper.SetDefault("SERVER_MODE", "release")
	viper.SetDefault("REDIS_URL", "redis://127.0.0.1:6379/0")
	viper.SetDefault("BINANCE_WS_URL", "wss://fstream.binance.com/ws/xauusdt@bookTicker")
	viper.AutomaticEnv()

	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		dsn = "postgres://postgres:postgres@127.0.0.1:5432/hustle2026?sslmode=disable"
	}

	return &Config{
		Server: ServerConfig{
			Port: viper.GetString("SERVER_PORT"),
			Mode: viper.GetString("SERVER_MODE"),
		},
		Redis: RedisConfig{
			URL: viper.GetString("REDIS_URL"),
		},
		Postgres: PostgresConfig{
			DSN: dsn,
		},
		Binance: BinanceConfig{
			WSURL: viper.GetString("BINANCE_WS_URL"),
		},
	}
}
