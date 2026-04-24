"""
Endpoints de sincronização (ETL manual).
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ..db import get_conn
from ..etl import sincronizar_empresa

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/{empresa_id}")
def disparar_sync(empresa_id: str, background: BackgroundTasks):
    """Dispara ETL em background e retorna imediatamente."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ativo, ca_refresh_token_enc IS NOT NULL FROM core.clientes WHERE id = %s",
            (empresa_id,),
        )
        r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="cliente não encontrado")
    if not r[0]:
        raise HTTPException(status_code=400, detail="cliente inativo")
    if not r[1]:
        raise HTTPException(
            status_code=400,
            detail="cliente sem refresh_token — execute /auth/authorize antes",
        )

    background.add_task(sincronizar_empresa, empresa_id)
    return {"status": "agendado", "empresa_id": empresa_id}


@router.get("/{empresa_id}/historico")
def historico(empresa_id: str, limite: int = 20):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT endpoint, iniciado_em, finalizado_em, status, registros, mensagem_erro
              FROM core.sync_control
             WHERE empresa_id = %s
             ORDER BY iniciado_em DESC
             LIMIT %s
            """,
            (empresa_id, limite),
        )
        rows = cur.fetchall()
    return [
        {
            "endpoint": r[0],
            "iniciado_em": r[1].isoformat() if r[1] else None,
            "finalizado_em": r[2].isoformat() if r[2] else None,
            "status": r[3],
            "registros": r[4],
            "erro": r[5],
        }
        for r in rows
    ]
