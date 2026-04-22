"""Tiny async helpers that push new decisions / proposal-status-changes
onto the stream_hub so the auto frontend can subscribe instead of polling.

Safe to call from any async context; failures never propagate (we don\'t
want a WS hiccup to kill decision persistence)."""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

AGENT_DECISIONS_CH = 'agent.decisions'
AGENT_PROPOSALS_CH = 'agent.proposals'


async def push_decision_event(payload: Dict[str, Any]) -> None:
    """Publish a single new-decision envelope to agent.decisions channel."""
    try:
        from app.websocket.stream_hub import stream_hub
        await stream_hub.publish(AGENT_DECISIONS_CH, {
            'event': 'decision_new',
            **payload,
        })
    except Exception as e:
        logger.debug(f'[ws_events] push_decision_event swallowed: {e}')


async def push_proposal_event(event: str, payload: Dict[str, Any]) -> None:
    """Publish a proposal-lifecycle event (approved / rejected / created).

    `event` is one of: proposal_new, proposal_approved, proposal_rejected.
    """
    try:
        from app.websocket.stream_hub import stream_hub
        await stream_hub.publish(AGENT_PROPOSALS_CH, {
            'event': event,
            **payload,
        })
    except Exception as e:
        logger.debug(f'[ws_events] push_proposal_event swallowed: {e}')
