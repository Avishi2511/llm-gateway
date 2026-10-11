import hashlib
import secrets

from app.errors import UnauthorizedError


def key_id_for(key: str) -> str:
    """Short non-reversible identifier used in logs, rate limits and usage rows."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


class KeyAuthenticator:
    def __init__(self, keys: list[str]):
        self._keys = [k.encode() for k in keys]

    def authenticate(self, authorization: str | None) -> str:
        """Return the key id for a valid 'Bearer <key>' header, else raise UnauthorizedError.

        Missing, malformed and wrong keys are indistinguishable to the caller.
        """
        scheme, _, candidate = (authorization or "").partition(" ")
        candidate_b = candidate.strip().encode()
        # Compare against every key (no early exit) in constant time per comparison.
        matched = False
        for key in self._keys:
            if secrets.compare_digest(candidate_b, key):
                matched = True
        if scheme.lower() != "bearer" or not candidate_b or not matched:
            raise UnauthorizedError()
        return key_id_for(candidate.strip())
