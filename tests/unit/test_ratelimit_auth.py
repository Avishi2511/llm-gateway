import pytest

from app.auth import KeyAuthenticator, key_id_for
from app.errors import RateLimitedError, UnauthorizedError
from app.ratelimit import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_limiter_allows_up_to_limit_then_blocks():
    clock = FakeClock()
    rl = RateLimiter(3, 60, clock)
    for _ in range(3):
        rl.check("k")
    with pytest.raises(RateLimitedError) as info:
        rl.check("k")
    assert info.value.headers["Retry-After"] == "60"


def test_limiter_resets_after_window_and_retry_after_counts_down():
    clock = FakeClock()
    rl = RateLimiter(2, 60, clock)
    rl.check("k")
    clock.now += 10
    rl.check("k")
    clock.now += 10
    with pytest.raises(RateLimitedError) as info:
        rl.check("k")
    assert info.value.headers["Retry-After"] == "40"  # oldest hit expires 40s from now
    clock.now += 40  # first hit leaves the window
    rl.check("k")
    with pytest.raises(RateLimitedError):
        rl.check("k")
    clock.now += 60  # everything expired
    rl.check("k")


def test_rejected_requests_do_not_extend_the_block():
    clock = FakeClock()
    rl = RateLimiter(1, 60, clock)
    rl.check("k")
    for _ in range(5):
        clock.now += 1
        with pytest.raises(RateLimitedError):
            rl.check("k")
    clock.now += 56  # 61s after the only counted request
    rl.check("k")


def test_limiter_is_per_key():
    rl = RateLimiter(1, 60, FakeClock())
    rl.check("a")
    rl.check("b")
    with pytest.raises(RateLimitedError):
        rl.check("a")


@pytest.mark.parametrize(
    "header",
    [None, "", "Bearer", "Bearer ", "Bearer wrong", "Basic k1-secret-value", "k1-secret-value", "Bearer k1-secret-valu"],
)
def test_bad_credentials_rejected_identically(header):
    auth = KeyAuthenticator(["k1-secret-value", "k2-secret-value"])
    with pytest.raises(UnauthorizedError) as info:
        auth.authenticate(header)
    assert info.value.public_message == "Missing or invalid API key."


def test_valid_keys_accepted_case_insensitive_scheme():
    auth = KeyAuthenticator(["k1-secret-value", "k2-secret-value"])
    assert auth.authenticate("Bearer k2-secret-value") == key_id_for("k2-secret-value")
    assert auth.authenticate("bearer k1-secret-value") == key_id_for("k1-secret-value")


def test_non_ascii_credentials_do_not_crash():
    with pytest.raises(UnauthorizedError):
        KeyAuthenticator(["abc"]).authenticate("Bearer ключ")


def test_key_id_is_short_and_not_the_key():
    kid = key_id_for("k1-secret-value")
    assert len(kid) == 8 and "secret" not in kid
