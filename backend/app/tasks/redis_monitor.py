"""Background task for monitoring and restarting Redis/Memurai service"""
import asyncio
import subprocess
import logging
from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)


class RedisMonitor:
    """Monitor Redis/Memurai service and restart if needed"""

    def __init__(self):
        self.running = False
        self.task = None
        self.check_interval = 30  # Check every 30 seconds
        self.is_healthy = False
        self.last_error = None

    async def start(self):
        """Start the Redis monitoring task"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._monitor_loop())
        print("Redis monitor started successfully")
        logger.info("Redis monitor started")

    async def stop(self):
        """Stop the Redis monitoring task"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Redis monitor stopped")

    async def _check_redis_health(self) -> bool:
        """Check if Redis is healthy"""
        try:
            # Try to set and get a test key
            test_key = "_redis_health_check"
            await redis_client.set(test_key, "ok", ex=10)
            result = await redis_client.get(test_key)
            return result is not None
        except Exception as e:
            logger.warning(f"Redis health check failed: {str(e)}")
            return False

    def _restart_memurai_service(self) -> bool:
        """Restart Memurai service using Windows net command"""
        try:
            # Stop service (ignore errors if already stopped)
            subprocess.run(
                ["net", "stop", "Memurai"],
                capture_output=True,
                timeout=10
            )

            # Wait a moment
            import time
            time.sleep(2)

            # Start service
            result = subprocess.run(
                ["net", "start", "Memurai"],
                capture_output=True,
                timeout=10,
                text=True
            )

            if result.returncode == 0:
                logger.info("Memurai service restarted successfully")
                return True
            else:
                logger.error(f"Failed to restart Memurai: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Error restarting Memurai service: {str(e)}")
            return False

    async def _monitor_loop(self):
        """Main monitoring loop"""
        logger.info("Redis monitor loop started")

        while self.running:
            try:
                # Check Redis health
                is_healthy = await self._check_redis_health()

                if is_healthy:
                    if not self.is_healthy:
                        logger.info("Redis is now healthy")
                    self.is_healthy = True
                    self.last_error = None
                else:
                    logger.warning("Redis is unhealthy, attempting to restart Memurai")
                    self.is_healthy = False
                    self.last_error = "Redis connection failed"

                    # Try to restart Memurai
                    restart_success = self._restart_memurai_service()

                    if restart_success:
                        # Wait a bit for service to fully start
                        await asyncio.sleep(3)

                        # Reconnect Redis client
                        try:
                            await redis_client.disconnect()
                            await redis_client.connect()
                            logger.info("Redis client reconnected after Memurai restart")
                        except Exception as e:
                            logger.error(f"Failed to reconnect Redis client: {str(e)}")
                    else:
                        logger.error("Failed to restart Memurai service")

                # Wait for next check
                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Error in Redis monitor loop: {str(e)}")
                self.is_healthy = False
                self.last_error = str(e)
                await asyncio.sleep(self.check_interval)

    def get_status(self) -> dict:
        """Get current Redis status"""
        return {
            "healthy": self.is_healthy,
            "last_error": self.last_error,
            "service": "Memurai"
        }


# Global monitor instance
redis_monitor = RedisMonitor()
