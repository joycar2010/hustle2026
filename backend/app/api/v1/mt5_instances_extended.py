

# ==================== 新增 API 端点 ====================

@router.get("/client/{client_id}", response_model=List[MT5InstanceResponse])
async def list_instances_by_client(
    client_id: int,
    db: Session = Depends(get_db)
):
    """获取指定MT5客户端的所有实例"""
    instances = db.query(MT5Instance).filter(
        MT5Instance.client_id == client_id
    ).all()
    return instances


@router.post("/client/{client_id}/deploy", response_model=MT5InstanceResponse, status_code=status.HTTP_201_CREATED)
async def deploy_instance_for_client(
    client_id: int,
    instance_data: MT5InstanceCreate,
    db: Session = Depends(get_db)
):
    """为指定MT5客户端部署新实例"""
    from app.models.mt5_client import MT5Client
    from sqlalchemy import func

    # 检查客户端是否存在
    client = db.query(MT5Client).filter(MT5Client.client_id == client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MT5 Client {client_id} not found"
        )

    # 检查该客户端的实例数量（最多2个）
    instance_count = db.query(func.count(MT5Instance.instance_id)).filter(
        MT5Instance.client_id == client_id
    ).scalar()

    if instance_count >= 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 2 instances per client (primary and backup)"
        )

    # 检查该类型的实例是否已存在
    existing_type = db.query(MT5Instance).filter(
        MT5Instance.client_id == client_id,
        MT5Instance.instance_type == instance_data.instance_type
    ).first()

    if existing_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Instance type '{instance_data.instance_type}' already exists for this client"
        )

    # 检查端口是否已被使用
    existing_port = db.query(MT5Instance).filter(
        MT5Instance.service_port == instance_data.service_port
    ).first()

    if existing_port:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Port {instance_data.service_port} already in use"
        )

    # 创建实例记录
    instance_dict = instance_data.dict()
    instance_dict['client_id'] = client_id

    # 如果是第一个实例，自动设为启用
    if instance_count == 0:
        instance_dict['is_active'] = True
    else:
        instance_dict['is_active'] = False

    instance = MT5Instance(**instance_dict)
    db.add(instance)
    db.commit()
    db.refresh(instance)

    # 调用 Windows Agent 部署实例
    agent_service = MT5AgentService(instance.server_ip)
    try:
        # 从客户端获取 MT5 登录信息
        await agent_service.deploy_instance(
            port=instance.service_port,
            mt5_path=instance.mt5_path,
            deploy_path=instance.deploy_path,
            auto_start=instance.auto_start,
            account=client.mt5_login,
            server=client.mt5_server
        )
    except Exception as e:
        # 部署失败，删除数据库记录
        db.delete(instance)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deploy instance: {str(e)}"
        )

    return instance


@router.post("/client/{client_id}/switch", response_model=dict)
async def switch_active_instance(
    client_id: int,
    target_instance_id: UUID,
    db: Session = Depends(get_db)
):
    """切换活动实例（主备切换）"""
    from app.models.mt5_client import MT5Client

    # 检查客户端是否存在
    client = db.query(MT5Client).filter(MT5Client.client_id == client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MT5 Client {client_id} not found"
        )

    # 检查目标实例是否存在且属于该客户端
    target_instance = db.query(MT5Instance).filter(
        MT5Instance.instance_id == target_instance_id,
        MT5Instance.client_id == client_id
    ).first()

    if not target_instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {target_instance_id} not found or does not belong to client {client_id}"
        )

    # 如果目标实例已经是活动的，直接返回
    if target_instance.is_active:
        return {"status": "ok", "message": "Target instance is already active"}

    # 获取当前活动的实例
    current_active = db.query(MT5Instance).filter(
        MT5Instance.client_id == client_id,
        MT5Instance.is_active == True
    ).first()

    try:
        # 停止当前活动实例
        if current_active:
            agent_service = MT5AgentService(current_active.server_ip)
            try:
                await agent_service.stop_instance(current_active.service_port)
                current_active.is_active = False
                current_active.status = "stopped"
            except Exception as e:
                # 记录错误但继续切换
                print(f"Warning: Failed to stop current instance: {str(e)}")

        # 启动目标实例
        agent_service = MT5AgentService(target_instance.server_ip)
        await agent_service.start_instance(target_instance.service_port)
        target_instance.is_active = True
        target_instance.status = "running"

        # 更新客户端连接状态
        client.connection_status = "connected"

        db.commit()

        return {
            "status": "ok",
            "message": "Instance switched successfully",
            "previous_instance": str(current_active.instance_id) if current_active else None,
            "current_instance": str(target_instance.instance_id)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to switch instance: {str(e)}"
        )


@router.get("/client/{client_id}/health", response_model=dict)
async def check_client_health(
    client_id: int,
    db: Session = Depends(get_db)
):
    """检查MT5客户端的健康状态（包括所有实例）"""
    from app.models.mt5_client import MT5Client

    # 检查客户端是否存在
    client = db.query(MT5Client).filter(MT5Client.client_id == client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MT5 Client {client_id} not found"
        )

    # 获取所有实例
    instances = db.query(MT5Instance).filter(
        MT5Instance.client_id == client_id
    ).all()

    health_data = {
        "client_id": client_id,
        "client_name": client.client_name,
        "is_connected": client.is_connected,
        "instances": []
    }

    # 检查每个实例的状态
    for instance in instances:
        agent_service = MT5AgentService(instance.server_ip)
        try:
            status_data = await agent_service.get_instance_status(instance.service_port)
            instance_health = {
                "instance_id": str(instance.instance_id),
                "instance_name": instance.instance_name,
                "instance_type": instance.instance_type,
                "is_active": instance.is_active,
                "status": status_data.get("status", "unknown"),
                "healthy": status_data.get("status") == "running"
            }
        except Exception as e:
            instance_health = {
                "instance_id": str(instance.instance_id),
                "instance_name": instance.instance_name,
                "instance_type": instance.instance_type,
                "is_active": instance.is_active,
                "status": "error",
                "healthy": False,
                "error": str(e)
            }

        health_data["instances"].append(instance_health)

    # 判断整体健康状态
    active_instances = [i for i in health_data["instances"] if i["is_active"]]
    health_data["overall_healthy"] = any(i["healthy"] for i in active_instances) if active_instances else False

    return health_data


@router.post("/client/{client_id}/auto-failover", response_model=dict)
async def auto_failover(
    client_id: int,
    db: Session = Depends(get_db)
):
    """自动故障转移：如果主实例失败，自动切换到备用实例"""
    from app.models.mt5_client import MT5Client

    # 检查客户端是否存在
    client = db.query(MT5Client).filter(MT5Client.client_id == client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MT5 Client {client_id} not found"
        )

    # 获取当前活动实例
    active_instance = db.query(MT5Instance).filter(
        MT5Instance.client_id == client_id,
        MT5Instance.is_active == True
    ).first()

    if not active_instance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active instance found"
        )

    # 检查活动实例健康状态
    agent_service = MT5AgentService(active_instance.server_ip)
    try:
        status_data = await agent_service.get_instance_status(active_instance.service_port)
        if status_data.get("status") == "running":
            return {
                "status": "ok",
                "message": "Active instance is healthy, no failover needed",
                "active_instance": str(active_instance.instance_id)
            }
    except Exception:
        # 活动实例不健康，需要故障转移
        pass

    # 获取备用实例
    backup_instance = db.query(MT5Instance).filter(
        MT5Instance.client_id == client_id,
        MT5Instance.is_active == False
    ).first()

    if not backup_instance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No backup instance available for failover"
        )

    # 执行故障转移
    try:
        # 停用当前实例
        active_instance.is_active = False
        active_instance.status = "error"

        # 启动备用实例
        backup_agent = MT5AgentService(backup_instance.server_ip)
        await backup_agent.start_instance(backup_instance.service_port)
        backup_instance.is_active = True
        backup_instance.status = "running"

        db.commit()

        return {
            "status": "ok",
            "message": "Failover completed successfully",
            "failed_instance": str(active_instance.instance_id),
            "new_active_instance": str(backup_instance.instance_id)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failover failed: {str(e)}"
        )
