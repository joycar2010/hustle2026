package main

import (
	"fmt"

	"github.com/gin-gonic/gin"
	"github.com/glebarez/sqlite"
	"github.com/spf13/viper"
	"gorm.io/driver/mysql"
	"gorm.io/gorm"
)

func Init() {
	// 初始化Viper
	viper.SetConfigFile("config.ini")
	viper.ReadInConfig()
}

func GetConfig() map[string]string {
	config := make(map[string]string)
	// 读取配置项
	config["db_mode"] = viper.GetString("server.db_mode")
	config["db_host"] = viper.GetString("mysql.host")
	config["db_port"] = viper.GetString("mysql.port")
	config["db_user"] = viper.GetString("mysql.user")
	config["db_password"] = viper.GetString("mysql.password")
	config["db_database"] = viper.GetString("mysql.database")
	config["db_charset"] = viper.GetString("mysql.charset")

	config["db_path"] = viper.GetString("sqlite.sqlite_path")

	config["port"] = viper.GetString("server.port")
	config["mode"] = viper.GetString("server.mode")
	// 添加其他配置项...

	return config
}

func initDB(config map[string]string) *gorm.DB {
	var err error
	fmt.Println(config["db_mode"])
	if config["db_mode"] == "mysql" {
		dsn := config["db_user"] + ":" + config["db_password"] + "@tcp(" + config["db_host"] + ":" + config["db_port"] + ")/" + config["db_database"] + "?charset=" + config["db_charset"] + "&parseTime=True&loc=Local"
		fmt.Println(dsn)
		db, err = gorm.Open(mysql.Open(dsn), &gorm.Config{})
	}
	if config["db_mode"] == "sqlite" {
		db, err = gorm.Open(sqlite.Open(config["db_path"]), &gorm.Config{})
	}

	if err != nil {
		panic("Failed to connect to database")
	}

	db.AutoMigrate(&TSysUser{}, &TSysFile{}, &TGoviewProject{}, &TGoviewProjectData{})
	return db
}

func main() {

	// 初始化Viper
	Init()
	config := GetConfig()
	// 读取配置
	initDB(config)
	// 设置Gin模式
	gin.SetMode(config["mode"])

	router := gin.Default()

	// 设置静态文件路由
	// 参数 "static" 表示 URL 的前缀，"./static" 表示静态文件所在的目录
	router.Static("/static", "./static")

	// Public routes (without authentication)
	router.GET("/", Index)

	goview := router.Group("/api/goview/sys")
	goview.POST("/login", Login)
	goview.GET("/logout", Logout)
	goview.GET("/getOssInfo", GetOssInfo)
	goview.POST("/register", Register)
	router.GET("/api/goview/project/getData", ProjectDataGet)
	goViewProject := router.Group("/api/goview/project")
	goViewProject.Use(AuthMiddleware())
	goViewProject.POST("/create", ProjectCreate)
	goViewProject.POST("/edit", ProjectEdit)
	goViewProject.DELETE("/delete", ProjectDelete)
	goViewProject.GET("/list", PorjectListGet)
	goViewProject.PUT("/publish", ProjectPublish)
	goViewProject.POST("/upload", ProjectUpload)
	// goViewProject.GET("/getData", ProjectDataGet)
	goViewProject.POST("/save/data", ProjectDataSave)

	// Authenticated routes (with JWT authentication)
	// auth := router.Group("/auth")
	// auth.Use(AuthMiddleware())
	{
		// auth.POST("/users", CreateNewUser)
		// Add other authenticated routes here
	}

	router.Run(":" + config["port"])
}
