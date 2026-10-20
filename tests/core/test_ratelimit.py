"""Limitation de débit : limite par défaut, clés, exemptions, et panne du stockage."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.core import ratelimit
from app.core.ratelimit import (
    FailOpenLimiter,
    RateLimitMiddleware,
    ip_key,
    rate_limit_exceeded_handler,
    user_key,
)
from tests.helpers.auth import bearer


def build_app(limiter: Limiter) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(RateLimitMiddleware)

    @app.get("/plain")
    def plain(request: Request):
        return {"ok": True}

    @app.get("/exempt")
    @limiter.exempt
    def exempt(request: Request):
        return {"ok": True}

    @app.get("/own-limit")
    @limiter.limit("2/minute")
    def own_limit(request: Request):
        return {"ok": True}

    return app


def memory_limiter(default: str = "3/minute", key=ip_key) -> Limiter:
    return FailOpenLimiter(
        key_func=key, storage_uri="memory://", default_limits=[default], swallow_errors=True
    )


def test_default_limit_applies_to_routes_without_their_own_and_uses_the_api_error_format():
    client = TestClient(build_app(memory_limiter("3/minute")))

    codes = [client.get("/plain").status_code for _ in range(5)]
    refused = client.get("/plain")

    assert codes == [200, 200, 200, 429, 429]
    assert refused.json()["error"]["code"] == "rate_limited"
    assert refused.json()["error"]["message"] == "Trop de requêtes, réessayez plus tard"
    assert int(refused.headers["Retry-After"]) > 0


def test_exempt_routes_are_never_limited():
    client = TestClient(build_app(memory_limiter("1/minute")))
    assert {client.get("/exempt").status_code for _ in range(20)} == {200}


def test_a_route_with_its_own_limit_is_not_counted_against_the_default():
    client = TestClient(build_app(memory_limiter("100/minute")))
    assert [client.get("/own-limit").status_code for _ in range(3)] == [200, 200, 429]


def test_disabled_limiter_lets_everything_through():
    limiter = memory_limiter("1/minute")
    limiter.enabled = False
    client = TestClient(build_app(limiter))
    assert {client.get("/plain").status_code for _ in range(10)} == {200}


def test_the_api_stays_up_when_the_counter_store_is_down():
    """Redis injoignable : on laisse passer (et on journalise) au lieu de renvoyer 500 partout."""
    broken = FailOpenLimiter(
        key_func=ip_key,
        storage_uri="redis://127.0.0.1:1/0",
        default_limits=["1/minute"],
        swallow_errors=True,
    )
    client = TestClient(build_app(broken), raise_server_exceptions=False)

    assert {client.get("/plain").status_code for _ in range(5)} == {200}
    assert {client.get("/own-limit").status_code for _ in range(5)} == {200}


# ---- Clés de comptage ------------------------------------------------------------------


def make_request(headers=None, client=("1.2.3.4", 5000)) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "client": client, "method": "GET", "path": "/"})


def test_user_key_separates_users_sharing_an_ip(users):
    """Derrière le NAT d'un opérateur mobile, des centaines d'utilisateurs partagent une IP."""
    a, b = users.user(), users.user()
    key_a = user_key(make_request(bearer(a)))
    key_b = user_key(make_request(bearer(b)))
    assert key_a != key_b and key_a.startswith("user:")


def test_user_key_falls_back_to_the_ip_for_anonymous_or_forged_tokens():
    assert user_key(make_request()) == "ip:1.2.3.4"
    assert user_key(make_request({"Authorization": "Bearer garbage"})) == "ip:1.2.3.4"
    assert user_key(make_request({"Authorization": "Basic abc"})) == "ip:1.2.3.4"


def test_a_forged_token_cannot_buy_a_fresh_quota():
    """Un jeton non signé ne donne pas de clé « user:… » : l'attaquant reste compté par IP."""
    forged = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.signature"
    assert user_key(make_request({"Authorization": f"Bearer {forged}"})).startswith("ip:")


def test_ip_key_ignores_the_authorization_header(users):
    request = make_request(bearer(users.user()))
    assert ip_key(request) == "ip:1.2.3.4"


def test_request_without_a_client_gets_a_stable_key():
    assert ip_key(make_request(client=None)) == "ip:unknown"


# ---- Sur l'application réelle ----------------------------------------------------------


def set_default_limit(limiter: Limiter, monkeypatch, value: str) -> None:
    """Impose une limite par défaut pour la durée du test (restaurée automatiquement)."""
    from slowapi.wrappers import LimitGroup

    group = LimitGroup(value, limiter._key_func, None, False, None, None, None, 1, False)
    monkeypatch.setattr(limiter, "_default_limits", [group])


def test_the_real_app_enforces_its_default_limit(client, users, rate_limit, monkeypatch):
    set_default_limit(rate_limit, monkeypatch, "5/minute")
    h = bearer(users.user())

    codes = [client.get("/api/v1/projects", headers=h).status_code for _ in range(7)]

    assert codes == [200] * 5 + [429, 429]


def test_two_users_do_not_share_a_quota(client, users, rate_limit, monkeypatch):
    set_default_limit(rate_limit, monkeypatch, "3/minute")
    a, b = bearer(users.user()), bearer(users.user())

    assert [client.get("/api/v1/projects", headers=a).status_code for _ in range(4)] == [
        200,
        200,
        200,
        429,
    ]
    assert (
        client.get("/api/v1/projects", headers=b).status_code == 200
    )  # l'autre utilisateur n'est pas pénalisé


def test_the_fixture_restores_the_limiters_global_state(rate_limit):
    from app.core.ratelimit import limiter

    assert limiter.enabled is True  # activé pendant le test, désactivé ensuite par la fixture


def test_middleware_is_the_one_registered_on_the_server():
    from app.server import server

    assert any(m.cls is RateLimitMiddleware for m in server.user_middleware)
    assert ratelimit.limiter._swallow_errors is True
