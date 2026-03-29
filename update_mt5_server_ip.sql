-- 将 MT5 实例的服务器 IP 从外网改为内网
-- 54.249.66.53 -> 172.31.14.113

UPDATE mt5_instances
SET server_ip = '172.31.14.113'
WHERE server_ip = '54.249.66.53';

-- 验证更新结果
SELECT instance_id, service_port, server_ip, status
FROM mt5_instances
ORDER BY service_port;
