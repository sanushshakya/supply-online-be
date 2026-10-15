import hashlib
import hmac
import time


def _mac(secret, t, body):
    return hmac.new(
        secret.encode(), f"{t}.".encode() + body, hashlib.sha256
    ).hexdigest()


def sign(secret, body, now=None):
    """Return the X-Integration-Signature header value for ``body``."""
    t = int(time.time()) if now is None else int(now)
    return f"t={t},v1={_mac(secret, t, body)}"


def verify(secret, body, header, now=None, tolerance=300):
    """True only if ``header`` is a fresh, valid signature of ``body``."""
    if not secret or not header or not isinstance(header, str):
        return False
    try:
        parts = dict(p.strip().split("=", 1) for p in header.split(","))
        t = int(parts["t"])
        given = parts["v1"]
    except (ValueError, KeyError):
        return False
    current = int(time.time()) if now is None else int(now)
    if abs(current - t) > tolerance:
        return False
    return hmac.compare_digest(_mac(secret, t, body), given)
