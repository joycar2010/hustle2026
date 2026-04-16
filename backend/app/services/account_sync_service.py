"""
Account Sync Service
Synchronizes account data from Binance and Bybit platforms
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.account import Account
from app.models.position import Position
from app.models.account_snapshot import AccountSnapshot
from app.services.binance_client import BinanceFuturesClient
from app.services.bybit_client import BybitV5Client

logger = logging.getLogger(__name__)


class AccountSyncService:
    """Service for syncing account data from trading platforms"""

    def __init__(self):
        self.binance_client = BinanceFuturesClient(
            api_key=settings.BINANCE_API_KEY,
            api_secret=settings.BINANCE_API_SECRET
        )
        self.bybit_client = BybitV5Client(
            api_key=settings.BYBIT_API_KEY,
            api_secret=settings.BYBIT_API_SECRET
        )
        self.is_running = False

    async def start(self):
        """Start the account sync service"""
        self.is_running = True
        logger.info("Account sync service started")

        while self.is_running:
            try:
                await self.sync_all_accounts()
                await asyncio.sleep(10)  # Sync every 10 seconds
            except Exception as e:
                logger.error(f"Error in account sync loop: {e}")
                await asyncio.sleep(5)

    async def stop(self):
        """Stop the account sync service"""
        self.is_running = False
        logger.info("Account sync service stopped")

    async def sync_all_accounts(self):
        """Sync all active accounts"""
        db = SessionLocal()
        try:
            # Get all active accounts
            accounts = db.query(Account).filter(Account.is_active == True).all()

            for account in accounts:
                try:
                    if account.platform == "binance":
                        await self.sync_binance_account(db, account)
                    elif account.platform == "bybit":
                        await self.sync_bybit_account(db, account)
                except Exception as e:
                    logger.error(f"Error syncing account {account.account_id}: {e}")

            db.commit()
        except Exception as e:
            logger.error(f"Error in sync_all_accounts: {e}")
            db.rollback()
        finally:
            db.close()

    async def sync_binance_account(self, db: Session, account: Account):
        """Sync Binance account data"""
        try:
            # Get account information
            account_data = await self.binance_client.get_account()
            if account_data:
                # Get balance data
                total_wallet_balance = float(account_data.get('totalWalletBalance', 0))
                available_balance = float(account_data.get('availableBalance', 0))
                margin_used = float(account_data.get('totalInitialMargin', 0))
                unrealized_pnl = float(account_data.get('totalUnrealizedProfit', 0))

                # Create account snapshot
                snapshot = AccountSnapshot(
                    account_id=account.account_id,
                    total_assets=total_wallet_balance,
                    available_assets=available_balance,
                    net_assets=total_wallet_balance + unrealized_pnl,
                    total_position=0.0,  # Will be calculated from positions
                    frozen_assets=margin_used,
                    margin_balance=total_wallet_balance,
                    margin_used=margin_used,
                    margin_available=available_balance,
                    unrealized_pnl=unrealized_pnl,
                    daily_pnl=0.0,  # Not available from this API
                    risk_ratio=0.0 if total_wallet_balance == 0 else (margin_used / total_wallet_balance),
                    timestamp=datetime.utcnow()
                )
                db.add(snapshot)

            # Get open positions
            positions_data = await self.binance_client.get_position_risk()
            if positions_data:
                await self.update_positions(db, account, positions_data, "binance")

        except Exception as e:
            logger.error(f"Error syncing Binance account {account.account_id}: {e}")

    async def sync_bybit_account(self, db: Session, account: Account):
        """Sync Bybit account data"""
        try:
            # Get wallet balance
            balance_data = await self.bybit_client.get_wallet_balance("UNIFIED")
            if balance_data and 'list' in balance_data and len(balance_data['list']) > 0:
                wallet = balance_data['list'][0]
                # Get balance data
                total_equity = float(wallet.get('totalEquity', 0))
                total_available = float(wallet.get('totalAvailableBalance', 0))
                margin_used = float(wallet.get('totalInitialMargin', 0))
                unrealized_pnl = float(wallet.get('totalPerpUPL', 0))

                # Create account snapshot
                snapshot = AccountSnapshot(
                    account_id=account.account_id,
                    total_assets=total_equity,
                    available_assets=total_available,
                    net_assets=total_equity,
                    total_position=0.0,  # Will be calculated from positions
                    frozen_assets=margin_used,
                    margin_balance=total_equity,
                    margin_used=margin_used,
                    margin_available=total_available,
                    unrealized_pnl=unrealized_pnl,
                    daily_pnl=0.0,  # Not available from this API
                    risk_ratio=0.0 if total_equity == 0 else (margin_used / total_equity),
                    timestamp=datetime.utcnow()
                )
                db.add(snapshot)

            # Get open positions
            positions_data = await self.bybit_client.get_positions("linear")
            if positions_data and 'list' in positions_data:
                await self.update_positions(db, account, positions_data['list'], "bybit")

        except Exception as e:
            logger.error(f"Error syncing Bybit account {account.account_id}: {e}")

    async def update_positions(self, db: Session, account: Account, positions_data: List[Dict], platform: str):
        """Update positions from platform data"""
        try:
            for pos_data in positions_data:
                # Skip positions with zero size
                size = float(pos_data.get('size', 0) or pos_data.get('positionAmt', 0))
                if size == 0:
                    continue

                symbol = pos_data.get('symbol', '')
                side = 'long' if size > 0 else 'short'

                # Check if position exists
                existing_position = db.query(Position).filter(
                    Position.account_id == account.account_id,
                    Position.symbol == symbol,
                    Position.platform == platform,
                    Position.is_open == True
                ).first()

                if existing_position:
                    # Update existing position
                    existing_position.current_price = float(pos_data.get('markPrice', 0) or pos_data.get('entryPrice', 0))
                    existing_position.quantity = abs(size)
                    existing_position.unrealized_pnl = float(pos_data.get('unrealizedProfit', 0) or pos_data.get('unRealizedProfit', 0))
                    existing_position.update_time = datetime.utcnow()
                else:
                    # Create new position
                    new_position = Position(
                        user_id=account.user_id,
                        account_id=account.account_id,
                        symbol=symbol,
                        platform=platform,
                        side=side,
                        entry_price=float(pos_data.get('entryPrice', 0) or pos_data.get('avgPrice', 0)),
                        current_price=float(pos_data.get('markPrice', 0) or pos_data.get('entryPrice', 0)),
                        quantity=abs(size),
                        leverage=int(pos_data.get('leverage', 1)),
                        unrealized_pnl=float(pos_data.get('unrealizedProfit', 0) or pos_data.get('unRealizedProfit', 0)),
                        margin_used=float(pos_data.get('initialMargin', 0) or pos_data.get('positionIM', 0)),
                        is_open=True,
                        open_time=datetime.utcnow()
                    )
                    db.add(new_position)

        except Exception as e:
            logger.error(f"Error updating positions: {e}")


# Global instance
account_sync_service = AccountSyncService()

