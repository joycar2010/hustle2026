import os, sys
sys.path.insert(0, '.')
from bot import config
from bot.sports_main import SportsPaperService

def build_data_source():
    api_key = os.environ.get('ODDS_API_KEY', '').strip()
    if not api_key:
        return None
    try:
        from bot.feeds.odds_consensus import OddsConsensusSource
        return OddsConsensusSource(api_key=api_key)
    except Exception as e:
        print(f'odds source init failed: {e}')
        return None

cfg = config.load()
source = build_data_source()
print(f'data_source: {source.name if source else "market_implied"}')
service = SportsPaperService(cfg, data_source=source)

while True:
    import time
    result = service.run_once()
    print(f'{result["status"]} markets={len(result["markets"])} decisions={len(result["decisions"])} orders={len(result["orders"])}')
    time.sleep(300)
