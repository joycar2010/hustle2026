import sys

path = "/home/ubuntu/hustle2026/frontend-go/src/components/trading/StrategyPanel.vue"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add pairBinding ref after accountsData ref
old1 = "const accountsData = ref(null)"
new1 = "const accountsData = ref(null)\nconst pairBinding = ref(null)"
assert old1 in content, "anchor 1 not found"
content = content.replace(old1, new1, 1)

# 2. Add fetchPairBinding function + update watch
old2 = "watch(alertPairCode, () => {\n  fetchAlertSettings()\n})"
new2 = "watch(alertPairCode, () => {\n  fetchAlertSettings()\n  fetchPairBinding()\n})\n\nasync function fetchPairBinding() {\n  if (!alertPairCode.value) return\n  try {\n    const res = await api.get(`/api/v1/pair-accounts/${alertPairCode.value}`)\n    pairBinding.value = res.data\n  } catch (e) {\n    console.warn('Failed to fetch pair binding:', e)\n    pairBinding.value = null\n  }\n}"
assert old2 in content, "anchor 2 not found"
content = content.replace(old2, new2, 1)

# 3. Fix fetchAccountData
old3 = "    const bybitAccounts = accountData.accounts?.filter(acc => acc.platform_id === PlatformId.BYBIT) || []\n\n    // Use first account's available balance\n    binanceAssets.value = binanceAccounts.length > 0 ? (binanceAccounts[0].balance?.available_balance || 0) : 0\n    bybitAssets.value = bybitAccounts.length > 0 ? (bybitAccounts[0].balance?.available_balance || 0) : 0"
new3 = "    const hedgeId = pairBinding.value?.account_b_id\n    const hedgeAcc = hedgeId\n      ? accountData.accounts?.find(acc => acc.account_id === hedgeId)\n      : accountData.accounts?.find(acc => acc.platform_id === PlatformId.BYBIT && acc.is_active !== false)\n\n    binanceAssets.value = binanceAccounts.length > 0 ? (binanceAccounts[0].balance?.available_balance || 0) : 0\n    bybitAssets.value = hedgeAcc?.balance?.available_balance || 0"
assert old3 in content, "anchor 3 not found"
content = content.replace(old3, new3, 1)

# 4. Fix handleAccountBalanceUpdate — use a regex to handle em-dash encoding
import re
pat4 = re.compile(
    r"    const bybitAccounts = data\.accounts\.filter\(acc => acc\.platform_id === PlatformId\.BYBIT\) \|\| \[\]\n"
    r"\n"
    r"    // Use first account's available balance instead of summing all accounts\n"
    r"    binanceAssets\.value = binanceAccounts\.length > 0 \? \(binanceAccounts\[0\]\.balance\?\.available_balance \|\| 0\) : 0\n"
    r"\n"
    r"    // MT5 accounts always report available_balance=0 from the aggregated API/WS broadcast\.\n"
    r"    // Only update bybitAssets from WS if it's a non-MT5 account with real data\.\n"
    r"    const bybitAcc = bybitAccounts\[0\]\n"
    r"    if \(bybitAcc\) \{\n"
    r"      const wsBal = bybitAcc\.balance\?\.available_balance \|\| 0\n"
    r"      if \(!bybitAcc\.is_mt5_account \|\| wsBal > 0\) \{\n"
    r"        bybitAssets\.value = wsBal\n"
    r"      \}\n"
    r"      // For MT5:.*?\n"
    r"    \}"
)
new4 = (
    "    const hedgeId = pairBinding.value?.account_b_id\n"
    "    const hedgeAcc = hedgeId\n"
    "      ? data.accounts.find(acc => acc.account_id === hedgeId)\n"
    "      : data.accounts.find(acc => acc.platform_id === PlatformId.BYBIT && acc.is_active !== false)\n"
    "\n"
    "    binanceAssets.value = binanceAccounts.length > 0 ? (binanceAccounts[0].balance?.available_balance || 0) : 0\n"
    "\n"
    "    if (hedgeAcc) {\n"
    "      const wsBal = hedgeAcc.balance?.available_balance || 0\n"
    "      if (!hedgeAcc.is_mt5_account || wsBal > 0) {\n"
    "        bybitAssets.value = wsBal\n"
    "      }\n"
    "    }"
)
m4 = pat4.search(content)
assert m4, "anchor 4 not found"
content = content[:m4.start()] + new4 + content[m4.end():]

# 5. Fix strategy execution
old5 = "    const bybitMT5Account = accountsData.value.accounts.find(a => a.platform_id === PlatformId.BYBIT)"
new5 = "    const hedgeBId = pairBinding.value?.account_b_id\n    const bybitMT5Account = hedgeBId\n      ? accountsData.value.accounts.find(a => a.account_id === hedgeBId)\n      : accountsData.value.accounts.find(a => a.platform_id === PlatformId.BYBIT && a.is_active !== false)"
assert old5 in content, "anchor 5 not found"
content = content.replace(old5, new5, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("P1 patch applied successfully")
