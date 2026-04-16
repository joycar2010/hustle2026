"""Background task for subscribing to timing configuration updates"""
import asyncio
import json
import logging
from app.core.redis_client import redis_client
from app.services.timing_config_service import TimingConfigService

logger = logging.getLogger(__name__)


class TimingConfigSubscriber:
    """Background task for subscribing to timing config reload events"""

    def __init__(self):
        self.running = False
        self.task = None
        self.pubsub = None
        self.reload_count = 0
        self.last_reload_time = None
        # Store active executors that need config updates
        self.registered_executors = []

    def register_executor(self, executor):
        """Register an executor to receive config updates"""
        if executor not in self.registered_executors:
            self.registered_executors.append(executor)
            logger.info(f"Registered executor for config updates: {type(executor).__name__}")

    def unregister_executor(self, executor):
        """Unregister an executor from config updates"""
        if executor in self.registered_executors:
            self.registered_executors.remove(executor)
            logger.info(f"Unregistered executor: {type(executor).__name__}")

    async def start(self):
        """Start the timing config subscriber task"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._subscribe_loop())
        logger.info("Timing config subscriber started")

    async def stop(self):
        """Stop the timing config subscriber task"""
        self.running = False
        if self.pubsub:
            await self.pubsub.unsubscribe('timing_config:reload')
            await self.pubsub.close()
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Timing config subscriber stopped")

    async def _subscribe_loop(self):
        """Main subscription loop"""
        while self.running:
            try:
                if not redis_client.client:
                    logger.warning("Redis client not available, retrying in 10s")
                    await asyncio.sleep(10)
                    continue

                # Create pubsub instance
                self.pubsub = redis_client.client.pubsub()
                await self.pubsub.subscribe('timing_config:reload')
                logger.info("Subscribed to timing_config:reload channel")

                # Listen for messages
                async for message in self.pubsub.listen():
                    if not self.running:
                        break

                    if message['type'] == 'message':
                        try:
                            # Parse reload notification
                            data = json.loads(message['data'])
                            config_level = data.get('config_level')
                            strategy_type = data.get('strategy_type')
                            timestamp = data.get('timestamp')

                            logger.info(
                                f"Received config reload notification: "
                                f"level={config_level}, type={strategy_type}, time={timestamp}"
                            )

                            # Reload configs for all registered executors
                            await self._reload_executor_configs(config_level, strategy_type)

                            self.reload_count += 1
                            self.last_reload_time = timestamp

                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse reload message: {e}")
                        except Exception as e:
                            logger.error(f"Error processing reload message: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in timing config subscriber: {e}")
                await asyncio.sleep(5)  # Retry after 5 seconds

    async def _reload_executor_configs(self, config_level: str, strategy_type: str):
        """Reload configurations for all registered executors"""
        from app.core.database import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as db:
                for executor in self.registered_executors:
                    try:
                        # Determine which strategy type this executor needs
                        executor_strategy_type = getattr(executor, 'strategy_type', None)

                        # Only reload if this config affects this executor
                        if config_level == 'global' or \
                           (config_level == 'strategy_type' and executor_strategy_type == strategy_type):

                            # Fetch fresh config from database
                            timing_config = await TimingConfigService.get_effective_config(
                                db=db,
                                strategy_type=executor_strategy_type
                            )

                            # Update executor's timing parameters
                            if hasattr(executor, 'update_timing_config'):
                                await executor.update_timing_config(timing_config)
                                logger.info(f"Updated config for executor: {type(executor).__name__}")
                            else:
                                # Fallback: directly update attributes
                                for key, value in timing_config.items():
                                    if hasattr(executor, key):
                                        setattr(executor, key, value)
                                logger.info(f"Updated config attributes for executor: {type(executor).__name__}")

                    except Exception as e:
                        logger.error(f"Failed to reload config for executor {type(executor).__name__}: {e}")

        except Exception as e:
            logger.error(f"Failed to reload executor configs: {e}")


# Global subscriber instance
timing_config_subscriber = TimingConfigSubscriber()
