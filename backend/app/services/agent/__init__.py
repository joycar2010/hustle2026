"""OpenCLAW agent module.

Layered architecture:
  config_loader  → hot-reloadable rules from agent_active_config table
  guard          → deterministic rule engine; LLM proposals MUST pass through
  rate_buckets   → 6 rolling windows on Redis to enforce anti-ban frequency caps
  state          → AgentState ORM helpers (mode, kill switch)
"""
