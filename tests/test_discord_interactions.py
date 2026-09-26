"""The signature tests matter more than they look: Discord validates a
newly-saved Interactions Endpoint URL by sending deliberately-BAD
signatures and checking they come back 401. Get that wrong and Discord
refuses to save the URL, so the command never works at all.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from src import discord_interactions
from src.discord_interactions import router


@pytest.fixture
def signing_key() -> SigningKey:
    return SigningKey.generate()


@pytest.fixture
def client(signing_key: SigningKey, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        discord_interactions.settings,
        "DISCORD_PUBLIC_KEY",
        signing_key.verify_key.encode().hex(),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _signed(signing_key: SigningKey, payload: dict) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    timestamp = "1700000000"
    signed = signing_key.sign(timestamp.encode() + body)
    return body, {
        "X-Signature-Ed25519": signed.signature.hex(),
        "X-Signature-Timestamp": timestamp,
    }


def test_ping_is_ponged(client: TestClient, signing_key: SigningKey) -> None:
    body, headers = _signed(signing_key, {"type": 1})

    response = client.post("/discord/interactions", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"type": 1}


def test_bad_signature_is_401(client: TestClient, signing_key: SigningKey) -> None:
    body, headers = _signed(signing_key, {"type": 1})
    other_key = SigningKey.generate()
    tampered = other_key.sign(b"1700000000" + body).signature.hex()

    response = client.post(
        "/discord/interactions",
        content=body,
        headers={**headers, "X-Signature-Ed25519": tampered},
    )

    assert response.status_code == 401


def test_missing_signature_headers_is_401(client: TestClient) -> None:
    response = client.post("/discord/interactions", content=b'{"type": 1}')

    assert response.status_code == 401


def test_malformed_signature_is_401_not_500(
    client: TestClient, signing_key: SigningKey
) -> None:
    """A non-hex signature must be rejected like any other bad one -- if the
    ValueError escaped it'd be a 500, which Discord treats as the endpoint
    being broken rather than correctly rejecting it.
    """
    body, headers = _signed(signing_key, {"type": 1})

    response = client.post(
        "/discord/interactions",
        content=body,
        headers={**headers, "X-Signature-Ed25519": "not-hex"},
    )

    assert response.status_code == 401


def test_unconfigured_public_key_is_503_not_crash(
    signing_key: SigningKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deploying before setting DISCORD_PUBLIC_KEY must not take down the
    service -- only this endpoint should be affected.
    """
    monkeypatch.setattr(discord_interactions.settings, "DISCORD_PUBLIC_KEY", "")
    app = FastAPI()
    app.include_router(router)
    unconfigured = TestClient(app)

    body, headers = _signed(signing_key, {"type": 1})
    response = unconfigured.post("/discord/interactions", content=body, headers=headers)

    assert response.status_code == 503


def test_invoking_user_read_from_guild_member() -> None:
    payload = {"member": {"user": {"id": "656802605267157004"}}}

    assert discord_interactions._invoking_discord_id(payload) == "656802605267157004"


def test_invoking_user_read_from_dm_shape() -> None:
    payload = {"user": {"id": "727705472185925713"}}

    assert discord_interactions._invoking_discord_id(payload) == "727705472185925713"


def test_invoking_user_absent_is_none() -> None:
    assert discord_interactions._invoking_discord_id({"type": 2}) is None
