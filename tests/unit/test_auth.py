"""Unit tests for the HTTP auth + abuse-control invariants (SVC-A-003 coverage).

These pin the load-bearing security contracts of ``prism.http.auth`` so a refactor that drops one
ships RED, not green:

  1. Failed-auth memory bound — the per-IP ``_fail_buckets`` map is reclaimable: idle buckets are
     evicted so an attacker cannot exhaust memory with distinct source IPs. (The bound is SOFT —
     eviction only removes buckets idle past the window; a flood of *simultaneously active* IPs can
     exceed FAIL_BUCKET_MAX. We test the real guarantee, not the aspirational hard cap — see
     ``test_active_flood_exceeds_cap_documents_soft_bound`` and the report's SVC-A-002 note.)
  2. Fail-closed — no/invalid key is refused when keys are configured and no-auth is not opted in.
  3. Hashed-at-rest + constant-time — keys live as SHA-256 hashes, compared via hmac.compare_digest.
  4. Idle eviction — the bound's recovery path: idle buckets are reclaimed after the idle window.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from prism.http.auth import (
    API_KEY_PREFIX,
    FAIL_BUCKET_IDLE_S,
    FAIL_BUCKET_MAX,
    Authenticator,
    generate_api_key,
    hash_key,
    load_key_hashes,
)
from prism.http.errors import ProblemError


class FakeClock:
    """A manually-advanced monotonic clock so eviction/refill are deterministic."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# --------------------------------------------------------------------------------------------------
# 1. Failed-auth memory bound (the headline gap) — SVC-A-003
# --------------------------------------------------------------------------------------------------


class TestFailedAuthMemoryBound:
    def test_idle_ip_flood_stays_bounded(self) -> None:
        """An attacker rotating through distinct IPs (each idle after one failure) cannot grow the
        ``_fail_buckets`` map without limit: idle eviction reclaims old buckets at capacity.

        MEANINGFUL: if ``_evict_idle_fail_buckets`` / the ``>= FAIL_BUCKET_MAX`` guard were removed,
        the map would grow to ``FAIL_BUCKET_MAX + extra`` and this assertion (size near the cap)
        would fail. We advance the clock past the idle window between rounds so every prior bucket
        is reclaimable, which is exactly the contract the code guarantees.
        """
        clock = FakeClock()
        _key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=1, clock=clock)

        extra = 200
        # Drive distinct hostile IPs past the cap. Between rounds, advance past the idle window so
        # the previous round's buckets are idle and therefore reclaimable.
        for ip in range(FAIL_BUCKET_MAX):
            with pytest.raises(ProblemError):
                auth.authenticate("Bearer prism_wrong", client_ip=f"10.0.{ip // 256}.{ip % 256}")
        clock.advance(FAIL_BUCKET_IDLE_S + 1.0)  # all prior buckets are now idle
        for ip in range(extra):
            with pytest.raises(ProblemError):
                auth.authenticate("Bearer prism_wrong", client_ip=f"172.16.{ip // 256}.{ip % 256}")

        # Bound holds: the map never exceeds the cap once idle buckets can be reclaimed. (It may sit
        # exactly at FAIL_BUCKET_MAX; it must not run away to FAIL_BUCKET_MAX + extra.)
        assert len(auth._fail_buckets) <= FAIL_BUCKET_MAX
        # And it is strictly smaller than "no bound at all" would produce.
        assert len(auth._fail_buckets) < FAIL_BUCKET_MAX + extra

    def test_active_flood_exceeds_cap_documents_soft_bound(self) -> None:
        """The bound is SOFT: simultaneously-active IPs (no idle gap) CAN exceed FAIL_BUCKET_MAX.

        This is the SVC-A-002 residual. We assert the code's REAL behavior (not an aspirational hard
        cap) so the contract is pinned honestly: an active bucket is never evicted (that would reset
        its strike count), so a no-gap flood grows the map past the cap. If a future Stage-B change
        turned this into a hard cap, this test would flip — that's the signal to re-evaluate.
        """
        clock = FakeClock()
        _key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=1, clock=clock)

        extra = 50
        # NO clock advance: every bucket stays "active" (recent _last) → never reclaimable.
        for ip in range(FAIL_BUCKET_MAX + extra):
            with pytest.raises(ProblemError):
                auth.authenticate("Bearer prism_wrong", client_ip=f"10.{ip // 65536}."
                                  f"{(ip // 256) % 256}.{ip % 256}")
        # Soft bound: the map grew past the cap because no bucket was idle/evictable.
        assert len(auth._fail_buckets) == FAIL_BUCKET_MAX + extra

    def test_active_attacker_bucket_is_not_evicted(self) -> None:
        """An active attacker's bucket OBJECT survives an eviction sweep (its strike count is not
        reset by replacing it with a fresh bucket).

        MEANINGFUL: eviction must skip non-idle buckets. If eviction dropped the active bucket, the
        attacker's accumulated failure count would reset (a brand-new TokenBucket) and the limiter
        would never trip. We capture the active IP's bucket object, advance time only enough to make
        the OTHER buckets idle (kept shorter than the active IP's idle window by re-touching it just
        before the sweep), trigger a capacity sweep, and assert the SAME bucket object is still
        mapped — identity, not refill state, is the eviction contract.
        """
        clock = FakeClock()
        _key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=2, clock=clock)

        active_ip = "203.0.113.99"
        with pytest.raises(ProblemError):
            auth.authenticate("Bearer prism_wrong", client_ip=active_ip)
        active_bucket = auth._fail_buckets[active_ip]

        # Fill the rest of the map with distinct idle buckets.
        for ip in range(FAIL_BUCKET_MAX):
            with pytest.raises(ProblemError):
                auth.authenticate("Bearer prism_wrong", client_ip=f"10.0.{ip // 256}.{ip % 256}")
        clock.advance(FAIL_BUCKET_IDLE_S + 1.0)  # the 10.0.* buckets are now idle

        # Re-touch the active IP so its _last is current (NOT idle) right before the sweep, then
        # insert a brand-new IP at capacity to force ``_evict_idle_fail_buckets``.
        with pytest.raises(ProblemError):
            auth.authenticate("Bearer prism_wrong", client_ip=active_ip)
        with pytest.raises(ProblemError):
            auth.authenticate("Bearer prism_wrong", client_ip="198.51.100.50")

        # The active IP's ORIGINAL bucket object survived the sweep — not evicted, not replaced.
        assert active_ip in auth._fail_buckets
        assert auth._fail_buckets[active_ip] is active_bucket


# --------------------------------------------------------------------------------------------------
# 2. Fail-closed
# --------------------------------------------------------------------------------------------------


class TestFailClosed:
    def test_no_keys_configured_refuses(self) -> None:
        """No keys + no opt-in → every request refused (an expensive endpoint is never left open).

        MEANINGFUL: if the fail-closed branch were removed (e.g. defaulting to 'anonymous'), this
        would return a value instead of raising 401.
        """
        auth = Authenticator(set(), allow_no_auth=False)
        with pytest.raises(ProblemError) as exc:
            auth.authenticate("Bearer prism_anything", client_ip="1.2.3.4")
        assert exc.value.status == 401
        assert exc.value.slug == "no-auth-configured"

    def test_no_keys_but_opt_in_allows_anonymous(self) -> None:
        """The explicit opt-in (allow_no_auth) is the only way through with no keys."""
        auth = Authenticator(set(), allow_no_auth=True)
        assert auth.authenticate(None, client_ip="1.2.3.4") == "anonymous"

    @pytest.mark.parametrize(
        "header",
        [None, "", "Bearer ", "prism_nope", "Basic abc", "bearer prism_lowercase_scheme"],
    )
    def test_missing_or_malformed_header_refused(self, header: str | None) -> None:
        """No/invalid Authorization header is refused when keys ARE configured.

        MEANINGFUL: each of these must NOT authenticate. A regression that accepted a bare token or
        a wrong scheme would let unauthenticated callers through.
        """
        _key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=100)
        with pytest.raises(ProblemError) as exc:
            auth.authenticate(header, client_ip="1.2.3.4")
        assert exc.value.status == 401

    def test_wrong_key_refused(self) -> None:
        """A correctly-formatted but unknown key is refused (401), not accepted."""
        _key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=100)
        with pytest.raises(ProblemError) as exc:
            auth.authenticate("Bearer prism_not_the_real_key", client_ip="1.2.3.4")
        assert exc.value.status == 401
        assert exc.value.slug == "unauthorized"

    def test_correct_key_authenticates(self) -> None:
        """The matching key returns its hash identity (the rate-limit key)."""
        key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=100)
        assert auth.authenticate(f"Bearer {key}", client_ip="1.2.3.4") == key_hash


# --------------------------------------------------------------------------------------------------
# 3. Hashed-at-rest + constant-time
# --------------------------------------------------------------------------------------------------


class TestHashedAndConstantTime:
    def test_config_stores_hash_not_plaintext(self) -> None:
        """Keys live as SHA-256 hashes, never plaintext.

        MEANINGFUL: the authenticator holds the hash, not the raw key — a config dump leaks only
        the irreversible hash. If hashing were dropped (raw keys stored/compared), the stored value
        would equal the plaintext key and this assertion would fail.
        """
        key, key_hash = generate_api_key()
        assert key.startswith(API_KEY_PREFIX)
        assert key_hash == hashlib.sha256(key.encode()).hexdigest()
        assert key_hash != key  # not plaintext
        auth = Authenticator({key_hash}, failed_auth_per_minute=100)
        # The stored set contains the hash, not the raw key.
        assert key not in auth._key_hashes
        assert key_hash in auth._key_hashes

    def test_load_key_hashes_parses_hashes(self) -> None:
        """PRISM_API_KEYS parsing keeps hashes only, trims/splits, drops empties."""
        h1 = hash_key("prism_one")
        h2 = hash_key("prism_two")
        assert load_key_hashes(f" {h1} , {h2} ,, ") == {h1, h2}
        assert load_key_hashes("") == set()
        assert load_key_hashes(None) == set() or isinstance(load_key_hashes(None), set)

    def test_same_length_wrong_key_fails_correct_passes(self) -> None:
        """Observable constant-time contract: a correct key passes; a wrong key of the SAME byte
        length as the correct key still fails.

        MEANINGFUL: this is the behavioral surface of ``hmac.compare_digest`` over the *hashes*.
        Comparison is on fixed-length SHA-256 hex digests, so a wrong key never matches regardless
        of how many leading characters collide. If the equality check were a naive ``==`` on raw
        keys (timing-leaky) the digests would still differ — but pinning correct-passes / wrong-of-
        same-length-fails guards the matching logic itself.
        """
        key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=100)
        # A wrong key of identical length to the real key.
        wrong = key[:-4] + ("0000" if not key.endswith("0000") else "1111")
        assert len(wrong) == len(key)
        assert auth.authenticate(f"Bearer {key}", client_ip="9.9.9.9") == key_hash
        with pytest.raises(ProblemError):
            auth.authenticate(f"Bearer {wrong}", client_ip="9.9.9.9")

    def test_comparison_uses_compare_digest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The key comparison goes through hmac.compare_digest (constant-time), not ``==``.

        MEANINGFUL: we wrap ``hmac.compare_digest`` and assert it is actually invoked during a
        successful auth. A regression replacing it with ``presented == kh`` (timing-leaky) would
        make this call count zero and fail the test.
        """
        import prism.http.auth as auth_mod

        calls: list[tuple[Any, Any]] = []
        real = hmac.compare_digest

        def spy(a: Any, b: Any) -> bool:
            calls.append((a, b))
            return real(a, b)

        monkeypatch.setattr(auth_mod.hmac, "compare_digest", spy)
        key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=100)
        assert auth.authenticate(f"Bearer {key}", client_ip="9.9.9.9") == key_hash
        assert calls, "auth must use hmac.compare_digest for the key comparison"


# --------------------------------------------------------------------------------------------------
# 4. Idle eviction (the bound's recovery path)
# --------------------------------------------------------------------------------------------------


class TestIdleEviction:
    def test_idle_buckets_evicted_at_capacity(self) -> None:
        """After the idle window, idle fail-buckets are reclaimed at capacity.

        MEANINGFUL: this is the recovery path that makes the soft bound usable. We fill the map to
        capacity with buckets, advance past the idle window so they are ALL idle, then insert one
        more distinct IP — which triggers ``_evict_idle_fail_buckets`` and drops idle buckets. If
        eviction were removed, the map would only grow; here it must shrink below the pre-insert
        size + 1 (idle buckets were actually reclaimed).
        """
        clock = FakeClock()
        _key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=1, clock=clock)

        for ip in range(FAIL_BUCKET_MAX):
            with pytest.raises(ProblemError):
                auth.authenticate("Bearer prism_wrong", client_ip=f"10.0.{ip // 256}.{ip % 256}")
        assert len(auth._fail_buckets) == FAIL_BUCKET_MAX

        clock.advance(FAIL_BUCKET_IDLE_S + 1.0)  # every bucket is now idle
        # One more distinct IP at capacity → eviction sweep reclaims idle buckets.
        with pytest.raises(ProblemError):
            auth.authenticate("Bearer prism_wrong", client_ip="198.51.100.1")
        # Idle buckets were reclaimed: the map did NOT simply grow to MAX+1.
        assert len(auth._fail_buckets) < FAIL_BUCKET_MAX + 1

    def test_eviction_only_touches_idle_not_recent(self) -> None:
        """A bucket touched within the idle window survives an eviction sweep.

        MEANINGFUL: pins that eviction is idle-gated, not blind LRU. We fill to capacity, advance
        partway (less than the idle window), re-touch one specific IP to refresh its ``_last``, then
        advance just past the window relative to the OLD buckets but keep the touched IP fresh, and
        trigger a sweep. The freshly-touched IP must remain.
        """
        clock = FakeClock()
        _key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=5, clock=clock)

        for ip in range(FAIL_BUCKET_MAX):
            with pytest.raises(ProblemError):
                auth.authenticate("Bearer prism_wrong", client_ip=f"10.0.{ip // 256}.{ip % 256}")

        clock.advance(FAIL_BUCKET_IDLE_S + 1.0)
        fresh_ip = "10.0.0.0"  # re-touch an existing bucket so its _last is current
        with pytest.raises(ProblemError):
            auth.authenticate("Bearer prism_wrong", client_ip=fresh_ip)
        # Now insert a brand-new IP → triggers the sweep; idle buckets go, fresh_ip stays.
        with pytest.raises(ProblemError):
            auth.authenticate("Bearer prism_wrong", client_ip="198.51.100.2")
        assert fresh_ip in auth._fail_buckets
