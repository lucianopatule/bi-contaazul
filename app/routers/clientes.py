"""
CRUD de clientes (tenants) — cadastro inicial, listagem e edição.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_conn

router = APIRouter(prefix="/clientes", tags=["clientes"])


# ----------------------------- Modelos -------------------------------------
class ClienteIn(BaseModel):
    nome: str
    cnpj: Optional[str] = None
    email_contato: Optional[str] = None
    sync_ativo: bool = True
    sync_frequencia_min: int = Field(default=60, ge=5)


class ClienteOut(BaseModel):
    id: str
    nome: str
    cnpj: Optional[str]
    email_contato: Optional[str]
    ativo: bool
    sync_ativo: bool
    sync_frequencia_min: int
    tem_refresh_token: bool
    ultimo_sync_em: Optional[str]


# ----------------------------- Endpoints -----------------------------------
@router.post("", response_model=ClienteOut, status_code=201)
def criar_cliente(payload: ClienteIn) -> ClienteOut:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO core.clientes
                (nome, cnpj, email_contato, sync_ativo, sync_frequencia_min)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, ativo, ultimo_sync_em
            """,
            (
                payload.nome,
                payload.cnpj,
                payload.email_contato,
                payload.sync_ativo,
                payload.sync_frequencia_min,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    return ClienteOut(
        id=str(row[0]),
        nome=payload.nome,
        cnpj=payload.cnpj,
        email_contato=payload.email_contato,
        ativo=row[1],
        sync_ativo=payload.sync_ativo,
        sync_frequencia_min=payload.sync_frequencia_min,
        tem_refresh_token=False,
        ultimo_sync_em=None,
    )


@router.get("", response_model=list[ClienteOut])
def listar_clientes(apenas_ativos: bool = False) -> list[ClienteOut]:
    sql = """
        SELECT id, nome, cnpj, email_contato, ativo,
               sync_ativo, sync_frequencia_min,
               ca_refresh_token_enc IS NOT NULL AS tem_refresh,
               ultimo_sync_em
          FROM core.clientes
    """
    if apenas_ativos:
        sql += " WHERE ativo = TRUE"
    sql += " ORDER BY nome"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    return [
        ClienteOut(
            id=str(r[0]), nome=r[1], cnpj=r[2], email_contato=r[3],
            ativo=r[4], sync_ativo=r[5], sync_frequencia_min=r[6],
            tem_refresh_token=r[7],
            ultimo_sync_em=r[8].isoformat() if r[8] else None,
        )
        for r in rows
    ]


@router.get("/{cliente_id}", response_model=ClienteOut)
def obter_cliente(cliente_id: str) -> ClienteOut:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, nome, cnpj, email_contato, ativo,
                   sync_ativo, sync_frequencia_min,
                   ca_refresh_token_enc IS NOT NULL,
                   ultimo_sync_em
              FROM core.clientes WHERE id = %s
            """,
            (cliente_id,),
        )
        r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="cliente não encontrado")
    return ClienteOut(
        id=str(r[0]), nome=r[1], cnpj=r[2], email_contato=r[3],
        ativo=r[4], sync_ativo=r[5], sync_frequencia_min=r[6],
        tem_refresh_token=r[7],
        ultimo_sync_em=r[8].isoformat() if r[8] else None,
    )


@router.patch("/{cliente_id}", response_model=ClienteOut)
def atualizar_cliente(cliente_id: str, payload: ClienteIn) -> ClienteOut:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE core.clientes
               SET nome = %s, cnpj = %s, email_contato = %s,
                   sync_ativo = %s, sync_frequencia_min = %s
             WHERE id = %s
            """,
            (
                payload.nome, payload.cnpj, payload.email_contato,
                payload.sync_ativo, payload.sync_frequencia_min, cliente_id,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="cliente não encontrado")
        conn.commit()
    return obter_cliente(cliente_id)


@router.delete("/{cliente_id}", status_code=204)
def desativar_cliente(cliente_id: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE core.clientes SET ativo = FALSE WHERE id = %s", (cliente_id,)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="cliente não encontrado")
        conn.commit()
