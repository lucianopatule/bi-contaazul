"""
Criptografia de secrets via pgcrypto (PGP_SYM_ENCRYPT / PGP_SYM_DECRYPT).

Mantém a chave mestre apenas em memória da aplicação (vinda do .env) e
delega cripto ao Postgres — simples, auditável e sem dependência extra.
"""
from __future__ import annotations

from psycopg import Connection

from .config import settings


def encrypt(conn: Connection, plaintext: str | None) -> bytes | None:
    """Retorna BYTEA pronto para persistir, ou None se plaintext vier None."""
    if plaintext is None or plaintext == "":
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pgp_sym_encrypt(%s, %s)",
            (plaintext, settings.crypto_master_key),
        )
        row = cur.fetchone()
        return row[0] if row else None


def decrypt(conn: Connection, ciphertext: bytes | None) -> str | None:
    if ciphertext is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pgp_sym_decrypt(%s::bytea, %s)",
            (ciphertext, settings.crypto_master_key),
        )
        row = cur.fetchone()
        return row[0] if row else None
