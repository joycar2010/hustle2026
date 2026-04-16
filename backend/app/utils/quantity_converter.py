"""
统一的数量单位转换工具类 — 支持多品种

每个对冲产品对有独立的换算参数（从 platform_symbols + hedging_pairs 读取）：
- XAU: 1 Lot = 100 XAU   (conversion_factor=100)
- XAG: 1 Lot = 5000 XAG  (conversion_factor=500, 因为 Binance 步长=10)
- CL/BZ: 1 Lot = 1000 BBL (conversion_factor=1000)
- NG: 1 Lot = 10000 mmBtu (conversion_factor=1000, 因为 Binance 步长=10)
"""

from typing import Union, Optional, Dict, Any
import math


class PairQuantityConverter:
    """品种级别的数量转换器 — 每个对冲产品对一个实例"""

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 包含以下字段：
                conversion_factor: A侧单位 per B侧单位 (如 100 = 1 lot = 100 XAU)
                qty_precision_a: A侧数量精度
                qty_step_a: A侧数量步长
                min_qty_a: A侧最小下单量
                qty_unit_a: A侧单位名称
                qty_precision_b: B侧数量精度
                qty_step_b: B侧数量步长
                min_qty_b: B侧最小下单量
                qty_unit_b: B侧单位名称
        """
        self.factor = config.get('conversion_factor', 100.0)
        self.prec_a = config.get('qty_precision_a', 0)
        self.step_a = config.get('qty_step_a', 1.0)
        self.min_a = config.get('min_qty_a', 1.0)
        self.unit_a = config.get('qty_unit_a', 'XAU')
        self.prec_b = config.get('qty_precision_b', 2)
        self.step_b = config.get('qty_step_b', 0.01)
        self.min_b = config.get('min_qty_b', 0.01)
        self.unit_b = config.get('qty_unit_b', 'lot')

    def a_to_b(self, qty_a: Union[int, float]) -> float:
        """A侧数量 → B侧数量 (如 XAU → Lot)"""
        if not qty_a:
            return 0.0
        raw = qty_a / self.factor
        return self._align(raw, self.step_b, self.prec_b)

    def b_to_a(self, qty_b: Union[int, float]) -> float:
        """B侧数量 → A侧数量 (如 Lot → XAU)"""
        if not qty_b:
            return 0.0
        raw = qty_b * self.factor
        return self._align(raw, self.step_a, self.prec_a)

    def normalize_a(self, qty: Union[int, float]) -> float:
        """A侧数量对齐到步长"""
        return self._align(qty, self.step_a, self.prec_a)

    def normalize_b(self, qty: Union[int, float]) -> float:
        """B侧数量对齐到步长"""
        return self._align(qty, self.step_b, self.prec_b)

    def validate_a(self, qty: Union[int, float]) -> tuple:
        if not qty or qty <= 0:
            return False, "数量无效"
        if qty < self.min_a:
            return False, f"最小下单量为 {self.min_a} {self.unit_a}"
        return True, ""

    def validate_b(self, qty: Union[int, float]) -> tuple:
        if not qty or qty <= 0:
            return False, "数量无效"
        if qty < self.min_b:
            return False, f"最小下单量为 {self.min_b} {self.unit_b}"
        return True, ""

    @staticmethod
    def _align(val: float, step: float, precision: int) -> float:
        """Align value to step size and round to precision"""
        if step and step > 0:
            val = math.floor(val / step) * step
        return round(val, precision)


class QuantityConverter:
    """全局数量转换器 — 兼容旧接口 + 支持多品种"""

    # 默认值（黄金，向后兼容）
    XAU_PER_LOT = 100.0
    LOT_PRECISION = 2
    XAU_PRECISION = 0
    MIN_LOT = 0.01
    MIN_XAU = 1

    # 品种转换器缓存
    _pair_converters: Dict[str, PairQuantityConverter] = {}

    @classmethod
    def get_pair_converter(cls, pair_code: str) -> Optional[PairQuantityConverter]:
        """获取品种级转换器"""
        return cls._pair_converters.get(pair_code)

    @classmethod
    def register_pair(cls, pair_code: str, config: Dict[str, Any]) -> PairQuantityConverter:
        """注册品种转换器"""
        conv = PairQuantityConverter(config)
        cls._pair_converters[pair_code] = conv
        return conv

    @classmethod
    async def load_from_db(cls):
        """从数据库加载所有对冲产品对的换算配置"""
        try:
            from app.core.database import AsyncSessionLocal
            from sqlalchemy import text
            async with AsyncSessionLocal() as session:
                r = await session.execute(text("""
                    SELECT hp.pair_code, hp.conversion_factor,
                           sa.qty_precision AS qty_precision_a, sa.qty_step AS qty_step_a,
                           sa.min_qty AS min_qty_a, sa.qty_unit AS qty_unit_a,
                           sb.qty_precision AS qty_precision_b, sb.qty_step AS qty_step_b,
                           sb.min_qty AS min_qty_b, sb.qty_unit AS qty_unit_b
                    FROM hedging_pairs hp
                    JOIN platform_symbols sa ON hp.symbol_a_id = sa.id
                    JOIN platform_symbols sb ON hp.symbol_b_id = sb.id
                    WHERE hp.is_active = TRUE
                """))
                rows = r.mappings().all()
                for row in rows:
                    cls.register_pair(row['pair_code'], dict(row))
                # 用 XAU 配置更新默认值（向后兼容）
                xau = cls._pair_converters.get('XAU')
                if xau:
                    cls.XAU_PER_LOT = xau.factor
                    cls.MIN_LOT = xau.min_b
                    cls.MIN_XAU = xau.min_a
                return len(rows)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to load pair converters from DB, using defaults: {e}")
            return 0

    # ── 向后兼容接口（黄金） ──────────────────────────────────────
    @classmethod
    def xau_to_lot(cls, xau: Union[int, float]) -> float:
        if xau is None or xau == 0:
            return 0.0
        return round(xau / cls.XAU_PER_LOT, cls.LOT_PRECISION)

    @classmethod
    def lot_to_xau(cls, lot: Union[int, float]) -> int:
        if lot is None or lot == 0:
            return 0
        return round(lot * cls.XAU_PER_LOT)

    @classmethod
    def format_xau(cls, xau: Union[int, float]) -> str:
        if xau is None:
            return "0 XAU"
        return f"{int(xau)} XAU"

    @classmethod
    def format_lot(cls, lot: Union[int, float]) -> str:
        if lot is None:
            return "0.00 Lot"
        return f"{lot:.{cls.LOT_PRECISION}f} Lot"

    @classmethod
    def format_xau_with_lot(cls, xau: Union[int, float]) -> str:
        if xau is None or xau == 0:
            return "0 XAU ≈ 0.00 Lot"
        lot = cls.xau_to_lot(xau)
        return f"{int(xau)} XAU ≈ {lot:.{cls.LOT_PRECISION}f} Lot"

    @classmethod
    def validate_xau(cls, xau: Union[int, float]) -> tuple:
        if xau is None or xau <= 0:
            return False, "数量无效"
        if xau < cls.MIN_XAU:
            return False, f"最小下单量为 {cls.MIN_XAU} XAU"
        return True, ""

    @classmethod
    def validate_lot(cls, lot: Union[int, float]) -> tuple:
        if lot is None or lot <= 0:
            return False, "数量无效"
        if lot < cls.MIN_LOT:
            return False, f"最小下单量为 {cls.MIN_LOT} Lot"
        return True, ""

    @classmethod
    def convert_for_platform(cls, quantity: Union[int, float], platform: str) -> float:
        if platform.lower() == 'bybit':
            return cls.xau_to_lot(quantity)
        return float(quantity)


# 全局实例
quantity_converter = QuantityConverter()
