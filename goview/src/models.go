package main

import (
	"gorm.io/gorm"
)

var db *gorm.DB

type TSysUser struct {
	Id       string `json:"id" gorm:"primaryKey"`
	Username string `json:"username"`
	Password string `json:"password"`
	Nickname string `json:"nickname"`
	DepId    int16  `json:"depId"`
	PosId    string `json:"postId"`
}

func (TSysUser) TableName() string {
	return "t_sys_user"
}

type TSysFile struct {
	Id           string `json:"id" gorm:"primaryKey"`
	FileName     string `json:"fileName"`
	FileSize     int64  `json:"fileSize"`
	FileSuffix   string `json:"fileSuffix"`
	CreateTime   string `json:"createTime"`
	Md5          string `json:"md5"`
	VirtualKey   string `json:"virtualKey"`
	RelativePath string `json:"relativePath"`
	AbsolutePath string `json:"absolutePath"`
}

func (TSysFile) TableName() string {
	return "t_sys_file"
}

type TGoviewProject struct {
	Id           string `json:"id" gorm:"primaryKey"`
	ProjectName  string `json:"projectName"`
	State        int16  `json:"state"`
	CreateTime   string `json:"createTime"`
	CreateUserId int64  `json:"createUserId"`
	IsDelete     int16  `json:"isDelete"`
	IndexImage   string `json:"indexImage"`
	Remarks      string `json:"remarks"`
}

func (TGoviewProject) TableName() string {
	return "t_goview_project"
}

type TGoviewProjectData struct {
	Id           string `json:"id" gorm:"primaryKey"`
	ProjectId    string `json:"projectId"`
	CreateTime   string `json:"createTime"`
	CreateUserId string `json:"createUserId"`
	Content      string `json:"content" gorm:"type:json"`
}

func (TGoviewProjectData) TableName() string {
	return "t_goview_project_data"
}
