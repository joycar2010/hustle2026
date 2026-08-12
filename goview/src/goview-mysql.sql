/*
 Navicat Premium Data Transfer

 Source Server         : localhost
 Source Server Type    : MySQL
 Source Server Version : 50740
 Source Host           : localhost:3306
 Source Schema         : test

 Target Server Type    : MySQL
 Target Server Version : 50740
 File Encoding         : 65001

 Date: 24/07/2024 13:46:09
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for t_goview_project
-- ----------------------------
DROP TABLE IF EXISTS `t_goview_project`;
CREATE TABLE `t_goview_project`  (
  `id` varchar(191) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL,
  `project_name` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `state` smallint(6) DEFAULT NULL,
  `create_time` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `create_user_id` bigint(20) DEFAULT NULL,
  `is_delete` smallint(6) DEFAULT NULL,
  `index_image` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `remarks` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for t_goview_project_data
-- ----------------------------
DROP TABLE IF EXISTS `t_goview_project_data`;
CREATE TABLE `t_goview_project_data`  (
  `id` varchar(191) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL,
  `project_id` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `create_time` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `create_user_id` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `content` json,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for t_sys_file
-- ----------------------------
DROP TABLE IF EXISTS `t_sys_file`;
CREATE TABLE `t_sys_file`  (
  `id` varchar(191) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL,
  `file_name` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `file_size` bigint(20) DEFAULT NULL,
  `file_suffix` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `create_time` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `md5` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `virtual_key` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `relative_path` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `absolute_path` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for t_sys_user
-- ----------------------------
DROP TABLE IF EXISTS `t_sys_user`;
CREATE TABLE `t_sys_user`  (
  `id` varchar(191) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL,
  `username` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `password` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `nickname` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  `dep_id` smallint(6) DEFAULT NULL,
  `pos_id` longtext CHARACTER SET utf8 COLLATE utf8_general_ci,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of t_sys_user
-- ----------------------------
INSERT INTO `t_sys_user` VALUES ('1', 'admin', '21232f297a57a5a743894a0e4a801fc3', 'admin', 1, '2322');

SET FOREIGN_KEY_CHECKS = 1;
