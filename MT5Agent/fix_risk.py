path = "/data/hustle2026/backend/app/services/account_service.py"
with open(path, "r") as f:
    c = f.read()

# Fix MT5 margin_level → risk_ratio conversion
# MT5 margin_level = equity/margin*100 (higher=safer, 5000%=very safe)
# CEX risk_ratio = maint_margin/margin_balance*100 (higher=riskier)
# Convert: risk_ratio = margin/equity*100 (inverse of margin_level)
# This gives ~1-2% when safe, approaches 100% at margin call

old1 = "                        _margin_level = (_equity / _margin * 100) if _margin > 0.01 else 0.0\n\n                        # \xe2\x94\x80\xe2\x94\x80 \xe5\xbc\xba\xe5\xb9\xb3\xe4\xbb\xb7\xe8\xae\xa1\xe7\xae\x97\xef\xbc\x88Bybit MT5"
assert old1 in c, f"anchor 1 not found"

new1 = "                        _margin_level = (_margin / _equity * 100) if _equity > 0.01 else 0.0\n\n                        # \xe2\x94\x80\xe2\x94\x80 \xe5\xbc\xba\xe5\xb9\xb3\xe4\xbb\xb7\xe8\xae\xa1\xe7\xae\x97\xef\xbc\x88Bybit MT5"
c = c.replace(old1, new1, 1)

# Also fix IC Markets branch (line 1334)
old2 = "                    _margin_level = (_equity / _margin * 100) if _margin > 0.01 else 0.0"
# After first replacement, only the IC Markets one remains
assert old2 in c, "anchor 2 not found"
c = c.replace(old2, "                    _margin_level = (_margin / _equity * 100) if _equity > 0.01 else 0.0", 1)

with open(path, "w") as f:
    f.write(c)
print("MT5 risk_ratio formula fixed (margin/equity*100)")
