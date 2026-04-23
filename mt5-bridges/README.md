# MT5 FastAPI bridges (7 instances + template)

Live source from MT5 host `172.31.14.113` (`D:\hustle-mt5-*\app\main.py`).
Each bridge wraps MetaTrader5 Python API behind HTTP so the gateway can
read ticks / positions / place orders over the LAN.

## Instances + broker mapping
| Service name              | Port | Broker class | Account type |
|---------------------------|------|--------------|--------------|
| hustle-mt5-mt5-by01       | 8001 | Bybit MT5    | trade        |
| hustle-mt5-mt5-by02       | 8002 | Bybit MT5    | trade        |
| hustle-mt5-mt5-by03       | 8003 | Bybit MT5    | trade        |
| hustle-mt5-mt5-bysys      | 8886 | Bybit MT5    | system       |
| hustle-mt5-mt5-ic01       | 8021 | IC Markets   | trade        |
| hustle-mt5-mt5-ic02       | 8022 | IC Markets   | trade        |
| hustle-mt5-mt5-icsys      | 8888 | IC Markets   | system       |
| hustle-mt5-template       |  —   | template     | (new builds) |

(Ports from nssm parameters; see D:\<instance>\nssm config on the host.)

## File structure per instance
- `app/main.py` — FastAPI app (identical inside a class: 4 instances share md5
  `6259d4f1d022e0357f6c655c21c9db7e`, 3 share `1e8174f3840b32daaea136c7b0404b90`).

venv/ and logs/ are excluded.

## Sync workflow
```powershell
# on MT5 host
for inst in by01 by02 by03 bysys ic01 ic02 icsys; do
  scp -i d:/HustleNew.pem D:/hustle-mt5-mt5-$inst/app/main.py ubuntu@172.31.2.22:/data/hustle2026/mt5-bridges/hustle-mt5-mt5-$inst/app/main.py
done
```
