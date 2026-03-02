"""
统一的数量单位转换工具类

单位定义：
- Binance: XAU (盎司) - 1 XAU = 1 合约单位
- Bybit MT5: Lot (手) - 1 Lot = 100 XAU

转换公式：
- Bybit Lot = Binance XAU ÷ 100
- Binance XAU = Bybit Lot × 100
"""

from typing import Union


class QuantityConverter:
    """数量单位转换器"""

    # 转换常量
    XAU_PER_LOT = 100.0  # 1 Lot = 100 XAU
    LOT_PRECISION = 2  # Lot精度：2位小数
    XAU_PRECISION = 0  # XAU精度：整数
    MIN_LOT = 0.01  # Bybit最小下单量：0.01 Lot
    MIN_XAU = 1  # Binance最小下单量：1 XAU

    @classmethod
    def xau_to_lot(cls, xau: Union[int, float]) -> float:
        """
        XAU转换为Lot

        Args:
            xau: XAU数量

        Returns:
            Lot数量（保留2位小数）
        """
        if xau is None or xau == 0:
            return 0.0
        return round(xau / cls.XAU_PER_LOT, cls.LOT_PRECISION)

    @classmethod
    def lot_to_xau(cls, lot: Union[int, float]) -> int:
        """
        Lot转换为XAU

        Args:
            lot: Lot数量

        Returns:
            XAU数量（整数）
        """
        if lot is None or lot == 0:
            return 0
        return round(lot * cls.XAU_PER_LOT)

    @classmethod
    def format_xau(cls, xau: Union[int, float]) -> str:
        """
        格式化XAU显示（带单位）

        Args:
            xau: XAU数量

        Returns:
            格式化后的字符串，例如："5 XAU"
        """
        if xau is None:
            return "0 XAU"
        return f"{int(xau)} XAU"

    @classmethod
    def format_lot(cls, lot: Union[int, float]) -> str:
        """
        格式化Lot显示（带单位）

        Args:
            lot: Lot数量

        Returns:
            格式化后的字符串，例如："0.05 Lot"
        """
        if lot is None:
            return "0.00 Lot"
        return f"{lot:.{cls.LOT_PRECISION}f} Lot"

    @classmethod
    def format_xau_with_lot(cls, xau: Union[int, float]) -> str:
        """
        格式化XAU并显示对应的Lot

        Args:
            xau: XAU数量

        Returns:
            格式化后的字符串，例如："5 XAU ≈ 0.05 Lot"
        """
        if xau is None or xau == 0:
            return "0 XAU ≈ 0.00 Lot"
        lot = cls.xau_to_lot(xau)
        return f"{int(xau)} XAU ≈ {lot:.{cls.LOT_PRECISION}f} Lot"

    @classmethod
    def validate_xau(cls, xau: Union[int, float]) -> tuple[bool, str]:
        """
        验证XAU数量是否有效

        Args:
            xau: XAU数量

        Returns:
            (是否有效, 错误信息)
        """
        if xau is None or xau <= 0:
            return False, "数量无效"

        if xau < cls.MIN_XAU:
            return False, f"最小下单量为 {cls.MIN_XAU} XAU"

        return True, ""

    @classmethod
    def validate_lot(cls, lot: Union[int, float]) -> tuple[bool, str]:
        """
        验证Lot数量是否有效

        Args:
            lot: Lot数量

        Returns:
            (是否有效, 错误信息)
        """
        if lot is None or lot <= 0:
            return False, "数量无效"

        if lot < cls.MIN_LOT:
            return False, f"最小下单量为 {cls.MIN_LOT} Lot"

        return True, ""

    @classmethod
    def convert_for_platform(cls, quantity: Union[int, float], platform: str) -> float:
        """
        根据平台转换数量

        Args:
            quantity: 输入数量（XAU）
            platform: 平台名称 ('binance' 或 'bybit')

        Returns:
            转换后的数量
        """
        if platform.lower() == 'bybit':
            return cls.xau_to_lot(quantity)
        return float(quantity)  # Binance使用XAU，不需要转换


# 创建全局实例
quantity_converter = QuantityConverter()
