"""Slow-loop agent layer (P1-P2 of the transformation roadmap).

Deterministic-first: every agent produces structured, validated outputs from
ledger/backtest data; LLM enrichment is optional, advisory, and OFF by
default.  Nothing in this package places orders or mutates trading config --
proposals go through gate.py and wait for human approval.
"""
