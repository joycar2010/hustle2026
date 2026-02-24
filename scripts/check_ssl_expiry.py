"""SSL证书过期检查脚本"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import async_session_maker
from app.models.ssl_certificate import SSLCertificate
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def check_ssl_certificates():
    """检查SSL证书过期状态"""
    async with async_session_maker() as session:
        try:
            logger.info("开始检查SSL证书过期状态...")

            # 获取所有证书
            result = await session.execute(select(SSLCertificate))
            certificates = result.scalars().all()

            if not certificates:
                logger.info("没有找到SSL证书")
                return

            now = datetime.utcnow()
            expired_certs = []
            expiring_soon_certs = []
            valid_certs = []

            for cert in certificates:
                # 计算距离过期天数
                days_before_expiry = (cert.expires_at - now).days

                # 更新证书状态
                old_status = cert.status
                old_days = cert.days_before_expiry

                cert.days_before_expiry = max(0, days_before_expiry)
                cert.last_check_at = now

                if days_before_expiry <= 0:
                    cert.status = "expired"
                    expired_certs.append(cert)
                elif days_before_expiry <= 30:
                    cert.status = "expiring_soon"
                    expiring_soon_certs.append(cert)
                else:
                    if cert.is_deployed:
                        cert.status = "active"
                    else:
                        cert.status = "inactive"
                    valid_certs.append(cert)

                # 记录状态变化
                if old_status != cert.status:
                    logger.warning(
                        f"证书状态变化: {cert.domain_name} "
                        f"{old_status} -> {cert.status} "
                        f"(剩余 {days_before_expiry} 天)"
                    )

            await session.commit()

            # 输出检查结果
            logger.info(f"\n{'='*60}")
            logger.info(f"SSL证书检查完成")
            logger.info(f"{'='*60}")
            logger.info(f"总计: {len(certificates)} 个证书")
            logger.info(f"  ✓ 有效: {len(valid_certs)} 个")
            logger.info(f"  ⚠ 即将过期 (30天内): {len(expiring_soon_certs)} 个")
            logger.info(f"  ✗ 已过期: {len(expired_certs)} 个")

            # 详细列出即将过期的证书
            if expiring_soon_certs:
                logger.warning(f"\n即将过期的证书:")
                for cert in expiring_soon_certs:
                    logger.warning(
                        f"  - {cert.domain_name}: "
                        f"剩余 {cert.days_before_expiry} 天 "
                        f"(过期时间: {cert.expires_at.strftime('%Y-%m-%d')})"
                    )

            # 详细列出已过期的证书
            if expired_certs:
                logger.error(f"\n已过期的证书:")
                for cert in expired_certs:
                    logger.error(
                        f"  - {cert.domain_name}: "
                        f"已过期 {abs(cert.days_before_expiry)} 天 "
                        f"(过期时间: {cert.expires_at.strftime('%Y-%m-%d')})"
                    )

            # 发送告警（可以集成邮件、钉钉、企业微信等）
            if expired_certs or expiring_soon_certs:
                logger.warning("\n⚠️  需要关注的证书:")
                for cert in expired_certs + expiring_soon_certs:
                    logger.warning(
                        f"  域名: {cert.domain_name}, "
                        f"状态: {cert.status}, "
                        f"剩余天数: {cert.days_before_expiry}, "
                        f"是否部署: {'是' if cert.is_deployed else '否'}"
                    )

                # TODO: 发送告警通知
                # send_alert_notification(expired_certs, expiring_soon_certs)

        except Exception as e:
            logger.error(f"检查SSL证书失败: {e}")
            raise


async def send_alert_notification(expired_certs, expiring_soon_certs):
    """发送告警通知（示例）"""
    # 这里可以集成邮件、钉钉、企业微信等通知方式
    pass


if __name__ == "__main__":
    asyncio.run(check_ssl_certificates())
