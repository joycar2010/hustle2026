#!/usr/bin/env python3
import time
import psycopg2
from prometheus_client import start_http_server, Gauge

DB_DSN = "postgresql://exporter:exporter_pass@127.0.0.1:5432/cex_trading"

# Metrics
shard_heartbeat_age = Gauge('coin_shard_heartbeat_age_seconds', 'Shard heartbeat age', ['scope'])
shard_active_positions = Gauge('coin_shard_active_positions', 'Active positions per shard', ['scope'])
worker_heartbeat_age = Gauge('coin_worker_heartbeat_age_seconds', 'Worker heartbeat age', ['worker'])

def collect():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    # Shard heartbeat
    cur.execute("""
        SELECT scope,
               EXTRACT(EPOCH FROM (now() - last_heartbeat)) AS age,
               COALESCE(active_positions, 0) AS positions
        FROM engine_state
        WHERE scope LIKE 'shard:%'
    """)
    for row in cur.fetchall():
        scope, age, positions = row
        shard_heartbeat_age.labels(scope=scope).set(age or 999)
        shard_active_positions.labels(scope=scope).set(positions)

    # Worker heartbeat
    cur.execute("""
        SELECT scope,
               EXTRACT(EPOCH FROM (now() - last_heartbeat)) AS age
        FROM engine_state
        WHERE scope LIKE 'sub:%'
    """)
    for row in cur.fetchall():
        scope, age = row
        worker_heartbeat_age.labels(worker=scope).set(age or 999)

    cur.close()
    conn.close()

if __name__ == '__main__':
    start_http_server(9188)
    print("Engine exporter started on :9188")
    while True:
        try:
            collect()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(10)
