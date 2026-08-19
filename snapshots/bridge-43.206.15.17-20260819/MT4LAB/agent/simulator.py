"""
simulator.py — 确定性 Broker Simulator(假 EA 侧)

替代真 MT4 终端 + EA:轮询 qhbridge/commands/,按注入模式写 results/,维护假持仓账本。
用于 Phase D 验证 Agent 的命令账本/幂等/UNKNOWN/恢复逻辑,不下真单。

模式(测试床写 sim/mode.json 控制):
  normal   下一条命令正常执行
  timeout  不写结果、不删命令(模拟 EA 忙/挂 → Agent 超时=UNKNOWN,命令留存待后续处理)
  reject   写 ok:false(券商拒单 retcode)
  partial  写 ok:true 部分成交(filled = requested/2)
  delay    sleep(delay_sec) 后正常
  crash    进程退出(模拟 EA/终端崩溃,命令未处理留存)

otoken 去重:同 otoken 已执行则返回原 ticket + reconciled:true(模拟 EA 崩溃后按 comment 认领,防重开)。

用法:python simulator.py <files_dir>   (files_dir = 测试 qhbridge 目录)
"""
import json
import os
import sys
import time

POLL = 0.05


class Simulator:
    def __init__(self, files_dir):
        self.root = files_dir
        self.state = os.path.join(files_dir, "state")
        self.commands = os.path.join(files_dir, "commands")
        self.results = os.path.join(files_dir, "results")
        self.simdir = os.path.join(files_dir, "sim")
        for d in (self.state, self.commands, self.results, self.simdir):
            os.makedirs(d, exist_ok=True)
        self.next_ticket = 900001
        self.positions = {}          # ticket -> {symbol, side, volume, price}
        self.executed = {}           # otoken -> ticket(去重)

    def _atomic(self, path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _mode(self):
        try:
            with open(os.path.join(self.simdir, "mode.json"), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"mode": "normal"}

    def heartbeat(self):
        ts = int(time.time())
        self._atomic(os.path.join(self.state, "meta.json"),
                     {"connected": True, "account": 999999, "server": "SIM",
                      "company": "Simulator", "ts": ts, "ea": "SIM/1.0"})
        eq = 100000.0 + sum(0 for _ in self.positions)
        self._atomic(os.path.join(self.state, "account.json"),
                     {"login": 999999, "balance": 100000.0, "equity": eq, "margin": 0.0,
                      "margin_free": eq, "margin_level": 0.0, "margin_so_call": None,
                      "margin_so_so": 50.0, "margin_so_mode": 0, "profit": 0.0, "swap": 0.0,
                      "currency": "USD", "leverage": 500, "server": "SIM", "name": "sim",
                      "company": "Simulator", "ts": ts})
        posl = [{"ticket": t, "symbol": p["symbol"], "type": (1 if p["side"] == "sell" else 0),
                 "volume": p["volume"], "price_open": p["price"], "price_current": p["price"],
                 "profit": 0.0, "swap": 0.0, "sl": 0.0, "tp": 0.0, "margin": 0.0,
                 "price_liquidation": 0.0, "time": ts, "comment": ""} for t, p in self.positions.items()]
        self._atomic(os.path.join(self.state, "positions.json"), {"positions": posl, "ts": ts})

    def _result(self, cmd_id, data):
        self._atomic(os.path.join(self.results, cmd_id + ".json"), data)
        try:
            os.remove(os.path.join(self.commands, cmd_id + ".json"))   # tombstone:留 result 删 command
        except OSError:
            pass

    def handle(self, cmd_id, cmd):
        m = self._mode()
        mode = m.get("mode", "normal")
        if mode == "timeout":
            return   # 不处理,命令留存
        if mode == "crash":
            print("SIM CRASH (mode=crash), exiting without processing %s" % cmd_id)
            sys.exit(3)
        if mode == "delay":
            time.sleep(float(m.get("delay_sec", 3)))

        op = cmd.get("op")
        otoken = cmd.get("otoken", "")

        if op == "order":
            # otoken 去重(模拟 EA 按 comment 认领已执行单)
            if otoken in self.executed:
                t = self.executed[otoken]
                p = self.positions.get(t, {})
                self._result(cmd_id, {"ok": True, "op": "order", "ticket": t,
                                      "price": p.get("price", 0.0), "volume": p.get("volume", cmd.get("volume")),
                                      "requested_volume": cmd.get("volume"), "retcode": 10009,
                                      "partial": False, "reconciled": True, "comment": otoken})
                return
            if mode == "reject":
                self._result(cmd_id, {"ok": False, "op": "order", "retcode": 10018,
                                      "error": "sim reject", "comment": otoken})
                return
            req_vol = float(cmd.get("volume") or 0.0)
            filled = req_vol
            partial = False
            if mode == "partial":
                filled = round(req_vol / 2.0, 2)
                partial = True
            t = self.next_ticket
            self.next_ticket += 1
            price = 4012.50
            self.executed[otoken] = t
            self.positions[t] = {"symbol": cmd.get("symbol"), "side": cmd.get("side"),
                                 "volume": filled, "price": price}
            self._result(cmd_id, {"ok": True, "op": "order", "ticket": t, "price": price,
                                  "volume": filled, "requested_volume": req_vol,
                                  "normalized_volume": req_vol, "retcode": (10010 if partial else 10009),
                                  "partial": partial, "reconciled": False, "comment": otoken})

        elif op == "close":
            tk = cmd.get("ticket")
            if tk is not None:
                if tk in self.positions:
                    p = self.positions.pop(tk)
                    self._result(cmd_id, {"ok": True, "op": "close", "ticket": tk,
                                          "price": p["price"], "volume": p["volume"], "retcode": 10009})
                else:
                    # 幂等:票已不在 = 已平,回成功
                    self._result(cmd_id, {"ok": True, "op": "close", "ticket": tk,
                                          "reconciled": True, "note": "already closed", "retcode": 10009})
            else:
                # 按 symbol+side 找一仓平
                side = cmd.get("side")
                target = 0 if side == "sell" else 1   # side=sell 平多(type0)
                found = [t for t, p in self.positions.items()
                         if p["symbol"] == cmd.get("symbol") and (1 if p["side"] == "sell" else 0) == target]
                if found:
                    t = found[0]; p = self.positions.pop(t)
                    self._result(cmd_id, {"ok": True, "op": "close", "ticket": t,
                                          "price": p["price"], "volume": p["volume"], "retcode": 10009})
                else:
                    self._result(cmd_id, {"ok": False, "op": "close", "error": "no matching position"})

        elif op == "close_all":
            sym = cmd.get("symbol")
            tks = [t for t, p in self.positions.items() if (sym is None or p["symbol"] == sym)]
            results = []
            for t in tks:
                self.positions.pop(t, None)
                results.append({"ticket": t, "success": True, "order": t})
            self._result(cmd_id, {"ok": True, "op": "close_all", "closed": len(tks),
                                  "failed": 0, "results": results})

        elif op == "cancel_all":
            self._result(cmd_id, {"ok": True, "op": "cancel_all", "cancelled": 0, "failed": 0})

        else:
            self._result(cmd_id, {"ok": False, "error": "unknown op %s" % op})

    def run(self):
        print("Simulator running on %s" % self.root)
        last_hb = 0
        while True:
            now = time.time()
            if now - last_hb >= 0.5:
                self.heartbeat()
                last_hb = now
            try:
                cmds = [f for f in os.listdir(self.commands) if f.endswith(".json") and not f.endswith(".tmp")]
            except OSError:
                cmds = []
            for fn in sorted(cmds):
                cmd_id = fn[:-5]
                try:
                    with open(os.path.join(self.commands, fn), "r", encoding="utf-8") as f:
                        cmd = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                self.handle(cmd_id, cmd)
            time.sleep(POLL)


if __name__ == "__main__":
    files_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "simtest", "qhbridge")
    Simulator(files_dir).run()
