#!/usr/bin/env python3
"""一次性补丁:main.py 接线 lab_schema.ensure_v2(c) 并 import,令第二代表代码自有。"""
import sys, os

MAIN = os.path.expanduser("~/dexlab/main.py")
src = open(MAIN, encoding="utf-8").read()

# 1) import lab_schema (插在 import lab_spine 之后)
anchor1 = "import lab_spine as _spine"
if anchor1 not in src:
    print("ABORT: anchor1 not found", file=sys.stderr); sys.exit(1)
if src.count(anchor1) != 1:
    print("ABORT: anchor1 non-unique", file=sys.stderr); sys.exit(1)
if "import lab_schema" in src:
    print("already wired: import lab_schema found", file=sys.stderr); sys.exit(0)
repl1 = anchor1 + "\nimport lab_schema"
src = src.replace(anchor1, repl1, 1)

# 2) 在 _migrate(c) 后调 lab_schema.ensure_v2(c)
anchor2 = "    _migrate(c)\n    c.commit()"
if anchor2 not in src:
    print("ABORT: anchor2 not found", file=sys.stderr); sys.exit(1)
if src.count(anchor2) != 1:
    print("ABORT: anchor2 non-unique", file=sys.stderr); sys.exit(1)
if "lab_schema.ensure_v2(c)" in src:
    print("already wired: ensure_v2 call found", file=sys.stderr); sys.exit(0)
repl2 = "    _migrate(c)\n    lab_schema.ensure_v2(c)  # LP0 增量2:第二代严谨表代码自有+版本戳\n    c.commit()"
src = src.replace(anchor2, repl2, 1)

open(MAIN, "w", encoding="utf-8").write(src)
print("wired: import + ensure_v2 call inserted into main.py")
