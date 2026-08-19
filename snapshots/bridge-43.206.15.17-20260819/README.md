# MT5/MT4 bridge snapshot - 2026-08-19

Source host: EC2AMAZ-2SH9D10 (43.206.15.17)
Scope: bridge source, MT4 EA/source, deployment candidates/templates, watchdog/supervisor scripts, current scheduled-task XML, and the independent `C:\MT5Agent` management Agent source/config shape.

The QHCELL terminal template trees were reduced to source/config extensions (MQ4/MQ5/MQH/EX4/EX5/SET/TPL and related text); terminal runtimes and market-data caches are excluded.
Excluded from this public snapshot: real .env/cell.env/slots.json, credentials and login state, terminal installations, virtual environments, logs, ledger/database/WAL files, caches, and transient backups. The `C:\MT5Agent` JSON files are redacted templates, not production configuration.
No production service was stopped and no trading order was sent while collecting this snapshot.
