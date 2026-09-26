"""Receives Discord slash-command interactions over plain HTTPS.

Why this works without turning น้องโกโก้ into a real bot: Discord will POST
an interaction to any HTTPS endpoint registered as the app's "Interactions
Endpoint URL", exactly like GitHub posts a webhook. No bot token at runtime,
no gateway WebSocket, no always-on process -- the same properties that let
this service live on a free tier (see README).

That is also why this is a slash command rather than "@mention the bot and
type a keyword": reading channel messages requires a live gateway
connection and the Message Content intent, which would mean an always-on
process. An interaction is just an HTTP request we already know how to
serve.
"""

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from src.config import settings
from src.database import async_session_maker
from src.discord_notify import format_my_reviews
from src.reviews import get_open_reviews, get_person_by_discord_id

router = APIRouter(prefix="/discord", tags=["discord"])
logger = logging.getLogger(__name__)

MYREVIEWS_COMMAND = "myreviews"

# Discord interaction types / response types we care about.
_PING = 1
_APPLICATION_COMMAND = 2
_PONG = 1
_CHANNEL_MESSAGE_WITH_SOURCE = 4


def _verify_signature(body: bytes, signature: str | None, timestamp: str | None) -> None:
    """Ed25519, using the app's public key.

    Discord validates a newly-saved Interactions Endpoint URL by sending
    requests with DELIBERATELY invalid signatures and checking they're
    rejected with 401 -- so returning anything else here (a 400, or worse a
    200) makes Discord refuse to save the URL at all.
    """
    if not settings.DISCORD_PUBLIC_KEY:
        # Feature not configured. Deliberately not a 500: the rest of the
        # service is fine, this one endpoint just isn't set up yet.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DISCORD_PUBLIC_KEY is not set on this service",
        )
    if not signature or not timestamp:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing signature headers")

    try:
        verify_key = VerifyKey(bytes.fromhex(settings.DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
    except (BadSignatureError, ValueError) as e:
        # ValueError covers a malformed hex signature/public key, which is
        # just as much "not a real Discord request" as a bad signature.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature") from e


def _invoking_discord_id(payload: dict) -> str | None:
    """In a guild the caller is under `member.user`; in a DM it's top-level
    `user`. Handling both means the command still works if someone tries it
    in a DM with the app instead of in the channel.
    """
    member = payload.get("member") or {}
    user = member.get("user") or payload.get("user") or {}
    return user.get("id")


@router.post("/interactions")
async def interactions(
    request: Request,
    x_signature_ed25519: str | None = Header(default=None),
    x_signature_timestamp: str | None = Header(default=None),
) -> dict:
    # Must verify against the RAW body -- re-serialising the parsed JSON
    # would change the bytes and fail the signature.
    body = await request.body()
    _verify_signature(body, x_signature_ed25519, x_signature_timestamp)

    payload = json.loads(body)

    if payload.get("type") == _PING:
        return {"type": _PONG}

    if payload.get("type") != _APPLICATION_COMMAND:
        return {"type": _PONG}

    command_name = (payload.get("data") or {}).get("name")
    if command_name != MYREVIEWS_COMMAND:
        logger.warning("unknown slash command %r", command_name)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown command")

    discord_id = _invoking_discord_id(payload)
    if discord_id is None:
        logger.warning("interaction carried no user id: %s", payload.get("type"))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no invoking user")

    async with async_session_maker() as session:
        person = await get_person_by_discord_id(session, discord_id)
        open_reviews = (
            await get_open_reviews(session, discord_id=discord_id)
            if person is not None
            else []
        )

    content = format_my_reviews(
        open_reviews, discord_id=discord_id, in_roster=person is not None
    )
    return {"type": _CHANNEL_MESSAGE_WITH_SOURCE, "data": {"content": content}}
