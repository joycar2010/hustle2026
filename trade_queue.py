"""Durable, per-account priority queue for paired trading intents.

Redis keeps the intent before QH starts broker work.  Close intents are always
claimed before open intents, while a separate processing list makes in-flight
work discoverable after a QH restart.
"""
import json
import os
import time
import uuid

import redis


TERMINAL_STATES = frozenset((
    "COMPLETED", "FAILED", "UNKNOWN", "MANUAL_REVIEW", "SINGLE_LEG_EXPOSED",
))

# These terminal outcomes keep the slot blocked until authoritative
# reconciliation.  SINGLE_LEG_EXPOSED is known broker risk rather than an
# unknown result, but it requires the same durable review latch.
DURABLE_REVIEW_STATES = frozenset((
    "UNKNOWN", "MANUAL_REVIEW", "SINGLE_LEG_EXPOSED",
))

# Queue updates arrive from the dispatcher, broker callbacks, and recovery
# tasks independently.  Keep the ordering here so a stale callback cannot
# move a job backwards even when it is not terminal yet.
STATE_RANK = {
    "QUEUED": 0,
    "CLAIMED": 5,
    "EXECUTING": 10,
    "DISPATCHING": 20,
}
STATE_RANK.update({state: 100 for state in TERMINAL_STATES})


class RedisTradeQueue:
    def __init__(self, redis_client, namespace="qh:tradeq:", ttl_sec=None):
        self.redis = redis_client
        self.namespace = namespace
        self.ttl_sec = max(3600, int(ttl_sec or os.getenv("QH_TRADE_QUEUE_TTL", "86400")))

    def _queue_key(self, username, kind):
        return "%squeue:%s:%s" % (self.namespace, username, kind)

    def _processing_key(self, username):
        return "%sprocessing:%s" % (self.namespace, username)

    def _job_key(self, job_id):
        return self.namespace + "job:" + str(self._text(job_id))

    def _batch_key(self, batch_id):
        return self.namespace + "batch:" + str(self._text(batch_id))

    def _slot_key(self, username, symbol, slot):
        return "%sslot:%s:%s:%d" % (self.namespace, username, symbol, int(slot))

    @staticmethod
    def _encode(value):
        if isinstance(value, (dict, list, tuple, bool)) or value is None:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        return str(value)

    @staticmethod
    def _text(value):
        """Normalize Redis byte responses without changing ordinary values."""
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return value

    @staticmethod
    def _state_rank(state):
        # Unknown persisted states are treated as almost terminal.  A repair
        # may still explicitly finish them, but ordinary progress updates must
        # not overwrite an unrecognized state with an earlier state.
        return STATE_RANK.get(str(state or "").upper(), 90)

    @staticmethod
    def _slot_value(value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _job_ids(cls, batch):
        """Return the authoritative, ordered job slots for a batch.

        Older batch records only have ``job_ids``.  Newer records also carry a
        ``total`` count; synthetic ``None`` entries preserve that count if a
        record was partially written or manually repaired.
        """
        raw = batch.get("job_ids") if isinstance(batch, dict) else []
        if not isinstance(raw, (list, tuple)):
            raw = []
        ids = []
        for value in raw:
            value = cls._text(value)
            ids.append(None if value in (None, "") else str(value))
        try:
            total = max(0, int(batch.get("total", len(ids))))
        except (TypeError, ValueError, AttributeError):
            total = len(ids)
        while len(ids) < total:
            ids.append(None)
        return ids

    @staticmethod
    def _job_specs(batch):
        specs = batch.get("job_specs") if isinstance(batch, dict) else []
        return specs if isinstance(specs, (list, tuple)) else []

    @classmethod
    def _missing_job(cls, batch, job_id, index):
        """Build a visible UNKNOWN record for an expired/missing job hash."""
        spec = {}
        for candidate in cls._job_specs(batch):
            if not isinstance(candidate, dict):
                continue
            if job_id is not None and str(cls._text(candidate.get("job_id"))) == str(job_id):
                spec = dict(candidate)
                break
            if job_id is None:
                try:
                    matches_seq = int(candidate.get("seq") or 0) == index + 1
                except (TypeError, ValueError):
                    matches_seq = False
                if matches_seq:
                    spec = dict(candidate)
                    break
        synthetic = job_id or "%s:missing:%d" % (batch.get("batch_id") or "batch", index + 1)
        spec.update({
            "job_id": synthetic,
            "batch_id": batch.get("batch_id"),
            "username": batch.get("username"),
            "kind": batch.get("kind"),
            "state": "UNKNOWN",
            "missing": True,
            "error": {"code": "JOB_MISSING"},
        })
        return spec

    @staticmethod
    def _decode_hash(raw):
        if not raw:
            return None
        try:
            items = dict(raw).items()
        except (TypeError, ValueError):
            return None
        out = {RedisTradeQueue._text(key): RedisTradeQueue._text(value)
               for key, value in items}
        for field in ("payload", "result", "error", "context"):
            value = out.get(field)
            if value is None:
                continue
            try:
                out[field] = json.loads(value)
            except (TypeError, ValueError):
                pass
        for field in ("slot", "seq"):
            if field in out:
                try:
                    out[field] = int(out[field])
                except (TypeError, ValueError):
                    pass
        return out

    def create_batch(self, username, kind, jobs, batch_id=None, source="manual",
                     request_fingerprint=None):
        if kind not in ("open", "close"):
            raise ValueError("kind must be open or close")
        batch_id = batch_id or uuid.uuid4().hex
        now = time.time()
        prepared = []
        job_specs = []
        pipe = self.redis.pipeline(transaction=True)
        for seq, item in enumerate(list(jobs or ()), 1):
            job = dict(item)
            job_id = str(self._text(job.get("job_id") or uuid.uuid4().hex))
            job.update({
                "job_id": job_id,
                "batch_id": batch_id,
                "username": username,
                "kind": kind,
                "source": source,
                "seq": seq,
                "state": "QUEUED",
                "created_at": now,
                "updated_at": now,
            })
            mapping = {key: self._encode(value) for key, value in job.items()}
            pipe.hset(self._job_key(job_id), mapping=mapping)
            pipe.expire(self._job_key(job_id), self.ttl_sec)
            pipe.lpush(self._queue_key(username, kind), job_id)
            slot = self._slot_value(job.get("slot"))
            symbol = job.get("symbol") or "XAUUSD"
            if slot > 0:
                pipe.setex(self._slot_key(username, symbol, slot), self.ttl_sec, job_id)
            prepared.append(job)
            # Keep enough immutable identity to render an expired job hash as
            # an UNKNOWN slot instead of silently shrinking the batch.
            job_specs.append({field: job[field] for field in (
                "job_id", "seq", "slot", "symbol", "kind", "op", "command_id",
                "pair_rid", "payload",
            ) if field in job})
        batch = {
            "batch_id": batch_id,
            "username": username,
            "kind": kind,
            "source": source,
            "created_at": now,
            "job_ids": [job["job_id"] for job in prepared],
            "total": len(prepared),
            "job_specs": job_specs,
        }
        if request_fingerprint:
            batch["request_fingerprint"] = str(request_fingerprint)
        pipe.setex(self._batch_key(batch_id), self.ttl_sec,
                   json.dumps(batch, ensure_ascii=False, separators=(",", ":")))
        pipe.sadd(self.namespace + "accounts", username)
        pipe.execute()
        return batch, prepared

    def get_job(self, job_id):
        if job_id in (None, ""):
            return None
        job_id = self._text(job_id)
        return self._decode_hash(self.redis.hgetall(self._job_key(str(job_id))))

    def update_job(self, job_id, state=None, **fields):
        if job_id in (None, ""):
            return None
        job_id = str(self._text(job_id))
        key = self._job_key(job_id)
        requested_state = None if state is None else str(self._text(state)).upper()
        # A late worker callback must never move a terminal job back to an
        # in-flight state (or replace its result).  WATCH makes the check and
        # update atomic across multiple queue workers.
        for _attempt in range(5):
            pipe = self.redis.pipeline(transaction=True)
            try:
                pipe.watch(key)
                current = self._decode_hash(pipe.hgetall(key))
                if not current:
                    pipe.unwatch()
                    return None
                current_state = str(current.get("state") or "").upper()
                if current_state in TERMINAL_STATES:
                    current["state"] = current_state
                    pipe.unwatch()
                    return current
                if (requested_state is not None and
                        self._state_rank(requested_state) < self._state_rank(current_state)):
                    # A delayed EXECUTING/DISPATCHING callback must not erase a
                    # newer state.  Reject the whole update so stale result or
                    # error fields cannot overwrite the current snapshot.
                    pipe.unwatch()
                    return current
                mapping = {"updated_at": str(time.time())}
                if requested_state is not None:
                    mapping["state"] = requested_state
                mapping.update({key: self._encode(value) for key, value in fields.items()})
                pipe.multi()
                pipe.hset(key, mapping=mapping)
                pipe.expire(key, self.ttl_sec)
                pipe.execute()
                return self.get_job(job_id)
            except redis.exceptions.WatchError:
                continue
            finally:
                pipe.reset()
        # A contention storm should not turn a known job into an untracked
        # one.  Returning the latest value lets callers retain its state.
        return self.get_job(job_id)

    def claim(self, username):
        processing = self._processing_key(username)
        # Priority is checked on every claim, so a close can overtake queued opens.
        for kind in ("close", "open"):
            queue_key = self._queue_key(username, kind)
            while True:
                job_id = self.redis.rpoplpush(queue_key, processing)
                if not job_id:
                    break
                job_id = str(self._text(job_id))
                job = self.get_job(job_id)
                if not job:
                    # Expired hashes must not wedge the processing list or
                    # prevent later jobs from being claimed.
                    self.redis.lrem(processing, 0, job_id)
                    continue
                if str(job.get("state") or "").upper() in TERMINAL_STATES:
                    self.redis.lrem(processing, 0, job_id)
                    continue
                state = str(job.get("state") or "").upper()
                if state not in STATE_RANK:
                    # Fail closed on a corrupt state instead of dispatching an
                    # untracked broker operation.
                    self.update_job(job_id, state="UNKNOWN",
                                    error={"code": "INVALID_JOB_STATE", "state": state})
                    self.redis.lrem(processing, 0, job_id)
                    continue
                return job
        return None

    def finish(self, job_id, state, **fields):
        state = str(self._text(state or "")).upper()
        if state not in TERMINAL_STATES:
            raise ValueError("finish state must be terminal")
        job_id = None if job_id in (None, "") else str(self._text(job_id))
        job = self.update_job(job_id, state=state, **fields)
        if job:
            self._cleanup_terminal_job(job_id, job)
        return job

    def _cleanup_terminal_job(self, job_id, job, remove_queued=False):
        """Batch terminal cleanup while retaining the slot ownership check."""
        actual_state = str(job.get("state") or "").upper()
        durable_review = actual_state in DURABLE_REVIEW_STATES
        username = job.get("username") or ""
        slot = self._slot_value(job.get("slot"))
        slot_key = (self._slot_key(username, job.get("symbol") or "XAUUSD", slot)
                    if slot > 0 else None)

        # These operations are independent. MULTI/EXEC collapses their network
        # cost and atomically publishes the durable-review/list snapshot.
        pipe = self.redis.pipeline(transaction=True)
        if durable_review:
            pipe.persist(self._job_key(job_id))
        pipe.lrem(self._processing_key(username), 0, job_id)
        if remove_queued:
            kind = job.get("kind") if job.get("kind") in ("open", "close") else "close"
            pipe.lrem(self._queue_key(username, kind), 0, job_id)
        if slot_key:
            pipe.get(slot_key)
        results = pipe.execute()

        if slot_key and self._text(results[-1]) == job_id:
            if durable_review:
                self.redis.persist(slot_key)
            else:
                # Keep a resolved terminal state briefly so another browser sees it.
                self.redis.expire(slot_key, 30)

    def update_review_job(self, job_id, **fields):
        """Persist recovery evidence without prematurely leaving a review state."""
        if job_id in (None, ""):
            return None
        job_id = str(self._text(job_id))
        key = self._job_key(job_id)
        for _attempt in range(5):
            pipe = self.redis.pipeline(transaction=True)
            try:
                pipe.watch(key)
                current = self._decode_hash(pipe.hgetall(key))
                if not current:
                    pipe.unwatch()
                    return None
                current_state = str(current.get("state") or "").upper()
                if current_state not in DURABLE_REVIEW_STATES:
                    pipe.unwatch()
                    return current
                mapping = {"updated_at": str(time.time())}
                mapping.update({name: self._encode(value)
                                for name, value in fields.items()})
                pipe.multi()
                pipe.hset(key, mapping=mapping)
                pipe.persist(key)
                pipe.execute()
                return self.get_job(job_id)
            except redis.exceptions.WatchError:
                continue
            finally:
                pipe.reset()
        return self.get_job(job_id)

    def reconcile_finish(self, job_id, state, **fields):
        """Promote a durable review state only after external truth proof."""
        state = str(self._text(state or "")).upper()
        if state not in TERMINAL_STATES:
            raise ValueError("reconciled state must be terminal")
        if job_id in (None, ""):
            return None
        job_id = str(self._text(job_id))
        key = self._job_key(job_id)
        job = None
        for _attempt in range(5):
            pipe = self.redis.pipeline(transaction=True)
            try:
                pipe.watch(key)
                current = self._decode_hash(pipe.hgetall(key))
                if not current:
                    pipe.unwatch()
                    return None
                current_state = str(current.get("state") or "").upper()
                if current_state == state:
                    pipe.unwatch()
                    job = current
                    break
                if current_state not in DURABLE_REVIEW_STATES:
                    pipe.unwatch()
                    job = current
                    break
                mapping = {"state": state, "updated_at": str(time.time()),
                           "reconciled_at": str(time.time())}
                mapping.update({name: self._encode(value) for name, value in fields.items()})
                pipe.multi()
                pipe.hset(key, mapping=mapping)
                pipe.expire(key, self.ttl_sec)
                pipe.execute()
                job = self.get_job(job_id)
                break
            except redis.exceptions.WatchError:
                continue
            finally:
                pipe.reset()
        if not job:
            job = self.get_job(job_id)
        if not job:
            return None
        self._cleanup_terminal_job(job_id, job, remove_queued=True)
        return job

    def requeue(self, job_id, reason="process_restart"):
        if job_id in (None, ""):
            return None
        job_id = str(self._text(job_id))
        key = self._job_key(job_id)
        # Recovery races with broker callbacks.  Watch the job hash while
        # moving it back to the queue so a callback that wins the race leaves
        # the terminal state untouched.
        for _attempt in range(5):
            pipe = self.redis.pipeline(transaction=True)
            try:
                pipe.watch(key)
                job = self._decode_hash(pipe.hgetall(key))
                if not job:
                    pipe.unwatch()
                    return None
                if str(job.get("state") or "").upper() in TERMINAL_STATES:
                    job["state"] = str(job.get("state") or "").upper()
                    pipe.unwatch()
                    return job
                username = self._text(job.get("username") or "")
                kind = str(self._text(job.get("kind") or "open"))
                if kind not in ("open", "close"):
                    kind = "open"
                queue_key = self._queue_key(username, kind)
                processing_key = self._processing_key(username)
                pipe.multi()
                pipe.lrem(processing_key, 0, job_id)
                # Avoid duplicate queue entries after repeated recovery scans.
                pipe.lrem(queue_key, 0, job_id)
                # Recovered processing work is older than still-pending items.
                pipe.rpush(queue_key, job_id)
                pipe.hset(key, mapping={
                    "state": "QUEUED", "updated_at": str(time.time()),
                    "recovery_reason": reason,
                })
                pipe.expire(key, self.ttl_sec)
                pipe.execute()
                return self.get_job(job_id)
            except redis.exceptions.WatchError:
                continue
            finally:
                pipe.reset()
        return self.get_job(job_id)

    @staticmethod
    def _batch_status_payload(batch, jobs):
        batch = dict(batch or {})
        expected = RedisTradeQueue._job_ids(batch)
        # Keep one response entry per expected job, even when Redis expired a
        # hash or a partial pipeline response omitted it.
        by_id = {}
        for job in jobs or ():
            if not isinstance(job, dict):
                continue
            job = dict(job)
            job_id = RedisTradeQueue._text(job.get("job_id"))
            if job_id not in (None, ""):
                by_id.setdefault(str(job_id), []).append(job)
        if not expected and by_id:
            expected = list(by_id)
        ordered = []
        missing = []
        for index, expected_id in enumerate(expected):
            bucket = by_id.get(str(expected_id), []) if expected_id is not None else []
            job = bucket.pop(0) if bucket else None
            if not job:
                job = RedisTradeQueue._missing_job(batch, expected_id, index)
                missing.append(job["job_id"])
            job.setdefault("job_id", expected_id)
            job.setdefault("batch_id", batch.get("batch_id"))
            job.setdefault("username", batch.get("username"))
            job.setdefault("kind", batch.get("kind"))
            if not job.get("state"):
                job["state"] = "UNKNOWN"
                job.setdefault("error", {"code": "JOB_STATE_MISSING"})
            ordered.append(job)

        # A legacy/corrupt record can contain decoded jobs but no job_ids.  Do
        # not silently discard those entries; they are still accounted for.
        if not expected and not ordered:
            ordered = [dict(job) for job in (jobs or ()) if isinstance(job, dict)]
        try:
            declared_total = max(0, int(batch.get("total", len(expected))))
        except (TypeError, ValueError):
            declared_total = len(expected)
        total = max(declared_total, len(expected), len(ordered))
        counts = {}
        for job in ordered:
            state = str(job.get("state") or "UNKNOWN").upper()
            job["state"] = state
            counts[state] = counts.get(state, 0) + 1
        terminal = (total == 0 or
                    (len(ordered) == total and all(job.get("state") in TERMINAL_STATES
                                                   for job in ordered)))
        ok = terminal and total == len(ordered) and all(
            job.get("state") == "COMPLETED" for job in ordered
        )
        batch.update({
            "jobs": ordered,
            "counts": counts,
            "terminal": terminal,
            "ok": ok,
            "total": total,
            "missing": len(missing),
            "missing_job_ids": missing,
        })
        return batch

    def batch_status_many(self, batch_ids):
        """Read several batches with two Redis round trips, preserving request order."""
        if not batch_ids:
            return []
        batch_ids = list(dict.fromkeys(str(self._text(value)) for value in batch_ids if value))
        if not batch_ids:
            return []

        pipe = self.redis.pipeline(transaction=False)
        for batch_id in batch_ids:
            pipe.get(self._batch_key(batch_id))

        batches = []
        for batch_id, raw in zip(batch_ids, pipe.execute()):
            if not raw:
                continue
            try:
                decoded = raw if isinstance(raw, dict) else json.loads(raw)
                if isinstance(decoded, dict):
                    batches.append((batch_id, decoded))
            except (TypeError, ValueError):
                continue

        pipe = self.redis.pipeline(transaction=False)
        requests = []
        expected_by_batch = []
        for batch_index, (_, batch) in enumerate(batches):
            expected = self._job_ids(batch)
            expected_by_batch.append(expected)
            for item_index, job_id in enumerate(expected):
                if job_id is None:
                    continue
                pipe.hgetall(self._job_key(str(job_id)))
                requests.append((batch_index, item_index))

        raw_results = pipe.execute() if requests else []
        decoded = [[None for _ in expected] for expected in expected_by_batch]
        for (batch_index, item_index), raw in zip(requests, raw_results):
            decoded[batch_index][item_index] = self._decode_hash(raw)

        statuses = []
        for batch_index, (_, batch) in enumerate(batches):
            statuses.append(self._batch_status_payload(batch, decoded[batch_index]))
        return statuses

    def batch_status(self, batch_id):
        statuses = self.batch_status_many([batch_id])
        return statuses[0] if statuses else None

    def slot_states(self, username, symbol, slots):
        slots = [self._slot_value(slot) for slot in slots if slot is not None]
        slots = [slot for slot in slots if slot > 0]
        if not slots:
            return []
        pipe = self.redis.pipeline(transaction=False)
        for slot in slots:
            pipe.get(self._slot_key(username, symbol, slot))
        job_ids = [self._text(value) for value in pipe.execute()]
        pipe = self.redis.pipeline(transaction=False)
        present = [(index, job_id) for index, job_id in enumerate(job_ids) if job_id]
        for _, job_id in present:
            pipe.hgetall(self._job_key(str(job_id)))
        raw = iter(pipe.execute() if present else [])
        out = []
        for index, job_id in present:
            job = self._decode_hash(next(raw, None))
            if not job:
                # Keep the slot visible long enough for the frontend to clear
                # its busy state instead of treating a missing hash as an empty
                # slot and allowing a duplicate order.
                job = {
                    "job_id": str(job_id), "username": username,
                    "symbol": symbol, "slot": slots[index], "state": "UNKNOWN",
                    "missing": True, "error": {"code": "JOB_MISSING"},
                }
            else:
                job.setdefault("job_id", str(job_id))
                job.setdefault("username", username)
                job.setdefault("symbol", symbol)
                job.setdefault("slot", slots[index])
                if not job.get("state"):
                    job["state"] = "UNKNOWN"
                    job.setdefault("error", {"code": "JOB_STATE_MISSING"})
            out.append(job)
        return out

    def accounts(self):
        return sorted(str(self._text(value)) for value in
                      (self.redis.smembers(self.namespace + "accounts") or []))

    def recoverable_sagas(self):
        """Return durable open sagas which still need terminal reconciliation."""
        jobs = []
        for key in self.redis.scan_iter(match=self.namespace + "job:*"):
            job = self._decode_hash(self.redis.hgetall(key))
            if not job or str(job.get("op") or "") != "open_pair":
                continue
            state = str(job.get("state") or "").upper()
            raw_result = job.get("result") if isinstance(job.get("result"), dict) else {}
            evidence = raw_result.get("evidence")
            result = (evidence if raw_result.get("reconciled") and
                      isinstance(evidence, dict) else raw_result)
            durable = (str(job.get("saga_durable") or "").lower() in ("1", "true") or
                       bool(result.get("saga_durable")))
            if durable and state in (
                    "DISPATCHING", "UNKNOWN", "MANUAL_REVIEW", "SINGLE_LEG_EXPOSED"):
                jobs.append(job)
        return jobs

    def processing(self, username):
        ids = [self._text(value) for value in
               (self.redis.lrange(self._processing_key(username), 0, -1) or [])]
        out = []
        for job_id in ids:
            job = self.get_job(job_id)
            if job:
                out.append(job)
            else:
                # An expired hash cannot be recovered; remove only this stale
                # list entry so other in-flight jobs remain discoverable.
                self.redis.lrem(self._processing_key(username), 0, str(job_id))
        return out

    def depths(self, username):
        return {
            "close": int(self.redis.llen(self._queue_key(username, "close")) or 0),
            "open": int(self.redis.llen(self._queue_key(username, "open")) or 0),
            "processing": int(self.redis.llen(self._processing_key(username)) or 0),
        }

    def queued_depths_many(self, usernames):
        """Read close/open depths for an account set in one Redis round trip."""
        names = [str(self._text(value)) for value in (usernames or ())]
        if not names:
            return {}
        pipe = self.redis.pipeline(transaction=False)
        for username in names:
            pipe.llen(self._queue_key(username, "close"))
            pipe.llen(self._queue_key(username, "open"))
        values = pipe.execute()
        return {
            username: {
                "close": int(values[index * 2] or 0),
                "open": int(values[index * 2 + 1] or 0),
            }
            for index, username in enumerate(names)
        }

    def claim_consumer_lease(self, username, owner, ttl=10):
        key = "%sconsumer:%s" % (self.namespace, username)
        script = """
        local current = redis.call('get', KEYS[1])
        if not current or current == ARGV[1] then
            redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
            return 1
        end
        return 0
        """
        return bool(self.redis.eval(script, 1, key, owner, str(max(2, int(ttl)))))
