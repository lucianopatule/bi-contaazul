"""
ETL multi-tenant ContaAzul -> Postgres.

Mapeamentos baseados nos JSONs reais da API v2:
- Categorias: {id, nome, tipo(RECEITA|DESPESA), categoria_pai, considera_custo_dre}
- Centro de custo / Conta financeira: {id, nome, ativo}
- Vendas (/venda/busca): {id, data, numero, cliente:{id,nome}, situacao:{nome}, total, tipo}
- Contas pagar/receber: {id, data_vencimento, data_competencia, total, pago, nao_pago,
                         status, status_traduzido, cliente:{id,nome}, categorias:[], centros_de_custo:[]}

fato_parcela e populada diretamente de contas_pagar + contas_receber (API v2 nao usa endpoint separado de parcelas).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Iterator

from psycopg import Connection
from psycopg.types.json import Jsonb

from .contaazul import ContaAzulClient
from .db import get_conn
from .oauth import get_access_token

log = logging.getLogger(__name__)


def sincronizar_empresa(empresa_id: str) -> dict[str, Any]:
    resumo: dict[str, Any] = {"empresa_id": empresa_id, "endpoints": {}}
    with get_conn() as conn:
        access_token = get_access_token(conn, empresa_id)
    with ContaAzulClient(access_token) as client, get_conn() as conn:
        jobs: list[tuple[str, Callable[[], Iterator[dict]]]] = [
            ("categorias",         client.listar_categorias),
            ("centros_custo",      client.listar_centros_custo),
            ("contas_financeiras", client.listar_contas_financeiras),
            ("contas_pagar",       lambda: client.buscar_contas_pagar()),
            ("contas_receber",     lambda: client.buscar_contas_receber()),
            ("vendas",             lambda: client.listar_vendas()),
        ]
        for nome, gen_fn in jobs:
            try:
                qtd = _sync_endpoint(conn, empresa_id, nome, gen_fn())
                resumo["endpoints"][nome] = {"status": "success", "registros": qtd}
            except Exception as e:
                log.exception("Falha sincronizando %s", nome)
                resumo["endpoints"][nome] = {"status": "error", "erro": str(e)}

        try:
            _materializar_mart(conn, empresa_id)
            resumo["mart"] = "success"
        except Exception as e:
            log.exception("Falha materializando mart")
            resumo["mart"] = f"erro: {e}"

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE core.clientes SET ultimo_sync_em = NOW() WHERE id = %s",
                (empresa_id,),
            )
        conn.commit()
    return resumo


def _sync_endpoint(
    conn: Connection, empresa_id: str, endpoint: str, itens: Iterator[dict[str, Any]]
) -> int:
    sync_id = _abrir_sync(conn, empresa_id, endpoint)
    qtd = 0
    try:
        with conn.cursor() as cur:
            for item in itens:
                id_ext = _extrair_id(item)
                if id_ext is None:
                    continue
                payload_str = json.dumps(item, sort_keys=True, default=str)
                hash_p = hashlib.sha256(payload_str.encode()).hexdigest()
                cur.execute(
                    """
                    INSERT INTO staging_ca.raw_eventos
                        (empresa_id, endpoint, id_externo, payload, hash_payload)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (empresa_id, endpoint, id_externo) DO UPDATE
                       SET payload         = EXCLUDED.payload,
                           hash_payload    = EXCLUDED.hash_payload,
                           sincronizado_em = NOW()
                     WHERE staging_ca.raw_eventos.hash_payload <> EXCLUDED.hash_payload
                    """,
                    (empresa_id, endpoint, id_ext, Jsonb(item), hash_p),
                )
                qtd += 1
        conn.commit()
        _fechar_sync(conn, sync_id, "success", qtd)
    except Exception as e:
        conn.rollback()
        _fechar_sync(conn, sync_id, "error", qtd, str(e))
        raise
    return qtd


def _materializar_mart(conn: Connection, empresa_id: str) -> None:
    """Materializa dims e fatos a partir do staging (sem chamar API)."""
    with conn.cursor() as cur:

        # ============ DIM CATEGORIA ============
        cur.execute(
            """
            INSERT INTO mart_ca.dim_categoria
                (empresa_id, categoria_id, nome, tipo, ativo,
                 categoria_pai_id, considera_custo_dre)
            SELECT empresa_id, id_externo,
                   payload->>'nome',
                   UPPER(COALESCE(payload->>'tipo','')),
                   TRUE,
                   payload->>'categoria_pai',
                   COALESCE((payload->>'considera_custo_dre')::bool, FALSE)
              FROM staging_ca.raw_eventos
             WHERE empresa_id = %s AND endpoint = 'categorias'
            ON CONFLICT (empresa_id, categoria_id) DO UPDATE
               SET nome=EXCLUDED.nome,
                   tipo=EXCLUDED.tipo,
                   categoria_pai_id=EXCLUDED.categoria_pai_id,
                   considera_custo_dre=EXCLUDED.considera_custo_dre
            """,
            (empresa_id,),
        )

        # ============ DIM CENTRO DE CUSTO ============
        cur.execute(
            """
            INSERT INTO mart_ca.dim_centro_custo (empresa_id, centro_id, nome, ativo)
            SELECT empresa_id, id_externo, payload->>'nome',
                   COALESCE((payload->>'ativo')::bool, TRUE)
              FROM staging_ca.raw_eventos
             WHERE empresa_id = %s AND endpoint = 'centros_custo'
            ON CONFLICT (empresa_id, centro_id) DO UPDATE
               SET nome=EXCLUDED.nome, ativo=EXCLUDED.ativo
            """,
            (empresa_id,),
        )

        # ============ DIM CONTA FINANCEIRA ============
        cur.execute(
            """
            INSERT INTO mart_ca.dim_conta_financeira
                (empresa_id, conta_id, nome, tipo, saldo_inicial, ativo)
            SELECT empresa_id, id_externo, payload->>'nome', payload->>'tipo',
                   NULLIF(payload->>'saldo_inicial','')::numeric,
                   COALESCE((payload->>'ativo')::bool, TRUE)
              FROM staging_ca.raw_eventos
             WHERE empresa_id = %s AND endpoint = 'contas_financeiras'
            ON CONFLICT (empresa_id, conta_id) DO UPDATE
               SET nome=EXCLUDED.nome, tipo=EXCLUDED.tipo,
                   saldo_inicial=EXCLUDED.saldo_inicial, ativo=EXCLUDED.ativo
            """,
            (empresa_id,),
        )

        # ============ FATO VENDA ============
        # Limpa fato_venda da empresa antes de inserir (para nao acumular lixo)
        cur.execute(
            "DELETE FROM mart_ca.fato_venda WHERE empresa_id = %s",
            (empresa_id,),
        )
        cur.execute(
            """
            INSERT INTO mart_ca.fato_venda
                (empresa_id, venda_id, numero, data_venda, cliente_nome,
                 valor_total, valor_desconto, status,
                 cliente_id, valor_pago, valor_aberto,
                 data_vencimento, data_competencia,
                 categoria_principal, descricao)
            SELECT empresa_id, id_externo,
                   NULLIF(payload->>'numero','')::int,
                   NULLIF(payload->>'data','')::date,
                   payload->'cliente'->>'nome',
                   NULLIF(payload->>'total','')::numeric,
                   NULL::numeric,
                   payload->'situacao'->>'nome',
                   payload->'cliente'->>'id',
                   NULL::numeric,
                   NULL::numeric,
                   NULL::date,
                   NULLIF(payload->>'data','')::date,
                   NULL,
                   payload->>'tipo'
              FROM staging_ca.raw_eventos
             WHERE empresa_id = %s AND endpoint = 'vendas'
            """,
            (empresa_id,),
        )

        # ============ FATO PARCELA ============
        # API v2 nao usa /parcelas separado - cada conta_pagar/receber = 1 parcela.
        # Limpa antes para evitar lixo.
        cur.execute(
            "DELETE FROM mart_ca.fato_parcela WHERE empresa_id = %s",
            (empresa_id,),
        )
        cur.execute(
            """
            INSERT INTO mart_ca.fato_parcela (
                empresa_id, parcela_id, evento_id, tipo, numero,
                data_vencimento, data_pagamento, valor_previsto, valor_pago,
                status, categoria_id, centro_custo_id, conta_id,
                pessoa_nome, descricao
            )
            SELECT empresa_id, id_externo, id_externo,
                   CASE WHEN endpoint='contas_pagar' THEN 'PAGAR' ELSE 'RECEBER' END,
                   NULL::int,
                   NULLIF(payload->>'data_vencimento','')::date,
                   CASE
                       WHEN (payload->>'pago')::numeric >= (payload->>'total')::numeric
                            AND (payload->>'pago')::numeric > 0
                       THEN NULLIF(payload->>'data_alteracao','')::date
                       ELSE NULL
                   END,
                   NULLIF(payload->>'total','')::numeric,
                   NULLIF(payload->>'pago','')::numeric,
                   COALESCE(payload->>'status_traduzido', payload->>'status'),
                   (payload->'categorias'->0)->>'id',
                   (payload->'centros_de_custo'->0)->>'id',
                   NULL::text,
                   payload->'cliente'->>'nome',
                   payload->>'descricao'
              FROM staging_ca.raw_eventos
             WHERE empresa_id = %s
               AND endpoint IN ('contas_pagar','contas_receber')
            """,
            (empresa_id,),
        )
    conn.commit()


def _extrair_id(item: dict[str, Any]) -> str | None:
    for k in ("id", "uuid", "codigo"):
        v = item.get(k)
        if v is not None:
            return str(v)
    return None


def _abrir_sync(conn: Connection, empresa_id: str, endpoint: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO core.sync_control (empresa_id, endpoint) VALUES (%s, %s) RETURNING id",
            (empresa_id, endpoint),
        )
        sid = cur.fetchone()[0]
    conn.commit()
    return sid


def _fechar_sync(
    conn: Connection, sync_id: int, status: str, registros: int, erro: str | None = None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE core.sync_control SET finalizado_em=NOW(), status=%s, "
            "registros=%s, mensagem_erro=%s WHERE id=%s",
            (status, registros, erro, sync_id),
        )
    conn.commit()
