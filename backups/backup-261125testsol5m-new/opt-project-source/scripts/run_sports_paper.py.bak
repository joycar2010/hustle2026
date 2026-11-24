"""Long running sports paper worker for the isolated polyauto instance."""
import time
from bot.config import load
from bot.sports_main import SportsPaperService

def main() -> None:
    cfg = load()
    service = SportsPaperService(cfg)
    interval = max(float(getattr(cfg, "sports_scan_interval_sec", 300)), 30.0)
    while True:
        try:
            snapshot = service.run_once()
            print(f"sports paper cycle status={snapshot.get('status')} markets={len(snapshot.get('markets', []))}", flush=True)
        except Exception as exc:
            print(f"sports paper cycle failed: {exc}", flush=True)
        time.sleep(interval)

if __name__ == "__main__":
    main()
