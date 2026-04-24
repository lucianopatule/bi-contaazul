"""
CLI para agendamento (cron / Task Scheduler).

Uso:
    python run_etl.py --all                 # todos os clientes ativos com sync_ativo
    python run_etl.py --empresa-id UUID     # uma empresa específica
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from app.db import get_conn
from app.etl import sincronizar_empresa

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("run_etl")


def listar_clientes_pendentes() -> list[tuple[str, str]]:
    """Retorna [(id, nome)] de clientes ativos cujo sync está devido."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, nome
              FROM core.clientes
             WHERE ativo = TRUE
               AND sync_ativo = TRUE
               AND ca_refresh_token_enc IS NOT NULL
               AND (
                     ultimo_sync_em IS NULL
                  OR ultimo_sync_em < NOW() - (sync_frequencia_min || ' minutes')::interval
               )
             ORDER BY COALESCE(ultimo_sync_em, 'epoch'::timestamptz) ASC
            """
        )
        return [(str(r[0]), r[1]) for r in cur.fetchall()]


def main() -> int:
    p = argparse.ArgumentParser(description="ETL ContaAzul multi-tenant")
    p.add_argument("--all", action="store_true", help="sincroniza clientes pendentes")
    p.add_argument("--empresa-id", help="UUID da empresa a sincronizar")
    args = p.parse_args()

    if not args.all and not args.empresa_id:
        p.print_help()
        return 2

    alvo: list[tuple[str, str]]
    if args.empresa_id:
        alvo = [(args.empresa_id, args.empresa_id)]
    else:
        alvo = listar_clientes_pendentes()
        log.info("clientes pendentes: %d", len(alvo))

    exit_code = 0
    for eid, nome in alvo:
        log.info("-- sincronizando %s (%s)", nome, eid)
        try:
            resumo = sincronizar_empresa(eid)
            log.info("OK: %s", json.dumps(resumo, default=str))
        except Exception as e:  # noqa: BLE001
            log.exception("FALHA %s: %s", eid, e)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
