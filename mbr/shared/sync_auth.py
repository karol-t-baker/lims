"""Shared-secret token auth for headless COA sync endpoints.

Env var: MBR_SYNC_TOKEN
  - Unset/empty -> endpoints return 503 (fail closed).
  - Set        -> request must send `X-Sync-Token: <value>`.

Constant-time comparison via hmac.compare_digest.
"""

import hmac
import os
from functools import wraps

from flask import jsonify, request


def sync_token_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = os.environ.get("MBR_SYNC_TOKEN", "")
        if not expected:
            return jsonify({"ok": False, "error": "sync disabled"}), 503
        got = request.headers.get("X-Sync-Token", "")
        if not hmac.compare_digest(got, expected):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapped
