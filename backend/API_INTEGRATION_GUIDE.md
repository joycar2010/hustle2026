# MT5 Instances API 集成指南

## 需要添加的导入

在 `backend/app/api/v1/mt5_instances.py` 文件顶部添加：

```python
from sqlalchemy import func
from app.models.mt5_client import MT5Client
from app.schemas.mt5_instance import MT5InstanceSwitch
```

## 需要添加的新端点

将 `mt5_instances_extended.py` 中的所有新端点复制到 `mt5_instances.py` 文件末尾：

1. `GET /client/{client_id}` - 获取指定客户端的所有实例
2. `POST /client/{client_id}/deploy` - 为客户端部署新实例
3. `POST /client/{client_id}/switch` - 切换活动实例
4. `GET /client/{client_id}/health` - 检查客户端健康状态
5. `POST /client/{client_id}/auto-failover` - 自动故障转移

## 修改现有的 create_instance 端点

在 `create_instance` 函数中添加对 `client_id` 的支持：

```python
@router.post("", response_model=MT5InstanceResponse, status_code=status.HTTP_201_CREATED)
async def create_instance(
    instance_data: MT5InstanceCreate,
    db: Session = Depends(get_db)
):
    """创建新的MT5实例"""
    # 如果指定了 client_id，检查客户端是否存在
    if instance_data.client_id:
        client = db.query(MT5Client).filter(
            MT5Client.client_id == instance_data.client_id
        ).first()
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MT5 Client {instance_data.client_id} not found"
            )

        # 检查该客户端的实例数量
        instance_count = db.query(func.count(MT5Instance.instance_id)).filter(
            MT5Instance.client_id == instance_data.client_id
        ).scalar()

        if instance_count >= 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 2 instances per client"
            )

    # ... 其余代码保持不变
```

## 数据库迁移

在生产服务器上执行：

```bash
cd /home/ubuntu/hustle2026/backend
sudo -u postgres psql hustle_db < migrations/add_mt5_instance_client_relation.sql
```

## 测试新 API

```bash
# 1. 为客户端部署新实例
curl -X POST "http://localhost:8000/api/v1/mt5/instances/client/1/deploy" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "instance_name": "Primary Instance",
    "server_ip": "172.31.14.113",
    "service_port": 8003,
    "mt5_path": "C:/MT5/terminal.exe",
    "deploy_path": "C:/Services/MT5_Primary",
    "instance_type": "primary",
    "auto_start": true
  }'

# 2. 获取客户端的所有实例
curl "http://localhost:8000/api/v1/mt5/instances/client/1" \
  -H "Authorization: Bearer $TOKEN"

# 3. 检查客户端健康状态
curl "http://localhost:8000/api/v1/mt5/instances/client/1/health" \
  -H "Authorization: Bearer $TOKEN"

# 4. 切换活动实例
curl -X POST "http://localhost:8000/api/v1/mt5/instances/client/1/switch" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "target_instance_id": "uuid-here"
  }'

# 5. 自动故障转移
curl -X POST "http://localhost:8000/api/v1/mt5/instances/client/1/auto-failover" \
  -H "Authorization: Bearer $TOKEN"
```

## 注意事项

1. **并发控制**：确保同一客户端只有一个实例处于活动状态
2. **事务处理**：切换实例时使用数据库事务确保一致性
3. **错误处理**：故障转移失败时需要回滚状态
4. **日志记录**：记录所有切换和故障转移操作
5. **监控告警**：实现健康检查定时任务，自动触发故障转移
