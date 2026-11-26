"""Shared test environment bootstrap.

The portal reads ``CHAIN_DIR`` and a few other settings at import time, so a
test module must set environment variables **before** importing ``app.main``.
The subprocess-per-module runner (``scripts/run_all_tests.py``) keeps global
state isolated between modules; this helper only removes the repeated
temp-directory boilerplate.

Note: a per-test pytest fixture that rebuilds the chain directory is not safe
yet, because ``app.config`` captures ``CHAIN_DIR`` at import time. That moves
to a real fixture once config is read lazily (batch U1/U2).
"""

from __future__ import annotations

import os
import tempfile


def isolated_chain_dir(prefix: str = "portal-test-", **env: str | None) -> str:
    """Create a throwaway chain dir, set ``CHAIN_DIR``, and apply extra env vars.

    Parameters:
        prefix: temp-dir prefix.
        env: extra environment variables. Pass ``None`` as the value to pop a
            variable instead of setting it.

    Returns:
        The temp root (the ``test-chain`` directory lives underneath it).
    """
    tmp = tempfile.mkdtemp(prefix=prefix)
    os.environ["CHAIN_DIR"] = os.path.join(tmp, "test-chain")
    # Batch U7.2: the request logger emits one JSON line per call, which is
    # right in production and pure noise across 200 tests. Modules that
    # assert on log content (test_observability) set this explicitly.
    os.environ.setdefault("PORTAL_LOG_LEVEL", "WARNING")
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return tmp
