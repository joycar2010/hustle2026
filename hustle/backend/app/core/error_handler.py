from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from jose import JWTError
import traceback

async def custom_http_exception_handler(request: Request, exc):
    """自定义HTTP异常处理器"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "path": request.url.path,
                "method": request.method
            }
        }
    )

async def custom_validation_exception_handler(request: Request, exc: RequestValidationError):
    """自定义验证异常处理器"""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": 422,
                "message": "Validation error",
                "details": exc.errors(),
                "path": request.url.path,
                "method": request.method
            }
        }
    )

async def custom_sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    """自定义SQLAlchemy异常处理器"""
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": 500,
                "message": "Database error",
                "details": str(exc),
                "path": request.url.path,
                "method": request.method
            }
        }
    )

async def custom_jwt_exception_handler(request: Request, exc: JWTError):
    """自定义JWT异常处理器"""
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": 401,
                "message": "Invalid or expired token",
                "path": request.url.path,
                "method": request.method
            }
        }
    )

async def custom_generic_exception_handler(request: Request, exc: Exception):
    """自定义通用异常处理器"""
    # 记录详细的错误信息到日志
    error_traceback = traceback.format_exc()
    print(f"Error: {error_traceback}")
    
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": 500,
                "message": "Internal server error",
                "details": str(exc),
                "path": request.url.path,
                "method": request.method
            }
        }
    )

def setup_error_handlers(app: FastAPI):
    """设置错误处理器"""
    # 这里我们将在main.py中注册这些处理器
    pass
