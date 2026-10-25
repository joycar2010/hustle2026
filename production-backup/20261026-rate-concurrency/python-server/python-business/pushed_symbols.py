"""Atomic Redis mutations for the user-scoped pushed-symbol list."""

from __future__ import annotations

import json
from collections.abc import Iterable


_MUTATE_PUSHED_LUA = r"""
local raw = redis.call('GET', KEYS[1])
local current = {}
if raw then
    local ok, decoded = pcall(cjson.decode, raw)
    if ok and type(decoded) == 'table' then current = decoded end
end

local members = {}
for _, symbol in ipairs(current) do
    if type(symbol) == 'string' then members[symbol] = true end
end

local changed = 0
local add_blocked = KEYS[2] ~= '' and redis.call('EXISTS', KEYS[2]) == 1
local manual_marker_key = KEYS[4]
local mark_manual = ARGV[4] == '1'
local clear_manual = ARGV[5] == '1'
local protect_manual_removal = ARGV[6] == '1'
local pushed_at_key = string.gsub(KEYS[1], 'pushed_symbols$', 'pushed_at')
if pushed_at_key == KEYS[1] then pushed_at_key = '' end
local redis_time = redis.call('TIME')
local pushed_at_now = tostring(redis_time[1]) .. '.' .. string.format('%06d', redis_time[2])

local additions = cjson.decode(ARGV[1])
if not add_blocked then
    -- Keep the source marker and list membership in the same Redis
    -- transaction. Do not mark an addition rejected by its guard.
    if mark_manual and manual_marker_key ~= '' then
        redis.call('SET', manual_marker_key, '1')
    end
    for _, symbol in ipairs(additions) do
        local is_new = not members[symbol]
        if not members[symbol] then
            members[symbol] = true
            changed = changed + 1
        end
        if pushed_at_key ~= '' then
            if mark_manual then
                -- Explicit re-push is a new user action and moves the row to
                -- the top even if membership already existed.
                redis.call('HSET', pushed_at_key, symbol, pushed_at_now)
            elseif is_new then
                redis.call('HSETNX', pushed_at_key, symbol, pushed_at_now)
            end
        end
    end
end

local removals = cjson.decode(ARGV[2])
local removed = 0
local removal_blocked = protect_manual_removal
    and manual_marker_key ~= ''
    and redis.call('EXISTS', manual_marker_key) == 1
if not removal_blocked then
    for _, symbol in ipairs(removals) do
        if members[symbol] then
            members[symbol] = nil
            changed = changed + 1
            removed = removed + 1
        end
        if pushed_at_key ~= '' then
            redis.call('HDEL', pushed_at_key, symbol)
        end
    end
end

if ARGV[7] == '1' and pushed_at_key ~= '' then
    -- Repair legacy rows inside the same transaction as the membership read.
    -- A GET handler must never calculate stale fields from an older list and
    -- then race a concurrent push.
    for symbol, _ in pairs(members) do
        redis.call('HSETNX', pushed_at_key, symbol, pushed_at_now)
    end
    for _, symbol in ipairs(redis.call('HKEYS', pushed_at_key)) do
        if not members[symbol] then redis.call('HDEL', pushed_at_key, symbol) end
    end
end

if clear_manual and manual_marker_key ~= '' then
    redis.call('DEL', manual_marker_key)
end

local cooldown_ttl = tonumber(ARGV[3]) or 0
if removed > 0 and KEYS[3] ~= '' and cooldown_ttl > 0 then
    redis.call('SETEX', KEYS[3], cooldown_ttl, '1')
end

-- Preserve the queue order already stored in ``current``.  Newly added
-- symbols are emitted first (in caller order), so the most recently pushed
-- slot stays at the top.  A set/pairs or alphabetic sort here changes visible
-- slot order on every mutation.
local result = {}
local emitted = {}
for _, symbol in ipairs(additions) do
    if members[symbol] and not emitted[symbol] then
        table.insert(result, symbol)
        emitted[symbol] = true
    end
end
for _, symbol in ipairs(current) do
    if members[symbol] and not emitted[symbol] then
        table.insert(result, symbol)
        emitted[symbol] = true
    end
end
-- Redis cjson encodes an empty Lua table as {}, but this key's public
-- contract is always a JSON array. Build the short array explicitly.
local parts = {}
for index, symbol in ipairs(result) do parts[index] = cjson.encode(symbol) end
local encoded = '[' .. table.concat(parts, ',') .. ']'
redis.call('SET', KEYS[1], encoded)
return {encoded, changed, add_blocked and 1 or 0, removal_blocked and 1 or 0}
"""


# Custom-monitor rows are candidate/display entries, not Binance symbols.  A
# dedicated namespace prevents a display alias (for example ``LUNA``) from
# colliding with an executable ``LUNAUSDT`` row in the tenant list.
CUSTOM_MONITOR_PREFIX = "CUSTOM:"


def custom_monitor_candidate_key(monitor_id: int) -> str:
    """Return the tenant pushed-list key for a custom monitor id."""
    value = int(monitor_id)
    if value <= 0:
        raise ValueError("monitor_id must be a positive integer")
    return f"{CUSTOM_MONITOR_PREFIX}{value}"


def custom_monitor_id_from_candidate(value: object) -> int | None:
    """Parse a namespaced custom candidate, returning ``None`` otherwise."""
    raw = str(value or "").strip().upper()
    if not raw.startswith(CUSTOM_MONITOR_PREFIX):
        return None
    suffix = raw[len(CUSTOM_MONITOR_PREFIX):]
    if not suffix.isdigit():
        return None
    monitor_id = int(suffix)
    return monitor_id if monitor_id > 0 else None


def is_custom_monitor_candidate(value: object) -> bool:
    """Whether a pushed-list member is a display-only custom candidate."""
    return custom_monitor_id_from_candidate(value) is not None


def custom_monitor_source_key(user_id: int | None) -> str:
    """Return the optional source-index hash for custom candidates."""
    scope = "None" if user_id is None else str(int(user_id))
    return f"engine:{scope}:custom_monitor_pushed"


def _payload(symbols: Iterable[str]) -> str:
    # Redis stores an ordered queue.  Keep caller order while de-duplicating;
    # sorting here was the source of the dashboard's alphabetic slot order.
    normalized = []
    seen = set()
    for symbol in symbols:
        value = str(symbol).strip().upper()
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return json.dumps(normalized, separators=(",", ":"))


def _result(value) -> tuple[list[str], int]:
    encoded, changed, *_ = value
    if isinstance(encoded, bytes):
        encoded = encoded.decode()
    # Keep the ordered list returned by Lua.  Callers historically received a
    # set, which discarded queue order before publishing dashboard updates.
    decoded = json.loads(encoded or "[]")
    ordered = [str(item).strip().upper() for item in decoded if str(item).strip()]
    return ordered, int(changed or 0)


def manual_push_marker_key(user_id: int | None, symbol: str) -> str:
    """Return the user-scoped marker protecting a manual pushed symbol."""
    normalized = str(symbol).strip().upper()
    scope = "None" if user_id is None else str(int(user_id))
    return f"engine:{scope}:manual_pushed:{normalized}"


def auto_global_rules_key(user_id: int | None) -> str:
    """Return the hash of symbols that still inherit the global rule snapshot.

    The pushed list is intentionally only membership.  This separate hash
    records the source contract for an automatic push: an existing
    SymbolRule/AccountSymbolRule must not silently change the first borrow
    decision until the user explicitly saves that symbol's rule.  Hash
    membership is removed by manual pushes and rule-save endpoints.
    """
    scope = "None" if user_id is None else str(int(user_id))
    return f"engine:{scope}:auto_global_rules"


def clear_auto_global_rule_marker(redis_client, user_id: int | None, symbol: str) -> None:
    """Best-effort switch from automatic global rules to explicit overrides."""
    redis_client.hdel(auto_global_rules_key(user_id), str(symbol).strip().upper())


def auto_global_rule_account_field(sub_account_id: int, symbol: str) -> str:
    """Return the account-scoped override field in ``auto_global_rules``.

    The hash's plain ``SYMBOL`` field means every account still inherits the
    global snapshot.  A ``SUB_ACCOUNT_ID:SYMBOL`` field is written only when
    that account's rule is explicitly saved, allowing sibling Workers to
    retain the automatic/global source independently.
    """
    normalized = str(symbol or "").strip().upper()
    return f"{int(sub_account_id)}:{normalized}"


async def clear_auto_global_rule_account_markers_async(
    redis_client,
    user_id: int | None,
    symbol: str,
) -> int:
    """Clear stale account overrides when a symbol starts a new auto epoch.

    A symbol can leave and later re-enter the pushed list. The first Worker
    that observes the re-add must reset all account-scoped fields, not only
    its own field; otherwise a sibling's historical explicit override would
    silently control the new automatic decision. A later explicit account
    save writes its field back.
    """
    key = auto_global_rules_key(user_id)
    normalized = str(symbol or "").strip().upper()
    suffix = f":{normalized}"
    try:
        fields = await redis_client.hkeys(key)
        stale = []
        for field in fields or ():
            value = field.decode() if isinstance(field, (bytes, bytearray)) else str(field)
            if value.endswith(suffix):
                stale.append(value)
        if stale:
            await redis_client.hdel(key, *stale)
        return len(stale)
    except Exception:
        # Marker cleanup is advisory; membership and execution safety gates
        # remain authoritative if an older Redis proxy lacks hash methods.
        return 0


def _mutation_payloads(
    add,
    remove,
    *,
    manual_marker_key: str,
    mark_manual: bool,
    clear_manual: bool,
    protect_manual_removal: bool,
) -> tuple[str, str]:
    additions = _payload(add)
    removals = _payload(remove)
    operations = sum(bool(value) for value in (
        mark_manual,
        clear_manual,
        protect_manual_removal,
    ))
    if operations == 0:
        return additions, removals
    if not manual_marker_key:
        raise ValueError("manual_marker_key is required for manual marker operations")
    if operations != 1:
        raise ValueError("manual marker operations are mutually exclusive")

    add_members = json.loads(additions)
    remove_members = json.loads(removals)
    if mark_manual:
        valid = len(add_members) == 1 and not remove_members
    else:
        valid = len(remove_members) == 1 and not add_members
    if not valid:
        raise ValueError("manual marker operations require exactly one matching symbol")
    return additions, removals


def mutate_pushed_symbols(
    redis_client,
    key: str,
    *,
    add=(),
    remove=(),
    add_guard_key: str = "",
    remove_cooldown_key: str = "",
    remove_cooldown_ttl: int = 0,
    manual_marker_key: str = "",
    mark_manual: bool = False,
    clear_manual: bool = False,
    protect_manual_removal: bool = False,
    reconcile_timestamps: bool = False,
) -> tuple[list[str], int]:
    """Synchronously add/remove list members in one Redis script."""
    additions, removals = _mutation_payloads(
        add,
        remove,
        manual_marker_key=manual_marker_key,
        mark_manual=mark_manual,
        clear_manual=clear_manual,
        protect_manual_removal=protect_manual_removal,
    )
    value = redis_client.eval(
        _MUTATE_PUSHED_LUA,
        4,
        key,
        add_guard_key,
        remove_cooldown_key,
        manual_marker_key,
        additions,
        removals,
        max(0, int(remove_cooldown_ttl)),
        int(bool(mark_manual)),
        int(bool(clear_manual)),
        int(bool(protect_manual_removal)),
        int(bool(reconcile_timestamps)),
    )
    return _result(value)


async def mutate_pushed_symbols_async(
    redis_client,
    key: str,
    *,
    add=(),
    remove=(),
    add_guard_key: str = "",
    remove_cooldown_key: str = "",
    remove_cooldown_ttl: int = 0,
    manual_marker_key: str = "",
    mark_manual: bool = False,
    clear_manual: bool = False,
    protect_manual_removal: bool = False,
    reconcile_timestamps: bool = False,
) -> tuple[list[str], int]:
    """Asynchronously add/remove list members in one Redis script."""
    additions, removals = _mutation_payloads(
        add,
        remove,
        manual_marker_key=manual_marker_key,
        mark_manual=mark_manual,
        clear_manual=clear_manual,
        protect_manual_removal=protect_manual_removal,
    )
    value = await redis_client.eval(
        _MUTATE_PUSHED_LUA,
        4,
        key,
        add_guard_key,
        remove_cooldown_key,
        manual_marker_key,
        additions,
        removals,
        max(0, int(remove_cooldown_ttl)),
        int(bool(mark_manual)),
        int(bool(clear_manual)),
        int(bool(protect_manual_removal)),
        int(bool(reconcile_timestamps)),
    )
    return _result(value)
