"""Endpoints JSON para o dashboard HTML."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from ..db import get_conn

router = APIRouter(prefix="/bi", tags=["bi"])


@router.get("/empresas")
def listar_empresas():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.nome, c.cnpj, c.ativo,
                   c.ca_refresh_token_enc IS NOT NULL AS tem_token,
                   c.ultimo_sync_em,
                   (SELECT COUNT(*) FROM mart_ca.fato_parcela p WHERE p.empresa_id=c.id) AS qtd_parcelas
              FROM core.clientes c
             WHERE c.ativo = TRUE
             ORDER BY c.nome
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": str(r[0]), "nome": r[1], "cnpj": r[2], "ativo": r[3],
            "tem_token": r[4],
            "ultimo_sync_em": r[5].isoformat() if r[5] else None,
            "qtd_parcelas": r[6],
        }
        for r in rows
    ]


@router.get("/{empresa_id}/kpis")
def kpis(empresa_id: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM mart_ca.vw_resumo_financeiro WHERE empresa_id = %s",
            (empresa_id,),
        )
        r = cur.fetchone()
        cols = [c.name for c in cur.description] if cur.description else []
    if not r:
        return {"empresa_id": empresa_id, "total_a_receber": 0, "total_recebido": 0,
                "total_a_pagar": 0, "total_pago": 0, "receber_vencido": 0, "pagar_vencido": 0,
                "qtd_receber": 0, "qtd_pagar": 0, "saldo_projetado": 0}
    data = dict(zip(cols, r))
    saldo = (float(data.get("total_a_receber") or 0) - float(data.get("total_recebido") or 0)
             - (float(data.get("total_a_pagar") or 0) - float(data.get("total_pago") or 0)))
    data["saldo_projetado"] = saldo
    for k, v in list(data.items()):
        if hasattr(v, "__float__"):
            try: data[k] = float(v)
            except Exception: pass
    data["empresa_id"] = str(data["empresa_id"])
    return data


@router.get("/{empresa_id}/fluxo-caixa")
def fluxo_caixa(empresa_id: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT data, entrada_realizada, saida_realizada, entrada_prevista, saida_prevista
               FROM mart_ca.vw_fluxo_caixa WHERE empresa_id = %s ORDER BY data""",
            (empresa_id,),
        )
        rows = cur.fetchall()
    return [{"data": r[0].isoformat() if r[0] else None,
             "entrada_realizada": float(r[1] or 0), "saida_realizada": float(r[2] or 0),
             "entrada_prevista": float(r[3] or 0), "saida_prevista": float(r[4] or 0)} for r in rows]


@router.get("/{empresa_id}/aging")
def aging(empresa_id: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT tipo, faixa, qtd_parcelas, saldo_aberto, valor_previsto, valor_pago
               FROM mart_ca.vw_aging_detalhado WHERE empresa_id = %s
               ORDER BY tipo, CASE faixa
                 WHEN 'A_Vencer' THEN 1 WHEN '01-30d' THEN 2 WHEN '31-60d' THEN 3
                 WHEN '61-90d' THEN 4 WHEN '90d+' THEN 5 ELSE 9 END""",
            (empresa_id,),
        )
        rows = cur.fetchall()
    return [{"tipo": r[0], "faixa": r[1], "qtd_parcelas": int(r[2] or 0),
             "saldo_aberto": float(r[3] or 0), "valor_previsto": float(r[4] or 0),
             "valor_pago": float(r[5] or 0)} for r in rows]


@router.get("/{empresa_id}/dre")
def dre(empresa_id: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT mes, tipo_categoria, categoria, valor_previsto, valor_realizado, qtd_lancamentos
               FROM mart_ca.vw_dre_categoria WHERE empresa_id = %s
               ORDER BY mes DESC, tipo_categoria, categoria""",
            (empresa_id,),
        )
        rows = cur.fetchall()
    return [{"mes": r[0].isoformat() if r[0] else None, "tipo_categoria": r[1],
             "categoria": r[2], "valor_previsto": float(r[3] or 0),
             "valor_realizado": float(r[4] or 0), "qtd_lancamentos": int(r[5] or 0)} for r in rows]


@router.get("/{empresa_id}/parcelas")
def parcelas(empresa_id: str, limite: int = 500):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT parcela_id, tipo, pessoa_nome, data_vencimento, data_pagamento,
                      valor_previsto, valor_pago, saldo_aberto, status, situacao_calculada,
                      dias_atraso, descricao
               FROM mart_ca.vw_fato_parcela WHERE empresa_id = %s
               ORDER BY data_vencimento DESC NULLS LAST LIMIT %s""",
            (empresa_id, limite),
        )
        rows = cur.fetchall()
    return [{"parcela_id": r[0], "tipo": r[1], "pessoa_nome": r[2],
             "data_vencimento": r[3].isoformat() if r[3] else None,
             "data_pagamento": r[4].isoformat() if r[4] else None,
             "valor_previsto": float(r[5] or 0), "valor_pago": float(r[6] or 0),
             "saldo_aberto": float(r[7] or 0), "status": r[8], "situacao_calculada": r[9],
             "dias_atraso": int(r[10] or 0), "descricao": r[11]} for r in rows]


@router.get("/{empresa_id}/vendas")
def vendas(empresa_id: str, limite: int = 500):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT venda_id, numero, data_venda, cliente_nome, valor_total, status, descricao
               FROM mart_ca.fato_venda WHERE empresa_id = %s
               ORDER BY data_venda DESC NULLS LAST, numero DESC LIMIT %s""",
            (empresa_id, limite),
        )
        rows = cur.fetchall()
    return [{"venda_id": r[0], "numero": r[1],
             "data_venda": r[2].isoformat() if r[2] else None,
             "cliente_nome": r[3], "valor_total": float(r[4] or 0),
             "status": r[5], "descricao": r[6]} for r in rows]


@router.get("/{empresa_id}/ranking-categorias")
def ranking_categorias(empresa_id: str, tipo: str = "RECEITA", top: int = 10):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT categoria, SUM(valor_realizado), SUM(valor_previsto)
               FROM mart_ca.vw_dre_categoria WHERE empresa_id = %s AND tipo_categoria = %s
               GROUP BY categoria ORDER BY SUM(valor_realizado) DESC NULLS LAST LIMIT %s""",
            (empresa_id, tipo.upper(), top),
        )
        rows = cur.fetchall()
    return [{"categoria": r[0] or "(sem categoria)", "realizado": float(r[1] or 0),
             "previsto": float(r[2] or 0)} for r in rows]
