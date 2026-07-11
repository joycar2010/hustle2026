import argparse
from engine.main import run

parser = argparse.ArgumentParser(description='CEX Arbitrage Engine')
parser.add_argument('--shard-id', type=int, default=None, 
                    help='Run only this shard (for multi-process deployment)')
args = parser.parse_args()

run(shard_id=args.shard_id)
