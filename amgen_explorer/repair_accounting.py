"""Durable, sanitized usage for repair operations, separate from run identity."""
from contextlib import contextmanager
import math
import time
import uuid

from .indexing import atomic_json


@contextmanager
def repair_accounting(config, run):
    """Checkpoint known usage before/after requests, including interrupted repairs.

    The retained run is never mutated. An unfinished request or operation leaves
    usage explicitly incomplete; reported tokens do not establish total cost.
    """
    operation = {'operation_id': uuid.uuid4().hex, 'operation': 'repair',
                 'run_id': run['run_id'], 'started_at': time.time(), 'status': 'in_progress',
                 'usage_scope': 'reported_embedding_tokens_only',
                 'usage': {'embed_total_tokens': 0},
                 'usage_may_include_unreported_retries': False, 'request_in_progress': False}
    path = config.root/'data/health/operations'/(operation['operation_id']+'.json')
    working = {**run, 'usage': {'embed_total_tokens': 0}, 'usage_may_include_unreported_retries': False}

    def checkpoint(manifest, pending):
        tokens = manifest.get('usage', {}).get('embed_total_tokens')
        valid = type(tokens) in (int, float) and math.isfinite(tokens) and tokens >= 0
        operation['usage'] = {'embed_total_tokens': tokens if valid else 0}
        operation['usage_may_include_unreported_retries'] = (not valid or
            bool(manifest.get('usage_may_include_unreported_retries')))
        operation['request_in_progress'] = pending
        operation['updated_at'] = time.time()
        atomic_json(path, operation)

    checkpoint(working, False)
    completed = False
    try:
        yield working, operation, checkpoint
        completed = True
    finally:
        operation['status'] = 'completed' if completed else 'interrupted'
        operation['finished_at'] = time.time()
        if operation['request_in_progress']:
            operation['usage_may_include_unreported_retries'] = True
        atomic_json(path, operation)
