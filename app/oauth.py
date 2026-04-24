"""OAuth 2.0 para ContaAzul (API v2, DEV mode)."""
from __future__ import annotations
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
import httpx
from psycopg import Connection
from .config import settings
from .crypto import decrypt, encrypt

AUTHORIZE_ENDPOINT = "/login"
TOKEN_ENDPOINT = "/oauth2/token"


class OAuthError(Exception):
    pass


def gerar_authorize_url(conn: Connection, empresa_id: str) -> str:
    state = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO core.oauth_state (state, empresa_id) VALUES (%s, %s)",
            (state, empresa_id),
        )
    conn.commit()
    params = {
        "response_type": "code",
        "client_id": settings.ca_client_id,
        "redirect_uri": settings.ca_redirect_uri,
        "state": state,
    }
    qp = httpx.QueryParams(params)
    return f"{settings.ca_auth_base}{AUTHORIZE_ENDPOINT}?{qp}"


def trocar_code_por_token(conn: Connection, code: str, state: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT empresa_id FROM core.oauth_state WHERE state=%s AND expira_em>NOW()",
            (state,),
        )
        row = cur.fetchone()
        if not row:
            raise OAuthError("state invalido ou expirado")
        empresa_id = row[0]
        cur.execute("DELETE FROM core.oauth_state WHERE state=%s", (state,))
    tokens = _post_token({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.ca_redirect_uri,
    })
    _persist_tokens(conn, empresa_id, tokens)
    return str(empresa_id)


def get_access_token(conn: Connection, empresa_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ca_access_token_enc, ca_access_token_expira, ca_refresh_token_enc "
            "FROM core.clientes WHERE id=%s",
            (empresa_id,),
        )
        row = cur.fetchone()
        if not row:
            raise OAuthError(f"cliente {empresa_id} nao encontrado")
    access_enc, expira, refresh_enc = row
    agora = datetime.now(timezone.utc)
    margem = timedelta(seconds=60)
    if access_enc is not None and expira is not None and expira > agora + margem:
        token = decrypt(conn, access_enc)
        if token:
            return token
    refresh_token = decrypt(conn, refresh_enc)
    if not refresh_token:
        raise OAuthError(f"cliente {empresa_id} sem refresh_token")
    tokens = _post_token({"grant_type": "refresh_token", "refresh_token": refresh_token})
    _persist_tokens(conn, empresa_id, tokens)
    return tokens["access_token"]


def _post_token(data: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.ca_auth_base}{TOKEN_ENDPOINT}"
    body = {k: v for k, v in data.items() if k not in ("client_id", "client_secret")}
    with httpx.Client(timeout=30.0) as cli:
        resp = cli.post(
            url, data=body,
            auth=(settings.ca_client_id, settings.ca_client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        raise OAuthError(f"token endpoint retornou {resp.status_code}: {resp.text}")
    return resp.json()


def _persist_tokens(conn: Connection, empresa_id: str, tokens: dict[str, Any]) -> None:
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = int(tokens.get("expires_in", 3600))
    expira = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    access_enc = encrypt(conn, access_token)
    refresh_enc = encrypt(conn, refresh_token) if refresh_token else None
    with conn.cursor() as cur:
        if refresh_enc is not None:
            cur.execute(
                "UPDATE core.clientes SET ca_access_token_enc=%s, ca_access_token_expira=%s, "
                "ca_refresh_token_enc=%s WHERE id=%s",
                (access_enc, expira, refresh_enc, empresa_id),
            )
        else:
            cur.execute(
                "UPDATE core.clientes SET ca_access_token_enc=%s, ca_access_token_expira=%s "
                "WHERE id=%s",
                (access_enc, expira, empresa_id),
            )
    conn.commit()
