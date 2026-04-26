path = "/home/ubuntu/hustle2026/frontend-admin/src/views/MasterDashboard.vue"
with open(path, "r") as f:
    c = f.read()

# 1. Filter disabled accounts from sortedAccounts
old = "const sortedAccounts = computed(() => {\n  return [...allAccounts.value].sort((a, b) => {"
new = "const sortedAccounts = computed(() => {\n  return [...allAccounts.value].filter(a => a.is_active !== false).sort((a, b) => {"
assert old in c, "sortedAccounts anchor not found"
c = c.replace(old, new, 1)

# 2. Filter disabled accounts from globalRiskText calculation
old2 = "  const maxRisk = Math.max(...allAccounts.value.map(a => getBal(a, 'risk_ratio') || 0), 0)"
new2 = "  const maxRisk = Math.max(...allAccounts.value.filter(a => a.is_active !== false).map(a => getBal(a, 'risk_ratio') || 0), 0)"
assert old2 in c, "globalRiskText anchor not found"
c = c.replace(old2, new2, 1)

# 3. Filter disabled accounts from rebuildUserFinancials
old3 = "  for (const acc of allAccounts.value) {"
new3 = "  for (const acc of allAccounts.value.filter(a => a.is_active !== false)) {"
assert c.count(old3) >= 1, "rebuildUserFinancials anchor not found"
c = c.replace(old3, new3, 1)

with open(path, "w") as f:
    f.write(c)
print("Admin dashboard: disabled accounts filtered from display and risk calc")
