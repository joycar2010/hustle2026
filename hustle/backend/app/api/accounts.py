from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..core.database import get_db
from ..models import Account, User
from ..schemas import AccountCreate, AccountUpdate, AccountResponse
from ..services.market_data_service import MarketDataService
from ..services.strategy_engine import StrategyEngine
from ..services.risk_control_service import RiskControlService
from ..services.websocket_service import websocket_service
from ..services.auth_service import auth_service
from ..core.security import encrypt_data, decrypt_data
from .auth import get_current_user

# 全局服务实例
market_data_service = MarketDataService()
strategy_engine = StrategyEngine()
risk_control_service = RiskControlService()

router = APIRouter()

@router.post("/", response_model=AccountResponse)
def create_account(account_in: AccountCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 加密敏感信息
    encrypted_api_key = encrypt_data(account_in.api_key)
    encrypted_api_secret = encrypt_data(account_in.api_secret)
    encrypted_passphrase = encrypt_data(account_in.passphrase) if account_in.passphrase else None
    encrypted_mt5_id = encrypt_data(account_in.mt5_id) if account_in.mt5_id else None
    encrypted_mt5_server = encrypt_data(account_in.mt5_server) if account_in.mt5_server else None
    encrypted_mt5_primary_pwd = encrypt_data(account_in.mt5_primary_pwd) if account_in.mt5_primary_pwd else None
    
    account = Account(
        user_id=current_user.user_id,
        platform_id=account_in.platform_id,
        account_name=account_in.account_name,
        api_key=encrypted_api_key,
        api_secret=encrypted_api_secret,
        passphrase=encrypted_passphrase,
        mt5_id=encrypted_mt5_id,
        mt5_server=encrypted_mt5_server,
        mt5_primary_pwd=encrypted_mt5_primary_pwd,
        is_mt5_account=account_in.is_mt5_account,
        is_default=account_in.is_default,
        is_active=account_in.is_active
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    
    # 解密敏感信息用于返回
    account.api_key = decrypt_data(account.api_key)
    account.api_secret = decrypt_data(account.api_secret)
    if account.passphrase:
        account.passphrase = decrypt_data(account.passphrase)
    if account.mt5_id:
        account.mt5_id = decrypt_data(account.mt5_id)
    if account.mt5_server:
        account.mt5_server = decrypt_data(account.mt5_server)
    if account.mt5_primary_pwd:
        account.mt5_primary_pwd = decrypt_data(account.mt5_primary_pwd)
    
    return account

@router.get("/", response_model=List[AccountResponse])
def get_accounts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    accounts = db.query(Account).filter(Account.user_id == current_user.user_id).all()
    # 解密敏感信息用于返回
    for account in accounts:
        account.api_key = decrypt_data(account.api_key)
        account.api_secret = decrypt_data(account.api_secret)
        if account.passphrase:
            account.passphrase = decrypt_data(account.passphrase)
        if account.mt5_id:
            account.mt5_id = decrypt_data(account.mt5_id)
        if account.mt5_server:
            account.mt5_server = decrypt_data(account.mt5_server)
        if account.mt5_primary_pwd:
            account.mt5_primary_pwd = decrypt_data(account.mt5_primary_pwd)
    return accounts

@router.get("/list", response_model=List[AccountResponse])
def get_accounts_list(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    accounts = db.query(Account).filter(Account.user_id == current_user.user_id).all()
    # 解密敏感信息用于返回
    for account in accounts:
        account.api_key = decrypt_data(account.api_key)
        account.api_secret = decrypt_data(account.api_secret)
        if account.passphrase:
            account.passphrase = decrypt_data(account.passphrase)
        if account.mt5_id:
            account.mt5_id = decrypt_data(account.mt5_id)
        if account.mt5_server:
            account.mt5_server = decrypt_data(account.mt5_server)
        if account.mt5_primary_pwd:
            account.mt5_primary_pwd = decrypt_data(account.mt5_primary_pwd)
    return accounts

@router.post("/connect")
async def connect_account(account_data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 实现实际的账户连接逻辑
    account_id = account_data.get("account_id")
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少账户ID"
        )
    
    account = db.query(Account).filter(Account.account_id == account_id, Account.user_id == current_user.user_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="账户不存在或无权限访问"
        )
    
    # 更新账户状态为活跃
    account.is_active = True
    db.commit()
    db.refresh(account)
    
    # 启动三个核心服务
    try:
        await market_data_service.start()
        await strategy_engine.start()
        await risk_control_service.start()
        await websocket_service.start()
        print("四个核心服务已成功启动")
    except Exception as e:
        print(f"启动服务时出错: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="启动服务时出错"
        )
    
    return {"message": "账户连接成功，服务已启动"}

@router.post("/disconnect")
async def disconnect_account(account_data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 实现实际的账户断开逻辑
    account_id = account_data.get("account_id")
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少账户ID"
        )
    
    account = db.query(Account).filter(Account.account_id == account_id, Account.user_id == current_user.user_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="账户不存在或无权限访问"
        )
    
    # 更新账户状态为非活跃
    account.is_active = False
    db.commit()
    db.refresh(account)
    
    # 检查是否还有其他活跃账户
    active_accounts = db.query(Account).filter(Account.is_active == True).count()
    if active_accounts == 0:
        # 停止四个核心服务
        try:
            await market_data_service.stop()
            await strategy_engine.stop()
            await risk_control_service.stop()
            await websocket_service.stop()
            print("四个核心服务已成功停止")
        except Exception as e:
            print(f"停止服务时出错: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="停止服务时出错"
            )
    
    return {"message": "账户断开成功"}

@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = db.query(Account).filter(Account.account_id == account_id, Account.user_id == current_user.user_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="账户不存在或无权限访问"
        )
    # 解密敏感信息用于返回
    account.api_key = decrypt_data(account.api_key)
    account.api_secret = decrypt_data(account.api_secret)
    if account.passphrase:
        account.passphrase = decrypt_data(account.passphrase)
    if account.mt5_id:
        account.mt5_id = decrypt_data(account.mt5_id)
    if account.mt5_server:
        account.mt5_server = decrypt_data(account.mt5_server)
    if account.mt5_primary_pwd:
        account.mt5_primary_pwd = decrypt_data(account.mt5_primary_pwd)
    return account

@router.put("/{account_id}", response_model=AccountResponse)
def update_account(account_id: str, account_in: AccountUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = db.query(Account).filter(Account.account_id == account_id, Account.user_id == current_user.user_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="账户不存在或无权限访问"
        )
    
    update_data = account_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        # 对敏感信息进行加密
        if field in ['api_key', 'api_secret'] and value:
            setattr(account, field, encrypt_data(value))
        elif field in ['passphrase', 'mt5_id', 'mt5_server', 'mt5_primary_pwd'] and value:
            setattr(account, field, encrypt_data(value))
        else:
            setattr(account, field, value)
    
    db.commit()
    db.refresh(account)
    
    # 解密敏感信息用于返回
    account.api_key = decrypt_data(account.api_key)
    account.api_secret = decrypt_data(account.api_secret)
    if account.passphrase:
        account.passphrase = decrypt_data(account.passphrase)
    if account.mt5_id:
        account.mt5_id = decrypt_data(account.mt5_id)
    if account.mt5_server:
        account.mt5_server = decrypt_data(account.mt5_server)
    if account.mt5_primary_pwd:
        account.mt5_primary_pwd = decrypt_data(account.mt5_primary_pwd)
    
    return account

@router.delete("/{account_id}")
def delete_account(account_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = db.query(Account).filter(Account.account_id == account_id, Account.user_id == current_user.user_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="账户不存在或无权限访问"
        )
    db.delete(account)
    db.commit()
    return {"message": "账户删除成功"}
