-- 同步旧版 Bridge 实例数据到新版 Bridge 服务控制
-- 执行方式：PGPASSWORD=Lk106504 psql -h 127.0.0.1 -U postgres -d postgres -f sync_bridge_data.sql

-- 1. 查看当前 MT5-01 和 MT5-Sys-Server 的配置
SELECT
    client_id,
    client_name,
    bridge_service_name,
    bridge_service_port,
    mt5_login,
    mt5_server
FROM mt5_clients
WHERE client_name IN ('MT5-01', 'MT5-Sys-Server');

-- 2. 查看现有的 Bridge 实例数据
SELECT
    i.instance_id,
    i.client_id,
    c.client_name,
    i.instance_name,
    i.server_ip,
    i.service_port,
    i.instance_type,
    i.is_active
FROM mt5_instances i
JOIN mt5_clients c ON i.client_id = c.client_id
WHERE c.client_name IN ('MT5-01', 'MT5-Sys-Server');

-- 3. 根据实际情况更新 MT5-01 的 Bridge 配置
-- 假设 MT5-01 的 Bridge 服务名为 hustle-mt5-mt5-01，端口为 8002
UPDATE mt5_clients
SET
    bridge_service_name = 'hustle-mt5-mt5-01',
    bridge_service_port = 8002
WHERE client_name = 'MT5-01'
  AND bridge_service_name IS NULL;

-- 4. 根据实际情况更新 MT5-Sys-Server 的 Bridge 配置
-- 假设 MT5-Sys-Server 的 Bridge 服务名为 hustle-mt5-mt5-sys-server，端口为 8001
UPDATE mt5_clients
SET
    bridge_service_name = 'hustle-mt5-mt5-sys-server',
    bridge_service_port = 8001
WHERE client_name = 'MT5-Sys-Server'
  AND bridge_service_name IS NULL;

-- 5. 验证更新结果
SELECT
    client_id,
    client_name,
    bridge_service_name,
    bridge_service_port,
    mt5_login,
    mt5_server
FROM mt5_clients
WHERE client_name IN ('MT5-01', 'MT5-Sys-Server');

-- 注意：
-- 1. 请根据实际的 Bridge 服务名称和端口号修改上面的 UPDATE 语句
-- 2. 可以通过查询 Windows 服务器上的服务列表来确认服务名称：
--    sc query | findstr /i "hustle-mt5"
-- 3. 端口号可以从 mt5_instances 表的 service_port 字段获取
