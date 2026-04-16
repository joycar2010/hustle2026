"""
HedgingPairService — 全局产品对配置服务

提供内存缓存的产品对配置，供策略、行情、下单模块使用。
启动时从数据库加载，5分钟自动刷新。
"""
import asyncio
import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SymbolConfig:
    """平台品种配置"""
    id: str
    platform_id: int
    platform_name: str
    platform_type: str  # cex / mt5
    symbol: str
    base_asset: str
    quote_asset: str
    contract_unit: float
    qty_unit: str
    qty_precision: int
    qty_step: float
    min_qty: float
    price_precision: int
    price_step: float
    maker_fee_rate: float
    taker_fee_rate: float
    margin_rate_initial: float
    trading_hours: Optional[dict] = None


@dataclass
class HedgingPairConfig:
    """对冲产品对完整配置"""
    id: str
    pair_name: str
    pair_code: str
    symbol_a: SymbolConfig
    symbol_b: SymbolConfig
    account_a_id: Optional[str] = None
    account_b_id: Optional[str] = None
    conversion_factor: float = 100.0
    usd_usdt_rate: float = 1.0
    spread_mode: str = "absolute"
    spread_precision: int = 2
    default_spread_target: Optional[float] = None
    is_active: bool = True


class HedgingPairService:
    """全局对冲产品对配置管理"""

    def __init__(self):
        self._pairs: Dict[str, HedgingPairConfig] = {}
        self._loaded = False
        self._last_load: Optional[datetime] = None
        self._refresh_task: Optional[asyncio.Task] = None

    @property
    def loaded(self) -> bool:
        return self._loaded

    def get_pair(self, pair_code: str) -> Optional[HedgingPairConfig]:
        """获取产品对配置 (如 'XAU', 'XAG', 'CL')"""
        return self._pairs.get(pair_code)

    def get_active_pair(self, pair_code: str) -> Optional[HedgingPairConfig]:
        """获取启用的产品对"""
        p = self._pairs.get(pair_code)
        return p if p and p.is_active else None

    def list_active_pairs(self) -> List[HedgingPairConfig]:
        """列出所有启用的产品对"""
        return [p for p in self._pairs.values() if p.is_active]

    def get_default_pair(self) -> Optional[HedgingPairConfig]:
        """获取默认产品对 (XAU)"""
        return self._pairs.get('XAU')

    async def load(self):
        """从数据库加载所有产品对配置"""
        try:
            from app.core.database import AsyncSessionLocal
            from sqlalchemy import text

            async with AsyncSessionLocal() as session:
                r = await session.execute(text("""
                    SELECT
                        hp.id AS pair_id, hp.pair_name, hp.pair_code,
                        hp.account_a_id, hp.account_b_id,
                        hp.conversion_factor, hp.usd_usdt_rate,
                        hp.spread_mode, hp.spread_precision, hp.default_spread_target,
                        hp.is_active,
                        -- Side A symbol
                        sa.id AS sa_id, sa.platform_id AS sa_platform_id, sa.symbol AS sa_symbol,
                        sa.base_asset AS sa_base_asset, sa.quote_asset AS sa_quote_asset,
                        sa.contract_unit AS sa_contract_unit, sa.qty_unit AS sa_qty_unit,
                        sa.qty_precision AS sa_qty_precision, sa.qty_step AS sa_qty_step,
                        sa.min_qty AS sa_min_qty, sa.price_precision AS sa_price_precision,
                        sa.price_step AS sa_price_step, sa.maker_fee_rate AS sa_maker_fee_rate,
                        sa.taker_fee_rate AS sa_taker_fee_rate, sa.margin_rate_initial AS sa_margin_initial,
                        sa.trading_hours AS sa_trading_hours,
                        pa.platform_name AS pa_name, pa.platform_type AS pa_type,
                        -- Side B symbol
                        sb.id AS sb_id, sb.platform_id AS sb_platform_id, sb.symbol AS sb_symbol,
                        sb.base_asset AS sb_base_asset, sb.quote_asset AS sb_quote_asset,
                        sb.contract_unit AS sb_contract_unit, sb.qty_unit AS sb_qty_unit,
                        sb.qty_precision AS sb_qty_precision, sb.qty_step AS sb_qty_step,
                        sb.min_qty AS sb_min_qty, sb.price_precision AS sb_price_precision,
                        sb.price_step AS sb_price_step, sb.maker_fee_rate AS sb_maker_fee_rate,
                        sb.taker_fee_rate AS sb_taker_fee_rate, sb.margin_rate_initial AS sb_margin_initial,
                        sb.trading_hours AS sb_trading_hours,
                        pb.platform_name AS pb_name, pb.platform_type AS pb_type
                    FROM hedging_pairs hp
                    JOIN platform_symbols sa ON hp.symbol_a_id = sa.id
                    JOIN platform_symbols sb ON hp.symbol_b_id = sb.id
                    JOIN platforms pa ON sa.platform_id = pa.platform_id
                    JOIN platforms pb ON sb.platform_id = pb.platform_id
                """))
                rows = r.mappings().all()

            new_pairs = {}
            for row in rows:
                sym_a = SymbolConfig(
                    id=str(row['sa_id']), platform_id=row['sa_platform_id'],
                    platform_name=row['pa_name'], platform_type=row['pa_type'],
                    symbol=row['sa_symbol'], base_asset=row['sa_base_asset'],
                    quote_asset=row['sa_quote_asset'], contract_unit=row['sa_contract_unit'],
                    qty_unit=row['sa_qty_unit'], qty_precision=row['sa_qty_precision'],
                    qty_step=row['sa_qty_step'], min_qty=row['sa_min_qty'],
                    price_precision=row['sa_price_precision'], price_step=row['sa_price_step'],
                    maker_fee_rate=row['sa_maker_fee_rate'], taker_fee_rate=row['sa_taker_fee_rate'],
                    margin_rate_initial=row['sa_margin_initial'], trading_hours=row['sa_trading_hours'],
                )
                sym_b = SymbolConfig(
                    id=str(row['sb_id']), platform_id=row['sb_platform_id'],
                    platform_name=row['pb_name'], platform_type=row['pb_type'],
                    symbol=row['sb_symbol'], base_asset=row['sb_base_asset'],
                    quote_asset=row['sb_quote_asset'], contract_unit=row['sb_contract_unit'],
                    qty_unit=row['sb_qty_unit'], qty_precision=row['sb_qty_precision'],
                    qty_step=row['sb_qty_step'], min_qty=row['sb_min_qty'],
                    price_precision=row['sb_price_precision'], price_step=row['sb_price_step'],
                    maker_fee_rate=row['sb_maker_fee_rate'], taker_fee_rate=row['sb_taker_fee_rate'],
                    margin_rate_initial=row['sb_margin_initial'], trading_hours=row['sb_trading_hours'],
                )
                pair = HedgingPairConfig(
                    id=str(row['pair_id']), pair_name=row['pair_name'], pair_code=row['pair_code'],
                    symbol_a=sym_a, symbol_b=sym_b,
                    account_a_id=str(row['account_a_id']) if row['account_a_id'] else None,
                    account_b_id=str(row['account_b_id']) if row['account_b_id'] else None,
                    conversion_factor=row['conversion_factor'], usd_usdt_rate=row['usd_usdt_rate'],
                    spread_mode=row['spread_mode'], spread_precision=row['spread_precision'],
                    default_spread_target=row['default_spread_target'], is_active=row['is_active'],
                )
                new_pairs[pair.pair_code] = pair

            self._pairs = new_pairs
            self._loaded = True
            self._last_load = datetime.utcnow()

            # 同步 QuantityConverter 缓存
            from app.utils.quantity_converter import QuantityConverter
            await QuantityConverter.load_from_db()

            logger.info(f"[HedgingPairService] Loaded {len(new_pairs)} pairs: {list(new_pairs.keys())}")
            return len(new_pairs)

        except Exception as e:
            logger.error(f"[HedgingPairService] Failed to load: {e}")
            return 0

    async def start_refresh(self, interval: int = 300):
        """启动定时刷新 (默认5分钟)"""
        await self.load()

        async def _loop():
            while True:
                await asyncio.sleep(interval)
                await self.load()

        self._refresh_task = asyncio.create_task(_loop())

    async def stop(self):
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass


# 全局单例
hedging_pair_service = HedgingPairService()
