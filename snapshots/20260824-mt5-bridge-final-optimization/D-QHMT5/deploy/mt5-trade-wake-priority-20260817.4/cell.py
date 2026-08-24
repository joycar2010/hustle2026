# D:\QHCELL\cell.py — QH 区域自治 Cell v2(暖池秒供: MT5 + MT4 | 实测路由指标 | 本地看门狗)
# MT5 槽位: 写 .env → 起桥(桥进程合并式 initialize 自登录) → 等 /health mt5:true。
# MT4 槽位: 写 MT4 原生启动配置 start.ini(裸键值, 作命令行参数; ⚠不是 MT5 的 /config 格式)
#           → 起终端(/portable, 自登录) + 起文件桥 Agent(D:\MT4LAB\agent) → 等 agent /health
#           → 核验 /mt5/account/info login 匹配(EA 状态文件按槽位清洗, 防陈旧状态假阳性)。
# 释放 = 杀进程 + 抹凭证(.env / start.ini)+ 清 EA 状态 → 槽位回暖。
# 自治: 看门狗 30s 巡检, 3 连挂+180s 冷却本地自愈; 启动收养(活着 adopt / 死了按留存凭证 revive)。
# 会话: 必须跑在交互会话(MT4/MT5 终端 GUI 隔离铁律), 由 QHCELL-Agent 交互计划任务拉起。
# MT5 uses one child process as the sole native read/write IPC owner.
import hashlib, json, os, shutil, subprocess, threading, time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

CELL_NAME = "tokyo-bridge-1"
MT5_BRIDGE_BUILD_ID = "mt5-trade-wake-priority-20260817.4"
BASE = r"D:\QHCELL"
EXECUTION_ROOT = os.path.join(BASE, "execution")
VENV_PY = r"D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe"
MT4_AGENT_DIR = r"D:\MT4LAB\agent"
MT4_AGENT_PY = r"D:\MT4LAB\agent\venv\Scripts\python.exe"
SLOTS_FILE = os.path.join(BASE, "slots.json")
LOG_FILE = os.path.join(BASE, "logs", "cell.log")
API_KEY = ""
try:
    for _ln in open(os.path.join(BASE, "cell.env"), encoding="utf-8"):
        if _ln.startswith("API_KEY="): API_KEY = _ln.split("=", 1)[1].strip()
except Exception: pass

DEFAULT_SLOTS = [
    {"slot": "s1", "family": "ic",         "platform": "MT5", "port": 8061, "state": "warm", "alloc": None, "pid": None},
    {"slot": "s2", "family": "ic",         "platform": "MT5", "port": 8062, "state": "warm", "alloc": None, "pid": None},
    {"slot": "s3", "family": "exness",     "platform": "MT5", "port": 8063, "state": "warm", "alloc": None, "pid": None},
    {"slot": "s4", "family": "exness",     "platform": "MT5", "port": 8064, "state": "warm", "alloc": None, "pid": None},
    {"slot": "m1", "family": "mt4-ic",     "platform": "MT4", "port": 8065, "state": "warm", "alloc": None, "pid": None},
    {"slot": "m2", "family": "mt4-exness", "platform": "MT4", "port": 8066, "state": "warm", "alloc": None, "pid": None},
    {"slot": "m3", "family": "mt4-ic",     "platform": "MT4", "port": 8067, "state": "warm", "alloc": None, "pid": None},
    {"slot": "m4", "family": "mt4-exness", "platform": "MT4", "port": 8068, "state": "warm", "alloc": None, "pid": None},
]
LOCK = threading.Lock()

def log(m):
    line = "%s %s" % (time.strftime("%m-%d %H:%M:%S"), m)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass

def load_slots():
    try:
        with open(SLOTS_FILE, encoding="utf-8") as f: slots = json.load(f)
    except Exception:
        return [dict(s) for s in DEFAULT_SLOTS]
    # 迁移: 补默认字段/新增槽位(MT4 槽位在 v2 加入)
    have = {s["slot"] for s in slots}
    for d in DEFAULT_SLOTS:
        if d["slot"] not in have: slots.append(dict(d))
    for s in slots:
        s.setdefault("platform", "MT5"); s.setdefault("pid", None)
    return slots

def save_slots(slots):
    tmp = SLOTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(slots, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SLOTS_FILE)

SLOTS = load_slots()

def slot_base(s): return os.path.join(BASE, "pool", s["slot"])
def slot_dirs(s):
    base = slot_base(s)
    return os.path.join(base, "inst"), os.path.join(base, "terminal", "terminal64.exe")

def pick_family(server, platform):
    sv = (server or "").lower()
    pre = "mt4-" if platform == "MT4" else ""
    if sv.startswith("icmarkets"): return pre + "ic"
    if sv.startswith("exness"): return pre + "exness"
    return ""

def http_get(port, path, timeout=5):
    t0 = time.time()
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                 headers={"X-Api-Key": API_KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode()), int((time.time() - t0) * 1000)

def http_health(port, timeout=5):
    """返回 (mt5_connected, rtt_ms, trade_allowed)。trade_allowed: True/False/None
       (None=桥/agent 未报该字段, 如旧 MT4 agent)。用于部署时校验 AutoTrading 是否开启。"""
    try:
        j, rtt = http_get(port, "/health", timeout)
        if j.get("service") == "mt5-bridge":
            execution = j.get("execution_queue") or {}
            isolated_ready = bool(
                j.get("build_id") == MT5_BRIDGE_BUILD_ID and
                j.get("execution_process_isolation") is True and
                j.get("execution_healthy") is True and
                execution.get("process_isolated") is True and
                execution.get("execution_process_ready") is True and
                execution.get("coordinator_healthy") is True
            )
            if not isolated_ready:
                return False, rtt, j.get("trade_allowed")
        return bool(j.get("mt5")), rtt, j.get("trade_allowed")
    except Exception:
        return False, None, None

# ── MT5 槽位: .env + 桥进程 ──
def mt5_execution_settings(login, server):
    identity = str(server).strip().lower() + "|" + str(login).strip()
    fence_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return {
        "MT5_EXECUTION_FENCE_KEY": fence_key,
        "MT5_EXECUTION_LOCK_DIR": os.path.join(EXECUTION_ROOT, "locks"),
        "IDEMPOTENCY_DB": os.path.join(EXECUTION_ROOT, fence_key + ".db"),
    }


def ensure_mt5_execution_env(s):
    alloc = s.get("alloc") or {}
    if s.get("platform") != "MT5" or not alloc.get("login") or not alloc.get("server"):
        return
    inst, _ = slot_dirs(s)
    path = os.path.join(inst, ".env")
    if not os.path.exists(path):
        return
    values = dict(mt5_execution_settings(alloc["login"], alloc["server"]))
    os.makedirs(EXECUTION_ROOT, exist_ok=True)
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    output = []
    for line in lines:
        name = line.split("=", 1)[0] if "=" in line else ""
        if name in values:
            output.append(name + "=" + values.pop(name))
        else:
            output.append(line)
    output.extend(name + "=" + value for name, value in values.items())
    temporary = path + ".execution.tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(output) + "\n")
    os.replace(temporary, path)


def write_env(s, login, password, server):
    inst, term = slot_dirs(s)
    settings = mt5_execution_settings(login, server)
    fence_key = settings["MT5_EXECUTION_FENCE_KEY"]
    os.makedirs(EXECUTION_ROOT, exist_ok=True)
    env = ("API_KEY=%s\nMT5_LOGIN=%s\nMT5_PASSWORD='%s'\nMT5_SERVER=%s\n"
           "MT5_PATH=%s\nSERVICE_PORT=%d\nINSTANCE_NAME=qhcell-%s\n"
           "MT5_EXECUTION_PROCESS_ISOLATION=1\nMAX_PENDING_EXECUTIONS=32\n"
           "MT5_PARENT_READ_GATE_WAIT_MS=5000\n"
           "MT5_EXECUTION_READY_SEC=55\nMT5_EXECUTION_CONNECT_SEC=45\n"
           "MT5_EXECUTION_CONNECT_RETRY_MS=750\n"
           "MT5_NATIVE_RPC_TIMEOUT_SEC=30\n"
           "MT5_PUBLIC_TICK_CACHE_TTL_MS=250\n"
           "MT5_WAL_FALLBACK_POLL_MS=50\nACCOUNT_IDLE_REFRESH_SEC=5\n"
           "MT5_BRIDGE_BUILD_ID=%s\n"
           "MT5_EXECUTION_FENCE_KEY=%s\nMT5_EXECUTION_LOCK_DIR=%s\n"
           "IDEMPOTENCY_DB=%s\n"
           % (API_KEY, login, password, server, term, s["port"], s["slot"],
              MT5_BRIDGE_BUILD_ID, fence_key,
              settings["MT5_EXECUTION_LOCK_DIR"], settings["IDEMPOTENCY_DB"]))
    with open(os.path.join(inst, ".env"), "w", encoding="utf-8") as f: f.write(env)

def spawn_mt5(s):
    inst, _ = slot_dirs(s)
    out = open(os.path.join(inst, "logs", "bridge.out.log"), "ab")
    err = open(os.path.join(inst, "logs", "bridge.err.log"), "ab")
    p = subprocess.Popen([VENV_PY, "-m", "uvicorn", "app.main:app",
                          "--host", "0.0.0.0", "--port", str(s["port"])],
                         cwd=inst, stdout=out, stderr=err,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    return p.pid

# ── MT4 槽位: start.ini(原生启动配置) + 终端 + 文件桥 Agent ──
def mt4_paths(s):
    base = slot_base(s)
    term_dir = os.path.join(base, "terminal")
    return (os.path.join(base, "start.ini"), os.path.join(term_dir, "terminal.exe"),
            os.path.join(term_dir, "MQL4", "Files", "qhbridge"))

def write_mt4_ini(s, login, password, server):
    ini, _, _ = mt4_paths(s)
    body = ("Login=%s\r\nPassword=%s\r\nServer=%s\r\nProfile=default\r\nEnableNews=false\r\n"
            % (login, password, server))
    # ⚠newline="" 必须: Windows 文本模式会把 \n→\r\n, 叠加 body 里的 \r\n 变成 \r\r\n(双回车)
    # → MT4 解析 Login 值带尾随 \r → 账号无效认证失败(443 建但不登录)。禁 Python 换行转换。
    with open(ini, "w", encoding="ascii", errors="replace", newline="") as f: f.write(body)

def ensure_mt4_autotrading(s):
    """MT4 全局 AutoTrading headless 开启(修 4109 / trade_allowed=false 漏洞)。
       实测: config\\experts.ini **offset 36** 单字节 = 0x01(允许自动交易)/0x00(禁止)。
       起终端前强制置 1; 终端读取 → IsTradeAllowed()=true → 可下单。
       (start.ini 的 [Expert]AllowLiveTrading 段对 MT4 无效; EA 级允许在 profile.chr 用户已勾。)"""
    ei = os.path.join(slot_base(s), "terminal", "config", "experts.ini")
    try:
        with open(ei, "rb") as f: b = bytearray(f.read())
        if len(b) > 36 and b[36] != 1:
            b[36] = 1
            with open(ei, "wb") as f: f.write(b)
    except Exception: pass

def wipe_mt4_state(s):
    """清陈旧 EA 状态(防上个账户残留致 login 核验假阳性), 但**保留 qhbridge\\state 目录结构** ——
       ⚠MQL4 FileWrite 不自建目录, rmtree 整个 qhbridge 会导致 EA 写 state\\*.json 失败(state 恒 0)。"""
    _, _, files_dir = mt4_paths(s)
    state_dir = os.path.join(files_dir, "state")
    try:
        os.makedirs(state_dir, exist_ok=True)
        for f in os.listdir(state_dir):
            try: os.remove(os.path.join(state_dir, f))
            except Exception: pass
    except Exception: pass

def mt4_task_name(s): return "QHCELL-t-%s" % s["slot"]

def spawn_mt4(s):
    """起 MT4 终端(自登录) + Agent(文件桥)。返回 agent pid(terminal 经任务/按路径管理)。
       ⚠⚠会话拓扑铁律(实测): MT4 GUI 终端在 session 2(RDP 交互)登录失败, 必须落 session 0。
       (与 MT5 相反 —— MT5 python 桥在 session 0 IPC 超时, 需交互会话。二者会话需求相反。)
       cell 自身跑 session 2(供 MT5), 故 MT4 终端经**预建持久 SYSTEM 计划任务**(部署时建, tr 固定)
       在 session 0 起 —— 只 schtasks /run(避开 python→schtasks argv 引号地狱)。
       ⚠先 /end 强制结束旧任务实例: kill_slot 杀终端 pid 后任务状态有延迟仍显 Running,
       直接 /run 会被"任务已运行"忽略致终端不起 → 必须 /end→sleep→/run。"""
    ini, term_exe, files_dir = mt4_paths(s)
    tn = mt4_task_name(s)
    subprocess.run(["schtasks", "/end", "/tn", tn], capture_output=True)
    time.sleep(2)
    ensure_mt4_autotrading(s)   # 起终端前强制开全局 AutoTrading(experts.ini offset36=1)
    subprocess.run(["schtasks", "/run", "/tn", tn], capture_output=True)
    env = dict(os.environ)
    env.update({"API_KEY": API_KEY, "INSTANCE_NAME": "qhcell-%s" % s["slot"],
                "TERMINAL_FILES_DIR": files_dir, "SERVICE_PORT": str(s["port"])})
    logdir = os.path.join(slot_base(s), "logs"); os.makedirs(logdir, exist_ok=True)
    out = open(os.path.join(logdir, "agent.out.log"), "ab")
    p = subprocess.Popen([MT4_AGENT_PY, "-m", "uvicorn", "main:app",
                          "--host", "0.0.0.0", "--port", str(s["port"])],
                         cwd=MT4_AGENT_DIR, stdout=out, stderr=subprocess.STDOUT,
                         env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    return p.pid

def spawn_bridge(s):
    return spawn_mt4(s) if s.get("platform") == "MT4" else spawn_mt5(s)

def kill_slot(s):
    """杀本槽位全部进程: 桥/Agent python(记录 pid+按端口兜底)+ 终端(terminal64/terminal, 按槽位路径)。
       MT4 终端在 session 0(SYSTEM 任务起), CIM 跨会话可查, Stop-Process(cell 提权)可杀; 任务持久保留复用。"""
    if s.get("platform") == "MT4":
        subprocess.run(["schtasks", "/end", "/tn", mt4_task_name(s)], capture_output=True)
    if s.get("pid"):
        subprocess.run(["taskkill", "/PID", str(s["pid"]), "/T", "/F"], capture_output=True)
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*--port %d*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; "
          "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'terminal64.exe' -or $_.Name -eq 'terminal.exe') "
          "-and $_.CommandLine -like '*pool\\%s\\terminal*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
          % (s["port"], s["slot"]))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)

def wipe_creds(s):
    if s.get("platform") == "MT4":
        ini, _, _ = mt4_paths(s)
        try: os.remove(ini)
        except Exception: pass
        wipe_mt4_state(s)
    else:
        inst, _ = slot_dirs(s)
        try: os.remove(os.path.join(inst, ".env"))
        except Exception: pass

def _mt4_term_alive(s):
    """MT4 终端进程是否存活(按 pool\\slot 路径, 跨会话 CIM 查)。查失败保守返 True(不误重启)。"""
    ps = ("[bool](Get-CimInstance Win32_Process -Filter \"Name='terminal.exe'\" | "
          "Where-Object { $_.CommandLine -like '*pool\\%s\\terminal*' })" % s["slot"])
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=10)
        return "True" in (r.stdout or "")
    except Exception:
        return True

def wait_healthy(s, want_login="", budget_s=150):
    """等 /health 真 + AutoTrading 开(trade_allowed) + (可选)账户 login 匹配。
       ⚠AutoTrading 校验(修 10027 漏洞): trade_allowed 明确 False → 终端算法交易被关,
       视为未就绪(不会被当成功发出), 逼 allocate 失败→kill_slot 清终端→下次干净重起。
       ⚠MT4 OLE 崩溃自愈(修 10011): 并发起多个 MT4 终端会 OLE initialization failed[10011]
       首次崩溃退出, SYSTEM 任务只 /run 一次不重试 → 起后 >25s 仍无 health 且终端进程不在
       → /end→ensure_autotrading→/run 重起(冷却 40s)。"""
    t0 = time.time()
    last_respawn = t0
    while time.time() - t0 < budget_s:
        ok, rtt, ta = http_health(s["port"])
        if ok and ta is not False:   # AutoTrading 关(False)不算就绪; None/True 放行
            if not want_login:
                return True, rtt, int((time.time() - t0) * 1000)
            try:
                j, _ = http_get(s["port"], "/mt5/account/info", 8)
                if str(j.get("login")) == str(want_login):
                    return True, rtt, int((time.time() - t0) * 1000)
            except Exception: pass
        if (s.get("platform") == "MT4" and time.time() - t0 > 25
                and time.time() - last_respawn > 40 and not _mt4_term_alive(s)):
            tn = mt4_task_name(s)
            subprocess.run(["schtasks", "/end", "/tn", tn], capture_output=True)
            time.sleep(1)
            ensure_mt4_autotrading(s)
            subprocess.run(["schtasks", "/run", "/tn", tn], capture_output=True)
            last_respawn = time.time()
            log("respawn MT4 %s (OLE crash self-heal)" % s["slot"])
        time.sleep(2)
    return False, None, int((time.time() - t0) * 1000)

app = FastAPI()
CELL_HEALTH_PROBE_TIMEOUT = 1.5

def auth(x_api_key):
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(401, "bad api key")

@app.get("/cell/health")
def cell_health():
    with LOCK:
        warm = sum(1 for s in SLOTS if s["state"] == "warm")
        allocated = [
            {k: s.get(k) for k in ("slot", "platform", "port")}
            for s in SLOTS if s["state"] == "allocated"
        ]

    def probe(slot):
        try:
            connected, rtt, trade_allowed = http_health(
                slot["port"], timeout=CELL_HEALTH_PROBE_TIMEOUT)
        except Exception:
            connected, rtt, trade_allowed = False, None, None
        healthy = bool(connected and trade_allowed is not False)
        result = {
            "slot": slot["slot"],
            "platform": slot["platform"],
            "port": slot["port"],
            "healthy": healthy,
            "rtt_ms": rtt,
            "trade_allowed": trade_allowed,
        }
        if not healthy:
            result["reason"] = (
                "trade_disabled" if connected and trade_allowed is False
                else "bridge_unreachable_or_unhealthy"
            )
        return result

    if allocated:
        workers = min(len(allocated), 8)
        with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="cell-health") as pool:
            allocated_status = list(pool.map(probe, allocated))
    else:
        allocated_status = []
    unhealthy_slots = [
        status for status in allocated_status if not status["healthy"]
    ]
    allocated_healthy = len(allocated_status) - len(unhealthy_slots)
    return {
        "ok": not unhealthy_slots,
        "cell": CELL_NAME,
        "warm": warm,
        "allocated": len(allocated),
        "allocated_healthy": allocated_healthy,
        "allocated_status": allocated_status,
        "unhealthy_slots": unhealthy_slots,
        "ts": int(time.time()),
    }

@app.get("/cell/status")
def cell_status(x_api_key: str = Header(default="")):
    auth(x_api_key)
    out = []
    for s in SLOTS:
        e = {k: s[k] for k in ("slot", "family", "platform", "port", "state")}
        a = s.get("alloc") or {}
        if a:
            e["alloc"] = {k: a.get(k) for k in ("login", "server", "user", "role", "ts", "measured")}
        ok, rtt, ta = (http_health(s["port"]) if s["state"] == "allocated" else (None, None, None))
        e["healthy"] = ok; e["rtt_ms"] = rtt; e["trade_allowed"] = ta
        out.append(e)
    return {"cell": CELL_NAME, "slots": out}

class AllocReq(BaseModel):
    login: str; password: str; server: str
    platform: str = "MT5"; role: str = ""; user: str = ""; label: str = ""

@app.post("/cell/allocate")
def allocate(r: AllocReq, x_api_key: str = Header(default="")):
    auth(x_api_key)
    if r.platform not in ("MT5", "MT4"):
        raise HTTPException(400, "platform 须为 MT5|MT4")
    with LOCK:
        # 幂等: 同 login+server 已分配 → 直接返回原槽位
        for s in SLOTS:
            a = s.get("alloc") or {}
            if s["state"] == "allocated" and a.get("login") == r.login and a.get("server") == r.server:
                ok, rtt, _ta = http_health(s["port"])
                return {"ok": True, "idempotent": True, "cell": CELL_NAME, "slot": s["slot"],
                        "port": s["port"], "bridge_url": "http://172.31.5.62:%d" % s["port"],
                        "healthy": ok, "measured": a.get("measured")}
        fam = pick_family(r.server, r.platform)
        cand = [s for s in SLOTS if s["state"] == "warm" and s["platform"] == r.platform
                and (s["family"] == fam or not fam)]
        if not cand and r.platform == "MT5":
            cand = [s for s in SLOTS if s["state"] == "warm" and s["platform"] == "MT5"]  # MT5 可联网发现服务器
        if not cand:
            raise HTTPException(409, "%s 暖池无空闲槽位(族=%s), 请先清除占用或扩池" % (r.platform, fam or "any"))
        s = cand[0]
        s["state"] = "building"
        save_slots(SLOTS)
    t0 = time.time()
    log("allocate %s %s login=%s server=%s user=%s" % (s["slot"], r.platform, r.login, r.server, r.user))
    try:
        kill_slot(s)  # 清残留
        if r.platform == "MT4":
            wipe_mt4_state(s)
            write_mt4_ini(s, r.login, r.password, r.server)
        else:
            write_env(s, r.login, r.password, r.server)
        pid = spawn_bridge(s)
        ok, rtt, wait_ms = wait_healthy(s, want_login=(r.login if r.platform == "MT4" else ""))
        if not ok:
            kill_slot(s); wipe_creds(s)
            with LOCK:
                s["state"] = "warm"; s["alloc"] = None; s["pid"] = None
                save_slots(SLOTS)
            raise HTTPException(502, "桥启动/终端登录未在 150s 内就绪(核对账号/密码/服务器名)")
        measured = {"alloc_ms": int((time.time() - t0) * 1000), "login_wait_ms": wait_ms,
                    "health_rtt_ms": rtt}
        with LOCK:
            s["state"] = "allocated"; s["pid"] = pid
            s["alloc"] = {"login": r.login, "server": r.server, "user": r.user, "role": r.role,
                          "label": r.label, "platform": r.platform, "ts": int(time.time()),
                          "measured": measured}
            save_slots(SLOTS)
        log("allocated %s port=%d login=%s %sms" % (s["slot"], s["port"], r.login, measured["alloc_ms"]))
        return {"ok": True, "idempotent": False, "cell": CELL_NAME, "slot": s["slot"],
                "port": s["port"], "bridge_url": "http://172.31.5.62:%d" % s["port"],
                "healthy": True, "measured": measured}
    except HTTPException:
        raise
    except Exception as e:
        with LOCK:
            s["state"] = "warm"; s["alloc"] = None; s["pid"] = None
            save_slots(SLOTS)
        raise HTTPException(500, "allocate 异常: %s" % e.__class__.__name__)

class ReleaseReq(BaseModel):
    port: int = 0; login: str = ""

@app.post("/cell/release")
def release(r: ReleaseReq, x_api_key: str = Header(default="")):
    auth(x_api_key)
    with LOCK:
        tgt = None
        for s in SLOTS:
            a = s.get("alloc") or {}
            if s["state"] in ("allocated", "building") and (
                    (r.port and s["port"] == r.port) or (r.login and a.get("login") == r.login)):
                tgt = s; break
    if not tgt:
        return {"ok": True, "released": False, "msg": "无匹配占用(幂等视为已释放)"}
    log("release %s port=%d login=%s" % (tgt["slot"], tgt["port"], (tgt.get("alloc") or {}).get("login")))
    kill_slot(tgt); wipe_creds(tgt)
    with LOCK:
        tgt["state"] = "warm"; tgt["alloc"] = None; tgt["pid"] = None
        save_slots(SLOTS)
    return {"ok": True, "released": True, "slot": tgt["slot"], "port": tgt["port"]}

def _has_creds(s):
    if s.get("platform") == "MT4":
        return os.path.exists(mt4_paths(s)[0])
    inst, _ = slot_dirs(s)
    return os.path.exists(os.path.join(inst, ".env"))

def watchdog():
    bad = {}
    last_r = {}
    while True:
        time.sleep(30)
        for s in SLOTS:
            if s["state"] != "allocated": continue
            ok, _, _ = http_health(s["port"])
            if ok:
                if bad.get(s["slot"]): log("recovered %s" % s["slot"])
                bad[s["slot"]] = 0; continue
            bad[s["slot"]] = bad.get(s["slot"], 0) + 1
            log("unhealthy %s bad=%d" % (s["slot"], bad[s["slot"]]))
            if bad[s["slot"]] >= 3 and time.time() - last_r.get(s["slot"], 0) > 180:
                log("RESTART %s" % s["slot"])
                kill_slot(s)
                time.sleep(3)
                try:
                    s["pid"] = spawn_bridge(s)  # 凭证仍留存(.env / start.ini), 自登录
                    with LOCK: save_slots(SLOTS)
                except Exception as e:
                    log("restart fail %s %s" % (s["slot"], e))
                last_r[s["slot"]] = time.time(); bad[s["slot"]] = 0

def adopt():
    """启动收养: 已分配槽位桥活着=adopt, 死了=用留存凭证 revive。"""
    for s in SLOTS:
        if s["state"] == "building":
            kill_slot(s); wipe_creds(s)
            s["state"] = "warm"; s["alloc"] = None; s["pid"] = None
        if s["state"] != "allocated": continue
        if s.get("platform") == "MT5":
            ensure_mt5_execution_env(s)
        ok, _, _ = http_health(s["port"])
        if ok:
            log("adopt %s (healthy)" % s["slot"]); continue
        if _has_creds(s):
            log("revive %s" % s["slot"])
            kill_slot(s); s["pid"] = spawn_bridge(s)
        else:
            s["state"] = "warm"; s["alloc"] = None; s["pid"] = None
    save_slots(SLOTS)

adopt()
threading.Thread(target=watchdog, daemon=True).start()
log("=== cell %s up (v2 MT5+MT4), slots=%d ===" % (CELL_NAME, len(SLOTS)))
