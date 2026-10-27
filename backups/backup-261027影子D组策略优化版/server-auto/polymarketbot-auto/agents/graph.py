"""Minimal role-graph orchestrator for the slow loop (P2 skeleton).

Deliberately tiny and dependency-free: nodes are callables with declared
inputs/outputs over a shared context dict, executed in topological order,
with per-node timing and error isolation recorded to a real heartbeat file
(agents/out/agent_status.json).  The shape mirrors a LangGraph StateGraph so
swapping the runner later is mechanical; what matters now is that each
OpenClaw role becomes an ACTUAL unit of work with its own real status.

Current wiring (three real roles, five placeholders):

    review(复盘) --+
                   +--> desk(台长) --> gate --> proposals.jsonl (PENDING_HUMAN)
    search(猎手) --+

Placeholders (whale/shill) report `idle` honestly instead of pretending.
Execution-side roles (risk/sniper/exit/rug) remain deterministic code inside
the fast loop and are represented here as `external`.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "out")


@dataclass
class Node:
    role: str                  # OpenClaw role id: desk/search/whale/...
    fn: Callable[[dict], dict] | None
    needs: list[str] = field(default_factory=list)
    kind: str = "agent"        # agent | placeholder | external


class RoleGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.status: dict[str, dict[str, Any]] = {}

    def add(self, node: Node) -> None:
        self.nodes[node.role] = node

    def run(self, context: dict) -> dict:
        done: set[str] = set()
        pending = dict(self.nodes)
        while pending:
            ready = [n for n in pending.values() if all(d in done for d in n.needs)]
            if not ready:
                raise RuntimeError(f"cycle or missing dependency among: {list(pending)}")
            for node in ready:
                t0 = time.time()
                entry: dict[str, Any] = {
                    "status": "idle", "kind": node.kind, "queue_depth": 0,
                    "heartbeat_ts": round(t0, 3), "workflow_stage": "-",
                }
                if node.kind == "agent" and node.fn is not None:
                    try:
                        out = node.fn(context) or {}
                        context.update(out)
                        entry.update(status="running", workflow_stage="completed",
                                     duration_ms=int((time.time() - t0) * 1000),
                                     **{k: v for k, v in out.items()
                                        if isinstance(v, (int, float, str))})
                    except Exception as exc:  # isolate: one role failing
                        entry.update(status="error", workflow_stage="failed",
                                     detail=f"{type(exc).__name__}: {exc}")
                        context.setdefault("errors", {})[node.role] = traceback.format_exc()
                elif node.kind == "external":
                    entry.update(status="external",
                                 workflow_stage="fast-loop (deterministic)")
                self.status[node.role] = entry
                done.add(node.role)
                pending.pop(node.role)
        self._write_status()
        return context

    def _write_status(self) -> None:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "agent_status.json"), "w", encoding="utf-8") as f:
            json.dump({"ts": round(time.time(), 3), "roles": self.status},
                      f, ensure_ascii=False, indent=1)
