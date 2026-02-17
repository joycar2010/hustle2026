from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from jose import JWTError
from .api import api_router
from .services.websocket_service import websocket_service
from .core.error_handler import (
    custom_http_exception_handler,
    custom_validation_exception_handler,
    custom_sqlalchemy_exception_handler,
    custom_jwt_exception_handler,
    custom_generic_exception_handler
)
import uvicorn
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="跨平台套利系统API",
    description="跨平台套利系统的API接口",
    version="1.0.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册错误处理器
app.add_exception_handler(HTTPException, custom_http_exception_handler)
app.add_exception_handler(RequestValidationError, custom_validation_exception_handler)
app.add_exception_handler(SQLAlchemyError, custom_sqlalchemy_exception_handler)
app.add_exception_handler(JWTError, custom_jwt_exception_handler)
app.add_exception_handler(Exception, custom_generic_exception_handler)

# 注册路由
app.include_router(api_router, prefix="/api/v1")

# WebSocket 路由
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    logger.info(f"WebSocket connection attempt from user {user_id}")
    await websocket_service.manager.connect(websocket, user_id)
    logger.info(f"WebSocket connected for user {user_id}")
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received message from user {user_id}: {data}")
            # 处理客户端消息
            await websocket_service.manager.send_personal_message(
                {"type": "echo", "data": data},
                user_id
            )
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
        websocket_service.manager.disconnect(websocket, user_id)
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {str(e)}")
        websocket_service.manager.disconnect(websocket, user_id)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up the application")
    # 启动 WebSocket 服务
    try:
        await websocket_service.start()
        logger.info("WebSocket service started successfully")
    except Exception as e:
        logger.error(f"Failed to start WebSocket service: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down the application")
    # 停止 WebSocket 服务
    try:
        await websocket_service.stop()
        logger.info("WebSocket service stopped successfully")
    except Exception as e:
        logger.error(f"Failed to stop WebSocket service: {str(e)}")
    # 服务的停止由账户断开操作控制
    pass

@app.get("/")
def root():
    logger.info("Root endpoint accessed")
    return {"message": "跨平台套利系统API"}

@app.get("/health")
def health_check():
    logger.info("Health check endpoint accessed")
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
