package main

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/dgrijalva/jwt-go"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

func Index(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"message": "Hello World"})
}

func Login(c *gin.Context) {
	issuer := "goview"
	var user TSysUser

	if err := c.ShouldBindJSON(&user); err != nil {
		JSONError(c, http.StatusBadRequest, "Invalid token")
		return
	}

	// if user.Username != "admin" || user.Password != "admin" {
	// 	c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid username or password"})
	// 	return
	// }
	//从数据库TSysUser查询出对应的用户，用户不存在就返回登录失败

	if err := db.Where("username = ? and password = ?", user.Username, EncryptPassword(user.Password)).First(&user).Error; err != nil {
		JSONError(c, 500, "用户或密码错误")
		return
	} else {
		fmt.Println(err)
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"iss":      issuer,
		"username": user.Username,
		"exp":      time.Now().Add(time.Hour * 24).Unix(),
	})
	tokenString, err := token.SignedString([]byte("secret"))
	if err != nil {
		JSONError(c, http.StatusInternalServerError, "Invalid token")
		return
	}
	m := make(map[string]any)
	m["tokenValue"] = tokenString
	m["tokenName"] = "Authorization"
	m["isLogin"] = true
	m["loginId"] = user.Id
	m["loginType"] = "login"
	m["tokenTimeout"] = time.Now().Add(time.Hour * 24).Unix()
	m["sessionTimeout"] = time.Now().Add(time.Hour * 24).Unix()
	m["tokenSessionTimeout"] = time.Now().Add(time.Hour * 24).Unix()
	m["tokenActivityTimeout"] = -1
	m["loginDevice"] = "default-device"
	m["tag"] = nil
	JSONSuccess(c, gin.H{"userinfo": user, "token": m})
}

func GetOssInfo(c *gin.Context) {
	var protocol string
	//获取服务器的当前host信息以及对应port
	host := c.Request.Host
	//获取服务器的当前是http还是https
	if c.Request.TLS != nil {
		protocol = "https"
	} else {
		protocol = "http"
	}
	JSONSuccess(c, gin.H{
		"BucketName": "getuserphoto",
		"bucketURL":  protocol + "://" + host + "/static/uploads/goviews/",
	})
}

func Register(c *gin.Context) {
	var user TSysUser
	if err := c.ShouldBindJSON(&user); err != nil {
		JSONError(c, http.StatusBadRequest, "Invalid token")
		return
	}
	user.Id = GenerateID()
	if err := db.Create(&user).Error; err != nil {
		JSONError(c, 500, err.Error())
		return
	} else {
		JSONSuccess(c, user)
	}
}

// 吊销token，并退出登录
func Logout(c *gin.Context) {
	JSONSuccess(c, gin.H{})
}

func ProjectCreate(c *gin.Context) {
	var project TGoviewProject
	if err := c.ShouldBindJSON(&project); err != nil {
		JSONError(c, http.StatusBadRequest, "Invalid token")
		return
	}
	project.Id = GenerateID()
	err := db.Create(&project).Error
	if err != nil {
		JSONError(c, 500, err.Error())
		return
	} else {
		JSONSuccess(c, project)
	}
}

func ProjectEdit(c *gin.Context) {
	var project TGoviewProject
	if err := c.ShouldBindJSON(&project); err != nil {
		JSONError(c, http.StatusBadRequest, "Invalid token")
		return
	}

	fmt.Println(project.Id, project.IndexImage)
	// db.Where("id = ?", project.Id).First(&project)
	// 根据 `struct` 更新属性，只会更新非零值的字段
	db.Model(&project).Where("id = ?", project.Id).Updates(TGoviewProject{Id: project.Id, IndexImage: project.IndexImage})
	if err := db.Save(&project).Error; err != nil {
		JSONError(c, 500, err.Error())
		return
	} else {
		JSONSuccess(c, project)
	}
}

func ProjectDelete(c *gin.Context) {
	var project TGoviewProject
	//获取get参数
	ids := c.Query("ids")
	fmt.Println("id", ids)
	if err := db.Model(&TGoviewProject{}).Where("id = ?", ids).Update("is_delete", 1).Error; err != nil {
		JSONError(c, 500, err.Error())
		return
	} else {
		JSONSuccess(c, project)
	}
}

func PorjectListGet(c *gin.Context) {
	// 从查询参数中获取页码和每页数量
	page, _ := strconv.Atoi(c.Query("page"))
	pageSize, _ := strconv.Atoi(c.Query("pageSize"))

	// 设置默认值，避免未提供查询参数时的错误
	if page <= 0 {
		page = 1
	}
	if pageSize <= 0 {
		pageSize = 10
	}

	// 计算偏移量
	offset := (page - 1) * pageSize

	// 查询数据库，根据偏移量和每页数量获取用户列表
	var project []TGoviewProject
	db.Offset(offset).Where("is_delete = ?", 0).Limit(pageSize).Find(&project)

	JSONSuccess(c, project)
}

func ProjectPublish(c *gin.Context) {
	// {
	// 	"id": "686921059995357184", //项目主键
	// 	"state": "-1" //项目状态[-1未发布,1发布]
	// 	}
	//gin获取post参数
	var project TGoviewProject
	if err := c.ShouldBindJSON(&project); err != nil {
		JSONError(c, http.StatusBadRequest, "Invalid Data")
		return
	}
	if err := db.Model(&TGoviewProject{}).Where("id = ?", project.Id).Update("state", project.State).Error; err != nil {
		JSONError(c, 500, err.Error())
		return
	} else {
		JSONSuccess(c, project)
	}
}

func ProjectDataGet(c *gin.Context) {
	var project TGoviewProject
	// 从查询参数中获取页码和每页数量
	projectId := c.DefaultQuery("projectId", "")
	var projectData TGoviewProjectData
	err := db.Where("project_id = ?", projectId).First(&projectData).Error
	db.Model(&TGoviewProject{}).Where("id = ?", projectId).First(&project)
	if err != nil {
		if err.Error() == "record not found" {
			JSONSuccess(c, nil)
			return
		} else {
			JSONError(c, 500, err.Error())
			return
		}

	} else {
		JSONSuccess(c, gin.H{
			"content":      projectData.Content,
			"createTime":   project.CreateTime,
			"createUserId": project.CreateUserId,
			"indexImage":   project.IndexImage,
			"id":           project.Id,
			"isDelete":     project.IsDelete,
			"state":        project.State,
			"remarks":      project.Remarks,
		})
	}
}

func ProjectDataSave(c *gin.Context) {
	var projectData TGoviewProjectData
	projectId := c.DefaultPostForm("projectId", "")
	content := c.DefaultPostForm("content", "")
	if err := db.Where("project_id = ?", projectId).First(&projectData).Error; err != nil {
		err := db.Save(&TGoviewProjectData{Id: GenerateID(),
			ProjectId:  projectId,
			Content:    content,
			CreateTime: time.Now().Format("2006-01-02 15:04:05")}).Error
		if err != nil {
			JSONError(c, 500, err.Error())
			return
		}
	} else {
		projectData.Content = content
		if err := db.Save(&projectData).Error; err != nil {
			JSONError(c, 500, err.Error())
			return
		}
	}
	JSONSuccess(c, projectData)
}

func ProjectUpload(c *gin.Context) {
	file, header, err := c.Request.FormFile("object")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "File not provided"})
		return
	}
	defer file.Close()

	// 生成文件名和扩展名
	fileName := header.Filename
	extension := filepath.Ext(fileName)
	//获取文件大小
	fileSize := header.Size

	// 保存文件到指定目录
	savePath := "./static/uploads/goviews"
	if err := os.MkdirAll(savePath, os.ModePerm); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create upload directory"})
		return
	}
	// 获取文件的真实物理路径
	realPath, err := filepath.Abs(savePath)

	filePath := filepath.Join(savePath, fileName)
	out, err := os.Create(filePath)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create file"})
		return
	}
	defer out.Close()

	_, err = io.Copy(out, file)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to save file"})
		return
	}

	var t_sys_file = TSysFile{
		FileName:     fileName,
		FileSuffix:   extension,
		FileSize:     fileSize,
		CreateTime:   time.Now().Format("2006-01-02 15:04:05"),
		VirtualKey:   "oss",
		RelativePath: savePath,
		AbsolutePath: realPath,
	}
	// 将文件信息保存到数据库
	err = db.First(&t_sys_file).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			t_sys_file.Id = GenerateID()
			db.Create(&t_sys_file)
		}
	} else {
		// db.Model(&t_sys_file).Where("id = ?", t_sys_file.Id).Update(&t_sys_file)
		db.Save(&t_sys_file)
	}
	JSONSuccess(c, gin.H{
		"fileName":     t_sys_file.FileName,
		"fileSize":     t_sys_file.FileSize,
		"fileSuffix":   t_sys_file.FileSuffix,
		"virtualKey":   t_sys_file.VirtualKey,
		"relativePath": t_sys_file.RelativePath,
		"absolutePath": t_sys_file.AbsolutePath,
		"id":           t_sys_file.Id,
		"createTime":   t_sys_file.CreateTime,
	})

}
