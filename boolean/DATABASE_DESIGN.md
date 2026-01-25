# 微信小程序后端数据库设计文档

## 1. 项目概述

本项目是一个微信小程序后端，用于管理空间设计公司的作品展示、分类管理、客户线索和系统设置。采用 Node.js + Express + lowdb 实现，lowdb 是一个基于 JSON 文件的轻量级数据库，适合小型应用和开发阶段使用。

## 2. 数据模型设计

### 2.1 用户表 (users)

| 字段名 | 数据类型 | 描述 | 约束 |
| --- | --- | --- | --- |
| id | Number | 用户ID，自增 | 主键，唯一 |
| username | String | 用户名 | 必填，唯一 |
| password | String | 密码 | 必填 |
| role | String | 用户角色 | 必填，默认值：admin |
| createdAt | Date | 创建时间 | 必填，默认值：当前时间 |
| updatedAt | Date | 更新时间 | 必填，默认值：当前时间 |

### 2.2 作品表 (works)

| 字段名 | 数据类型 | 描述 | 约束 |
| --- | --- | --- | --- |
| id | Number | 作品ID，自增 | 主键，唯一 |
| title | String | 作品标题 | 必填 |
| type | String | 作品类型，关联分类表的slug | 必填 |
| area | Number | 面积（平方米） | 必填 |
| location | String | 地点 | 必填 |
| coverImage | String | 封面图片URL | 必填 |
| images | Array<String> | 作品图片列表 | 必填 |
| description | String | 作品描述 | 可选 |
| views | Number | 浏览量 | 必填，默认值：0 |
| createdAt | Date | 创建时间 | 必填，默认值：当前时间 |
| updatedAt | Date | 更新时间 | 必填，默认值：当前时间 |

### 2.3 分类表 (categories)

| 字段名 | 数据类型 | 描述 | 约束 |
| --- | --- | --- | --- |
| id | Number | 分类ID，自增 | 主键，唯一 |
| name | String | 分类名称 | 必填 |
| slug | String | 分类标识，用于URL | 必填，唯一 |
| description | String | 分类描述 | 可选 |
| worksCount | Number | 该分类下的作品数量 | 必填，默认值：0 |
| createdAt | Date | 创建时间 | 必填，默认值：当前时间 |
| updatedAt | Date | 更新时间 | 必填，默认值：当前时间 |

### 2.4 线索表 (leads)

| 字段名 | 数据类型 | 描述 | 约束 |
| --- | --- | --- | --- |
| id | Number | 线索ID，自增 | 主键，唯一 |
| name | String | 客户名称 | 必填 |
| phone | String | 联系电话 | 必填 |
| email | String | 邮箱 | 可选 |
| projectType | String | 项目类型，关联分类表的slug | 必填 |
| budget | String | 预算范围 | 可选 |
| status | String | 线索状态：new, processing, completed, canceled | 必填，默认值：new |
| description | String | 需求描述 | 可选 |
| createdAt | Date | 创建时间 | 必填，默认值：当前时间 |
| updatedAt | Date | 更新时间 | 必填，默认值：当前时间 |

### 2.5 设置表 (settings)

| 字段名 | 数据类型 | 描述 | 约束 |
| --- | --- | --- | --- |
| siteName | String | 网站名称 | 必填 |
| siteLogo | String | 网站Logo | 必填 |
| contactEmail | String | 联系邮箱 | 必填 |
| contactPhone | String | 联系电话 | 必填 |
| address | String | 公司地址 | 必填 |
| socialMedia | Object | 社交媒体信息 | 必填 |
| socialMedia.wechat | String | 微信账号 | 可选 |
| socialMedia.weibo | String | 微博账号 | 可选 |
| socialMedia.instagram | String | Instagram账号 | 可选 |
| seoSettings | Object | SEO设置 | 必填 |
| seoSettings.title | String | SEO标题 | 必填 |
| seoSettings.description | String | SEO描述 | 必填 |
| seoSettings.keywords | String | SEO关键词 | 必填 |
| notificationSettings | Object | 通知设置 | 必填 |
| notificationSettings.leadNotification | Boolean | 线索通知 | 必填，默认值：true |
| notificationSettings.workNotification | Boolean | 作品通知 | 必填，默认值：true |
| notificationSettings.emailNotification | Boolean | 邮箱通知 | 必填，默认值：true |

### 2.6 关于我们表 (about)

| 字段名 | 数据类型 | 描述 | 约束 |
| --- | --- | --- | --- |
| brandInfo | Object | 品牌信息 | 必填 |
| brandInfo.name | String | 品牌名称 | 必填 |
| brandInfo.description | String | 品牌描述 | 必填 |
| brandInfo.logo | String | 品牌Logo | 必填 |
| brandInfo.slogan | String | 品牌口号 | 必填 |
| contactInfo | Object | 联系信息 | 必填 |
| contactInfo.phone | String | 联系电话 | 必填 |
| contactInfo.email | String | 联系邮箱 | 必填 |
| contactInfo.address | String | 公司地址 | 必填 |
| contactInfo.workingHours | String | 工作时间 | 必填 |
| contactInfo.map | String | 地图链接 | 必填 |

### 2.7 计数器表 (counters)

| 字段名 | 数据类型 | 描述 | 约束 |
| --- | --- | --- | --- |
| work | Number | 作品ID计数器 | 必填，默认值：1 |
| category | Number | 分类ID计数器 | 必填，默认值：1 |
| lead | Number | 线索ID计数器 | 必填，默认值：1 |

## 3. 数据关系

### 3.1 一对多关系

- **分类** 与 **作品**：一个分类可以包含多个作品，一个作品只能属于一个分类。
  - 关联字段：`works.type` 关联 `categories.slug`

- **分类** 与 **线索**：一个分类可以包含多个线索，一个线索只能属于一个分类。
  - 关联字段：`leads.projectType` 关联 `categories.slug`

### 3.2 一对一关系

- **设置**：系统只有一组设置数据。
- **关于我们**：系统只有一组关于我们数据。

## 4. 索引策略

由于 lowdb 是基于 JSON 文件的数据库，不支持传统的索引机制，但我们可以通过以下方式优化查询性能：

1. **ID 索引**：使用自增ID作为主键，便于快速查找单个记录。
2. **类型索引**：对于作品和线索，按类型进行分组，便于快速过滤。
3. **时间索引**：对于需要按时间排序的记录，确保时间字段格式一致，便于快速排序。
4. **内存缓存**：lowdb 将数据加载到内存中，查询操作非常快速。

## 5. 数据库优化建议

### 5.1 数据结构优化

1. **使用合适的数据类型**：确保每个字段使用合适的数据类型，避免不必要的类型转换。
2. **避免冗余数据**：例如，分类的作品数量可以通过计算得出，而不是存储在数据库中。
3. **合理设计嵌套结构**：对于设置和关于我们等数据，可以使用嵌套结构，便于管理和查询。

### 5.2 查询优化

1. **使用合适的查询方式**：根据查询需求选择合适的查询方式，例如使用 `find` 查找单个记录，使用 `filter` 过滤多个记录。
2. **减少数据传输**：只返回需要的数据，避免返回整个数据集。
3. **使用缓存**：对于频繁访问的数据，可以使用缓存机制，减少数据库查询次数。

### 5.3 安全优化

1. **数据验证**：对所有输入数据进行验证，确保数据的完整性和安全性。
2. **密码加密**：对用户密码进行加密存储，避免明文存储。
3. **访问控制**：实现适当的访问控制机制，确保只有授权用户才能访问敏感数据。
4. **防止SQL注入**：虽然lowdb不使用SQL，但仍需注意防止恶意输入。

## 6. 数据迁移策略

### 6.1 从模拟数据迁移

1. **导出模拟数据**：将现有的模拟数据导出为JSON格式。
2. **转换数据格式**：根据数据库设计转换数据格式。
3. **导入数据库**：将转换后的数据导入到lowdb数据库中。
4. **验证数据完整性**：验证导入后的数据完整性和一致性。

### 6.2 数据库版本管理

1. **使用版本控制**：对数据库文件进行版本控制，便于回滚和管理。
2. **记录变更日志**：记录数据库结构和数据的变更，便于追踪和管理。
3. **定期备份**：定期备份数据库文件，避免数据丢失。

## 7. 性能测试

### 7.1 测试方法

1. **负载测试**：测试系统在高负载下的性能表现。
2. **响应时间测试**：测试API端点的响应时间。
3. **并发测试**：测试系统在并发请求下的性能表现。

### 7.2 测试指标

1. **响应时间**：API端点的平均响应时间应小于100ms。
2. **吞吐量**：系统每秒能处理的请求数量。
3. **并发用户数**：系统能同时处理的用户数量。
4. **错误率**：系统在测试过程中的错误率应小于1%。

## 8. 监控和维护

### 8.1 监控

1. **日志监控**：记录系统的运行日志，便于追踪和调试。
2. **性能监控**：监控系统的性能指标，如响应时间、吞吐量等。
3. **错误监控**：监控系统的错误信息，便于及时发现和修复问题。

### 8.2 维护

1. **定期备份**：定期备份数据库文件，避免数据丢失。
2. **优化数据库**：定期优化数据库结构和数据，提高系统性能。
3. **更新依赖**：定期更新系统依赖，确保系统的安全性和稳定性。
4. **安全审计**：定期进行安全审计，确保系统的安全性。

## 9. 未来扩展

### 9.1 数据库升级

当系统规模扩大时，可以考虑升级到更强大的数据库，如MongoDB或MySQL：

1. **MongoDB**：适合处理大量非结构化数据，具有良好的扩展性。
2. **MySQL**：适合处理结构化数据，具有良好的性能和可靠性。

### 9.2 功能扩展

1. **添加更多数据模型**：根据业务需求添加更多数据模型，如用户权限、角色管理等。
2. **实现更复杂的查询**：支持更复杂的查询需求，如全文搜索、地理空间查询等。
3. **添加数据分析功能**：实现数据分析功能，便于用户了解系统运行情况。

## 10. 总结

本数据库设计文档详细描述了微信小程序后端的数据库设计，包括数据模型、字段定义、索引策略和数据关系。通过合理的数据库设计，可以提高系统的性能、安全性和可维护性，为微信小程序前端提供稳定可靠的数据支持。