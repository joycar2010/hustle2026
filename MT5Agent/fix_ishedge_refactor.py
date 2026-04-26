"""
Comprehensive isHedge() refactor across frontend-go.
Replaces all hardcoded PlatformId.BYBIT checks for hedge account logic.
"""
import re

BASE = "/home/ubuntu/hustle2026/frontend-go/src"

def patch(filepath, replacements, add_imports=None):
    with open(filepath, "r") as f:
        c = f.read()
    # Add imports if needed
    if add_imports:
        for imp_old, imp_new in add_imports:
            if imp_old in c and imp_new not in c:
                c = c.replace(imp_old, imp_new)
    for old, new in replacements:
        if old not in c:
            print(f"  WARN: anchor not found in {filepath}: {old[:60]}...")
            continue
        count = c.count(old)
        c = c.replace(old, new)
        print(f"  OK: replaced {count}x: {old[:50]}...")
    with open(filepath, "w") as f:
        f.write(c)

# ── 1. MarketCards.vue ──────────────────────────────────────────
print("=== MarketCards.vue ===")
mc = f"{BASE}/components/trading/MarketCards.vue"
patch(mc, [
    # Import isHedge
    ("import { PlatformId } from '@/constants/platform'",
     "import { PlatformId, isHedge } from '@/constants/platform'"),
    # 634, 814: bybitAccounts filter (2 occurrences, replace_all)
    ("data.accounts.filter(acc => acc.platform_id === PlatformId.BYBIT)",
     "data.accounts.filter(acc => isHedge(acc.platform_id))"),
    # 647, 673, 827, 856: position sorting by platform (4 occurrences)
    ("if (account.platform_id === PlatformId.BYBIT) {",
     "if (isHedge(account.platform_id)) {"),
])

# ── 2. AssetDashboard.vue ──────────────────────────────────────
print("=== AssetDashboard.vue ===")
ad = f"{BASE}/components/dashboard/AssetDashboard.vue"
with open(ad, "r") as f:
    c = f.read()
# Add isHedge import
if "isHedge" not in c:
    if "import { PlatformId }" in c:
        c = c.replace("import { PlatformId }", "import { PlatformId, isHedge }")
    elif "PlatformId" in c:
        # Find where PlatformId is imported
        pass
# Fix the filter
c = c.replace(
    "const bybitAccounts = data.accounts.filter(acc => acc.platform_id === PlatformId.BYBIT)",
    "const bybitAccounts = data.accounts.filter(acc => isHedge(acc.platform_id))"
)
# Also fix the comment
c = c.replace(
    "// Find Bybit accounts (platform_id === 2)",
    "// Find hedge accounts (Bybit / IC Markets / ...)"
)
with open(ad, "w") as f:
    f.write(c)
print("  OK: AssetDashboard patched")

# ── 3. RiskDashboard.vue ──────────────────────────────────────
print("=== RiskDashboard.vue ===")
rd = f"{BASE}/components/trading/RiskDashboard.vue"
with open(rd, "r") as f:
    c = f.read()
if "isHedge" not in c:
    if "import { PlatformId }" in c:
        c = c.replace("import { PlatformId }", "import { PlatformId, isHedge }")
    elif "import { PlatformId," in c:
        c = c.replace("import { PlatformId,", "import { PlatformId, isHedge,")
c = c.replace(
    "const bybitAccounts = data.accounts?.filter(acc => acc.platform_id === PlatformId.BYBIT) || []",
    "const bybitAccounts = data.accounts?.filter(acc => isHedge(acc.platform_id)) || []"
)
with open(rd, "w") as f:
    f.write(c)
print("  OK: RiskDashboard patched")

# ── 4. AccountStatusPanel.vue ──────────────────────────────────
print("=== AccountStatusPanel.vue ===")
asp = f"{BASE}/components/trading/AccountStatusPanel.vue"
with open(asp, "r") as f:
    c = f.read()
# Add isHedge import
if "isHedge" not in c:
    if "import { PlatformId }" in c:
        c = c.replace("import { PlatformId }", "import { PlatformId, isHedge }")
    elif "import { PlatformId," in c:
        c = c.replace("import { PlatformId,", "import { PlatformId, isHedge,")
# Template: v-if checks for showing margin/position fields — use is_mt5_account instead
c = c.replace(
    'v-if="account.platform_id === PlatformId.BYBIT"',
    'v-if="isHedge(account.platform_id)"'
)
# getRiskColor: MT5-specific logic should check is_mt5_account
c = c.replace(
    "if (account.platform_id === PlatformId.BYBIT && account.is_mt5_account) {",
    "if (account.is_mt5_account) {"
)
# Liquidation price push: should trigger for any MT5 hedge account
c = c.replace(
    "if (acc.platform_id === PlatformId.BYBIT && acc.is_mt5_account) {",
    "if (acc.is_mt5_account && isHedge(acc.platform_id)) {"
)
with open(asp, "w") as f:
    f.write(c)
print("  OK: AccountStatusPanel patched")

# ── 5. useAlertMonitoring.js ──────────────────────────────────
print("=== useAlertMonitoring.js ===")
am = f"{BASE}/composables/useAlertMonitoring.js"
with open(am, "r") as f:
    c = f.read()
if "isHedge" not in c:
    c = c.replace(
        "import { PlatformId }",
        "import { PlatformId, isHedge }"
    )
c = c.replace(
    "bybit_account: message.data.accounts?.find(acc => acc.platform_id === PlatformId.BYBIT && acc.is_mt5_account)",
    "bybit_account: message.data.accounts?.find(acc => isHedge(acc.platform_id) && acc.is_mt5_account)"
)
with open(am, "w") as f:
    f.write(c)
print("  OK: useAlertMonitoring patched")

print("\n=== All patches applied ===")
