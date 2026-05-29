# Database Backup

## 文件说明
- `postgres_YYYYMMDD_HHMM.dump.gz.part_*` - PostgreSQL 自定义格式备份 (Fc + gzip + split)
- `schema_YYYYMMDD_HHMM.sql` - 仅 schema 文本备份 (审计用)

## 恢复方法

### 合并分割文件
```bash
cat postgres_*.dump.gz.part_* > postgres.dump.gz
gunzip postgres.dump.gz
```

### 恢复数据库
```bash
# 创建空数据库 (如果不存在)
createdb -h 127.0.0.1 -U postgres -T template0 postgres_restore

# 恢复 (Fc 格式)
pg_restore -h 127.0.0.1 -U postgres -d postgres_restore --clean --if-exists postgres.dump
```

## 备份时间
test 服务器 PostgreSQL 主库 (postgres database) 完整备份。
