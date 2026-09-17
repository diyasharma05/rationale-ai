"""Content-addressed disk cache for expensive deterministic computations.

Why disk and not lru_cache: the only genuinely slow step in an investigation is
fitting the per-region IsolationForests (~7 s, five models x 200 trees, plus a
~9 s scikit-learn import on the first call in a process). An in-process cache
loses all of that on every restart — including the restart right before a demo.
A content hash keyed on the *data* also means the entry is automatically
invalidated when the underlying rows change, and is automatically role-scoped:
the frame handed in has already been through the RBAC WHERE clause, so two
roles with different row visibility hash differently and cannot share an entry.
"""
import hashlib
import json
import os

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE, "data", "cache")

# Cache entries are tracked in git so a fresh clone (and the hosted deploy)
# starts warm; bump this whenever the computation itself changes.
MODEL_VERSION = "iforest-v1-200est-c0.03-seed42"


def frame_fingerprint(df: pd.DataFrame) -> str:
    """Stable digest of a DataFrame's contents, independent of row order.

    Row order is deliberately not part of the identity: a GROUP BY can return
    equal-keyed rows in whatever order the engine's parallel aggregation
    produced, which would otherwise make the digest differ run to run and the
    cache never hit. Order-insensitive combination (sum of per-row hashes)
    keeps the key stable while still changing if any value changes.
    """
    h = pd.util.hash_pandas_object(df, index=False).to_numpy()
    # uint64 addition already wraps mod 2**64 and is associative, so the sum
    # is order-independent without any extra modulo (which would overflow).
    digest = f"{int(h.sum())}-{int(h.size)}-{df.shape}-{list(df.columns)}"
    return hashlib.sha256(digest.encode()).hexdigest()[:16]


def key_for(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def _path(namespace: str, key: str) -> str:
    return os.path.join(CACHE_DIR, namespace, f"{key}.json")


def get(namespace: str, key: str):
    try:
        with open(_path(namespace, key), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None          # a missing or corrupt entry just means "recompute"


def put(namespace: str, key: str, value) -> None:
    path = _path(namespace, key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, default=str)
        os.replace(tmp, path)     # atomic: never leave a half-written entry
    except OSError:
        pass                      # a read-only filesystem must not break the run
