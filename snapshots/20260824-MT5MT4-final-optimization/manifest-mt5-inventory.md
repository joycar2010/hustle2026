# MT5 bridge host inventory (read-only, 2026-08-24)

Host: `EC2AMAZ-2SH9D10` / `43.206.15.17`, accessed as `Administrator` with `mt5-bridge-key.pem`. No remote files were modified.

## Running bridge/API processes

- `C:\MT5Agent\venv\Scripts\python.exe C:\MT5Agent\main_v3.py` (also a spawned `C:\Python311\python.exe` copy), listener 8765.
- `D:\QHMT5\runtime\releases\v1\venv-bybit\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001` (worker `C:\Python311`, listener 8001).
- `D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8888` (listener 8888), port 8021, and cell port 8600.
- Additional IC workers on 8061 and 8063; Bybit on 8886. MT4 agent workers from `D:\MT4LAB\agent\venv\Scripts\python.exe` on 8041/8042/8065/8066/8067/8068.
- Listening bridge-related ports: `8001, 8021, 8041, 8042, 8061, 8063, 8065-8068, 8600, 8765, 8886, 8888` (all `0.0.0.0`).

## Scheduled tasks / deployment entrypoints

- `\\MT5Agent-NewBridge` running: `C:\MT5Agent\venv\Scripts\python.exe C:\MT5Agent\main_v3.py`.
- `\\QHMT5-Guardian` ready: `powershell ... -File D:\QHMT5\guardian.ps1`.
- `\\QHMT5-Launch-Interactive` ready: `powershell ... -File D:\QHMT5\supervisor.ps1`; `\\QHMT5-LaunchBridges` disabled, runs `D:\QHMT5\launch_bridges.ps1`.
- `\\QHCELL-Agent` ready: `D:\QHCELL\run_cell.ps1`; `\\QHCELL-t-m1`..`m4` running `D:\QHCELL\pool\mN\terminal\terminal.exe /portable D:\QHCELL\pool\mN\start.ini`.
- `\\MT4LAB-Agent-exness` and `\\MT4LAB-Agent-ic` running `D:\MT4LAB\agent\run_agent.ps1 -Instance exness|ic -Portable`; `\\MT4LAB-Startup` runs `D:\MT4LAB\launch_mt4lab_portable.ps1`; watchdog task runs `D:\MT4LAB\agent\mt4_agent_watchdog.ps1`.
- XML task snapshots available under `D:\QHCELL\backups\QHCELL-*.before-system.xml` and `QH-MT4-Agent-Watchdog.before-disable-20260811.xml`; MT4 task snapshots under `D:\MT4LAB\task_backup_20260722_cutover\`.

## Current MT5 bridge source/runtime files

The active IC runtime is duplicated in each instance (`ic01`, `icsys`, `icsysnew`) and in `runtime\releases\v1\ic`; hashes are identical:

- `D:\QHMT5\runtime\releases\v1\ic\app\main.py` 171,453 bytes, modified 2026-08-24 06:47:14, SHA256 `8B442F24AB5101FB4FC1FB702F76E056BC1EF38E5532A27968D00E592CEC7A5F`.
- `D:\QHMT5\runtime\releases\v1\ic\app\runtime.py` 111,063 bytes, modified 2026-08-21 22:26:46, SHA256 `3E9A4DBB83E84E0D0667678C5E42E27FA1C7FCCE7272DAA8455A9660F4891EC5`.
- `D:\QHMT5\runtime\releases\v1\ic\app\__init__.py` 38 bytes; `requirements.txt` 109 bytes; `test_bridge_deps.py` 950 bytes; `idempotency.db` 12,288 bytes.
- `D:\QHMT5\runtime\releases\v1\bybit\app\main.py` 34,998 bytes, SHA256 `46E812E11F54C3D97FFED73BE2B4C5CC7F5EFBE751F00BC2F1B20BC297CE349D`; requirements 109 bytes and idempotency DB.
- Instance copies: `D:\QHMT5\instances\ic01\app\{main.py,runtime.py,__init__.py}`, `icsys\app\...`, `icsysnew\app\...`; five `.env` files (`ic01`, `icsys`, `icsysnew`, `by01`, `bysys`) contain credentials and must be treated as secrets.
- Bybit instance copies: `D:\QHMT5\instances\by01\app\main.py`, `bysys\app\main.py`; `seed_tmp.py` files in each instance.
- Root launch/config scripts: `D:\QHMT5\supervisor.ps1` (3,263 bytes, SHA256 `EFC8DB43AD695A51CBCA064484A8CB02B9151A04B5E1FF38B8BFBE5EDF7DA6EE`), `guardian.ps1` (413), `launch_bridges.ps1` (949), `seed_login.ps1` (1,394), `ws_probe_mt5.py` (562), plus dated `.bak_*`/candidate supervisor variants.
- `C:\MT5Agent\main_v3.py` 100,801 bytes SHA256 `6E3C3076537F832EBEC3861B69352EAED0795A9A06C9FF12464C9FAFED952EF2`; `config.json` 1,335 bytes SHA256 `B0E74CE70DA94AB1814C7023C4D29EA93EA3FE252F0266F94E574CEE48691BCE`; `instances.json` 2,094 bytes SHA256 `94939110E8D36D3D747C3FA1FDEFD3722E02CB30D4A5827CF109113A74902E5B`; requirements 63 bytes. Python runtime is 3.11.9.

## Deployment templates/releases

Include all source and manifests in `D:\QHMT5\deploy\` and `D:\QHMT5\runtime\staged\` (do not delete existing branch files). Current deploy release directories and approximate source-only sizes:

- `release_mt5_admission_capability_20260821_3` (5 files, 318,787 bytes; latest), `release_mt5_admission_20260821_2` (316,194), `mt5-execution-quote-snapshot-20260821.1-retry2` (9, 352,353), `...-deploy` (352,220), `mt5-execution-probe-memory-20260819.6-deploy` (319,821), `...20260818.5` (284,142), `mt5-trade-wake-priority-20260817.4` (276,675), `mt5-tick-isolation-20260817.3` (258,209), both `mt5-single-owner-admission-20260817.2-*` (246,986 / 252,809), and `mt5-process-admission-20260817.1` (214,711).
- Each release contains `app/main.py`, `app/runtime.py` where applicable, `cell.py`, `deploy.ps1`, `release-manifest.json`, and validation/maintenance scripts. Preserve `deployment-token.txt` only in an encrypted secret archive.
- Staged source snapshots under `D:\QHMT5\runtime\staged\`: `hedge-pro-mt5-quiet-refresh-20260811.35`, `positions-authoritative-20260811.34`, `account-cache-20260811`, `latency-20260811`, `burst-cache-20260810`, `priority[-queue]-20260810`, `refresh-20260810`, `order-send-{closure,keyword}-20260810`, `v3-20260731`, `batch-20260731` (each ~54–181 KB source).
- Existing dated backup snapshots in `D:\QHMT5\backups\` include `qh-bridge-window-20260824T063920Z`, `mt5-execution-quote-snapshot-20260821.*`, `mt5-execution-probe-memory-20260818/19.*`, and prior admission/tick/wake releases. Retain manifests, `*.before` source, deployment reports, and DB files; omit only redundant runtime caches/logs if the Git snapshot is size constrained.

## QHCELL/MT4 cell bridge (used by the same bridge host)

- Runtime controller: `D:\QHCELL\cell.py` 25,921 bytes SHA256 `171BCF175F8DE9F1D50F5891C809A4F2D9A7881B5B0E8485EE51C36EF7905935`; `run_cell.ps1` 608 bytes SHA256 `BFFCC209801C307BB49ABFB50A6F8D3C5382FFC6DE3C5D768F013F4E6E161E39`; `slots.json` 2,770 bytes SHA256 `65369E336BBE4C6D4D40ED27894D3A7B6C481644B1404FA19B99125D6DE09B2D`; `cell.env` is secret.
- Active EA source/binaries in each MT4 cell: `D:\QHCELL\pool\m1..m4\terminal\MQL4\Experts\QHBridge.mq4` (41,534 bytes, SHA256 `C6468A6F49296011B82AFC11AC08D8CFE2801C2B9D3A851B434F6E4CC9BC0B01`) and `QHBridge.ex4` (per-cell 80,388–81,010 bytes; m1 SHA256 `89085EA19DD1B41C922710C8D237EF87CBA9347E045FBD8653AF75D1938FA284`). Each has `stage_qhbridge_v122_20260810\` copies. Include `D:\QHCELL\templates\mt4-exness` and `templates\mt4-ic` bridge/template configs.
- Cell execution DBs under `D:\QHCELL\execution\` (two active SQLite DBs, ~3.38 MB and ~1.33 MB WAL; include DB + `-wal`/`-shm` or make a consistent SQLite backup). `D:\QHCELL\pool\m1..m4` contain live dispatch/results/state JSON; snapshot only a bounded state sample or archive separately, not thousands of transient dispatch files.
- Task XML backups: `D:\QHCELL\backups\QHCELL-Agent.before-system.xml`, `QHCELL-t-m1..m4.before-system.xml`, `QH-MT4-Agent-Watchdog.before-disable-20260811.xml`.

## MT4 agent files on bridge host

- Active agent source: `D:\MT4LAB\agent\main.py` 50,585 bytes SHA256 `DBAB22D3BAA16B27A3BF58AC787A57B289415FBCB0EC8A8B49FD49734E863E4F`, `filebridge.py` 13,016 bytes SHA256 `1FC24FD132A2B680C772E0E4A1F04B2D110B8B5FE26FBCEDEDEE264D06BCB27A`, `ledger.py` 7,038 bytes SHA256 `7A4EBBEFB8B3A9C168805F9DE6DC90F363A96B696D7C564A88354D7632BB2511`, `run_agent.ps1` 1,672 bytes, watchdog/deploy/diagnostic scripts.
- Active EA: `D:\MT4LAB\agent\QHBridge.mq4` 25,793 bytes SHA256 `6F94B81CB34802B421732DAECFA59E7E3964F254179E7B1883F39E58FEF9816A`, `QHBridge.ex4` 61,136 bytes SHA256 `3C209087E781D3EE8BD5BA0BA4A44E0B75326D50406058E20630CEFF1659A239`.
- Include `D:\MT4LAB\build\` (QHBridge 1.11–1.14 sources/build logs and no123 subsecond EA) and `D:\MT4LAB\releases\no123-subsecond-20260727\` (agent + exness/ic EA/source). Include ledger DBs only as a consistent backup: live `ledger_qhmt4-{exness,ic,unknown}.db*`, `ledger_qhcell-{m1..m4,jj456-main,jj456-hedge,lei789-main,lei789-hedge}.db*`.

## Large files / GitHub handling

- `D:\QHMT5` totals ~4.37 GB (14,244 files): `terminals` ~1.97 GB, `instances` ~1.73 GB (mostly live DB/log/runtime), `backups` ~391 MB, `runtime` ~235 MB. `C:\MT5Agent` ~128 MB (venv ~49 MB, logs ~79 MB). `D:\MT4LAB` ~1.20 GB (agent ~968 MB; terminals ~161 MB). QHCELL pool terminals are ~67 MB each (s1–s4 ~272–299 MB each).
- Individual >100 MB binaries: MetaTrader `terminal64.exe` (109–132 MB) and `MetaEditor64.exe` (109–117 MB) under `D:\QHMT5\terminals\*`/`D:\QHCELL\pool\s*`. GitHub rejects files >100 MiB; do not add these directly. Store SHA256/metadata and use Git LFS or an external/encrypted artifact archive. Python source and bridge binaries are below 100 MiB.
- Exclude transient `logs`, `history`, `cache`, `bases`, `MQL*\\Files\\qhbridge\\dispatch|results`, virtualenv `venv-*`, and MetaTrader example indicators from the Git source snapshot unless explicitly archived. Preserve every `dist`/EA/source/deployment/template directory and manifests.
- Avoid recursive traversal of `C:\Users\Administrator\Application Data`, `Documents and Settings`, `Local Settings`, and similar reparse/junction paths. Restrict copy roots to the explicit paths above; `Get-ChildItem` showed no reparse points at selected root levels, but user-profile junctions are present.

