"""Test RiskMetricsStreamer directly"""
import asyncio
import logging

logging.basicConfig(level=logging.INFO)

from app.tasks.broadcast_tasks import risk_metrics_streamer

async def test():
    print("Starting risk_metrics_streamer...")
    await risk_metrics_streamer.start()
    print(f"Streamer running: {risk_metrics_streamer.running}")
    print("Waiting 35 seconds...")
    await asyncio.sleep(35)
    print("Stopping...")
    await risk_metrics_streamer.stop()

if __name__ == "__main__":
    asyncio.run(test())
