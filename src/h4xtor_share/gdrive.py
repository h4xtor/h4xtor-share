"""Optional Google Drive connection (OAuth 2.0 for installed apps, PKCE).

Nothing here runs unless the user explicitly clicks "connect". Only the refresh token and the
account e-mail are stored, next to the config, encrypted with DPAPI on Windows.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import secrets
import sys
from collections.abc import Callable
from html import escape
from typing import Any
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from h4xtor_share.config import Config

SCOPE = "https://www.googleapis.com/auth/drive.file"

SETUP_HELP = """Sådan opretter du en Google Drive-forbindelse (engangsopsætning):
1. Åbn Google Cloud Console (console.cloud.google.com) og opret et projekt.
2. Aktivér "Google Drive API" under APIs & Services > Library.
3. Under "OAuth consent screen": vælg External, tilføj dig selv som testbruger.
4. Under Credentials: opret "OAuth client ID" af typen "Desktop app".
5. Sæt miljøvariablerne H4XTOR_GDRIVE_CLIENT_ID og H4XTOR_GDRIVE_CLIENT_SECRET
   (eller nøglerne gdrive_client_id / gdrive_client_secret i config.json).
6. Genstart h4xtor share og tryk på "Forbind Google Drive".
"""

DONE_PAGE = (
    "<!doctype html><meta charset=utf-8><title>h4xtor share</title>"
    "<body style='font-family:sans-serif;text-align:center;margin-top:20vh'>"
    "<h2>{title}</h2><p>{text}</p></body>"
)


NETWORK_ERROR = "Kunne ikke kontakte Google. Tjek internetforbindelsen."


class GoogleDriveError(RuntimeError):
    """Raised with a user-readable (Danish) message."""


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# -- token protection --------------------------------------------------------
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    source = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = function(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI-kald mislykkedes.")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


class GoogleDrive:
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
    REVOKE_URL = "https://oauth2.googleapis.com/revoke"
    API_BASE = "https://www.googleapis.com"

    def __init__(self, config: Config) -> None:
        self.config = config

    # -- configuration ---------------------------------------------------------
    @property
    def client_id(self) -> str:
        return (
            os.environ.get("H4XTOR_GDRIVE_CLIENT_ID")
            or str(self.config.data.get("gdrive_client_id") or "")
        ).strip()

    @property
    def client_secret(self) -> str:
        return (
            os.environ.get("H4XTOR_GDRIVE_CLIENT_SECRET")
            or str(self.config.data.get("gdrive_client_secret") or "")
        ).strip()

    # -- token file ------------------------------------------------------------
    def _save_tokens(self, refresh_token: str, email: str) -> None:
        raw = json.dumps({"refresh_token": refresh_token, "email": email}).encode("utf-8")
        path = self.config.gdrive_token_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            path.write_bytes(_dpapi(raw, True))
        else:
            path.write_bytes(raw)
            path.chmod(0o600)

    def _load_tokens(self) -> dict[str, str] | None:
        path = self.config.gdrive_token_path
        try:
            raw = path.read_bytes()
            if sys.platform == "win32":
                raw = _dpapi(raw, False)
            data = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("refresh_token"):
            return None
        return {"refresh_token": str(data["refresh_token"]), "email": str(data.get("email") or "")}

    def status(self) -> dict[str, Any]:
        tokens = self._load_tokens()
        return {
            "configured": bool(self.client_id),
            "connected": tokens is not None,
            "email": tokens["email"] if tokens else "",
        }

    # -- OAuth -------------------------------------------------------------------
    def _token_form(self, **fields: str) -> dict[str, str]:
        form = {"client_id": self.client_id, **fields}
        if self.client_secret:
            form["client_secret"] = self.client_secret
        return form

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
                self.TOKEN_URL, data=form
            ) as response:
                payload = await response.json(content_type=None)
                if response.status >= 400:
                    reason = payload.get("error") if isinstance(payload, dict) else ""
                    if reason == "invalid_grant":
                        raise GoogleDriveError(
                            "Google Drive-forbindelsen er udløbet. Forbind igen."
                        )
                    raise GoogleDriveError(
                        f"Google afviste forespørgslen ({reason or response.status})."
                    )
                return payload
        except (aiohttp.ClientError, TimeoutError) as error:
            raise GoogleDriveError(NETWORK_ERROR) from error

    async def connect(self, open_url: Callable[[str], None], timeout: float = 300) -> str:
        if not self.client_id:
            raise GoogleDriveError("Google Drive er ikke sat op.\n" + SETUP_HELP)
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(24)
        loop = asyncio.get_running_loop()
        result: asyncio.Future[str] = loop.create_future()

        async def callback(request: web.Request) -> web.Response:
            query = request.query
            if "code" not in query and "error" not in query:
                return web.Response(status=404)
            if not secrets.compare_digest(query.get("state", ""), state):
                error: Exception = GoogleDriveError("Ugyldigt svar fra Google (state passer ikke).")
                title, text = "Fejl", "Ugyldigt svar. Prøv igen i h4xtor share."
            elif query.get("error"):
                denied = query["error"] == "access_denied"
                message = (
                    "Adgang til Google Drive blev afvist."
                    if denied
                    else f"Google returnerede en fejl ({query['error']})."
                )
                error = GoogleDriveError(message)
                title, text = "Afvist", escape(message)
            else:
                if not result.done():
                    result.set_result(query["code"])
                return web.Response(
                    text=DONE_PAGE.format(
                        title="Forbundet",
                        text="Du kan lukke denne fane og gå tilbage til h4xtor share.",
                    ),
                    content_type="text/html",
                )
            if not result.done():
                result.set_exception(error)
            return web.Response(
                text=DONE_PAGE.format(title=title, text=text), content_type="text/html", status=400
            )

        app = web.Application()
        app.add_routes([web.get("/", callback)])
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = runner.addresses[0][1]
            redirect = f"http://127.0.0.1:{port}/"
            query = urlencode(
                {
                    "client_id": self.client_id,
                    "redirect_uri": redirect,
                    "response_type": "code",
                    "scope": SCOPE,
                    "state": state,
                    "code_challenge": pkce_challenge(verifier),
                    "code_challenge_method": "S256",
                    "access_type": "offline",
                    "prompt": "consent",
                }
            )
            open_url(f"{self.AUTH_URL}?{query}")
            try:
                code = await asyncio.wait_for(result, timeout)
            except TimeoutError as error:
                raise GoogleDriveError("Tidsfristen for at forbinde til Google udløb.") from error
        finally:
            await runner.cleanup()

        tokens = await self._token_request(
            self._token_form(
                code=code,
                code_verifier=verifier,
                grant_type="authorization_code",
                redirect_uri=redirect,
            )
        )
        refresh = tokens.get("refresh_token")
        access = tokens.get("access_token")
        if not refresh or not access:
            raise GoogleDriveError("Google gav ikke en varig adgang. Prøv at forbinde igen.")
        about = await self._api_get(
            access, "/drive/v3/about", {"fields": "user(emailAddress,displayName)"}
        )
        user = about.get("user") or {}
        email = str(user.get("emailAddress") or user.get("displayName") or "")
        self._save_tokens(str(refresh), email)
        return email

    # -- API -------------------------------------------------------------------------
    async def _api_get(
        self, access_token: str, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session, session.get(
                f"{self.API_BASE}{path}",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as response:
                if response.status >= 400:
                    raise GoogleDriveError(f"Google Drive svarede med fejl {response.status}.")
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as error:
            raise GoogleDriveError(NETWORK_ERROR) from error

    async def _access_token(self) -> str:
        tokens = self._load_tokens()
        if not tokens:
            raise GoogleDriveError("Google Drive er ikke forbundet.")
        payload = await self._token_request(
            self._token_form(refresh_token=tokens["refresh_token"], grant_type="refresh_token")
        )
        access = payload.get("access_token")
        if not access:
            raise GoogleDriveError("Google gav ingen adgangstoken. Forbind igen.")
        return str(access)

    async def list_root(self, limit: int = 20) -> list[str]:
        access = await self._access_token()
        payload = await self._api_get(
            access,
            "/drive/v3/files",
            {
                "q": "'root' in parents and trashed=false",
                "fields": "files(name)",
                "pageSize": max(1, min(int(limit), 1000)),
            },
        )
        return [str(item.get("name") or "") for item in payload.get("files") or []]

    async def disconnect(self) -> None:
        tokens = self._load_tokens()
        if tokens:
            with contextlib.suppress(aiohttp.ClientError, TimeoutError):
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
                    self.REVOKE_URL, data={"token": tokens["refresh_token"]}
                ):
                    pass
        with contextlib.suppress(OSError):
            self.config.gdrive_token_path.unlink()
