"""Cliente HTTP para API ContaAzul v2 com filtros obrigatorios."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterator

import httpx
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from .config import settings

LIST_KEYS = ("itens", "items", "data", "result", "content")


class ContaAzulAPIError(Exception):
    pass


class ContaAzulClient:
    def __init__(self, access_token: str, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=settings.ca_api_base,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, ContaAzulAPIError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _get(self, path, params=None):
        resp = self._client.get(path, params=params or {})
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ContaAzulAPIError(f"HTTP {resp.status_code} em {path}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} em {path}: {resp.text[:500]}")
        return resp.json()

    def paginate(self, path, params=None, page_size=100):
        params = dict(params or {})
        pagina = 1
        while True:
            q = {**params, "pagina": pagina, "tamanho_pagina": page_size}
            data = self._get(path, q)
            items = self._extract_list(data)
            if not items:
                break
            for it in items:
                yield it
            if len(items) < page_size:
                break
            pagina += 1

    @staticmethod
    def _extract_list(data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in LIST_KEYS:
                if k in data and isinstance(data[k], list):
                    return data[k]
            for v in data.values():
                if isinstance(v, list):
                    return v
        return []

    # --- Categorias: obrigatorio tipo ---
    def listar_categorias(self):
        for tipo in ("RECEITA", "DESPESA"):
            yield from self.paginate("/categorias", {"tipo": tipo})

    # --- Centro de custo: filtro_rapido obrigatorio ---
    def listar_centros_custo(self):
        yield from self.paginate("/centro-de-custo", {"filtro_rapido": "TODOS"})

    # --- Conta financeira: filtro_rapido obrigatorio ---
    def listar_contas_financeiras(self):
        yield from self.paginate("/conta-financeira", {"filtro_rapido": "TODOS"})

    # --- Contas a pagar: data_vencimento_de/ate obrigatorios ---
    def buscar_contas_pagar(self, filtros=None):
        hoje = date.today()
        default = {
            "data_vencimento_de": (hoje - timedelta(days=365 * 3)).isoformat(),
            "data_vencimento_ate": (hoje + timedelta(days=365 * 2)).isoformat(),
        }
        default.update(filtros or {})
        yield from self.paginate(
            "/financeiro/eventos-financeiros/contas-a-pagar/buscar", default
        )

    # --- Contas a receber: idem ---
    def buscar_contas_receber(self, filtros=None):
        hoje = date.today()
        default = {
            "data_vencimento_de": (hoje - timedelta(days=365 * 3)).isoformat(),
            "data_vencimento_ate": (hoje + timedelta(days=365 * 2)).isoformat(),
        }
        default.update(filtros or {})
        yield from self.paginate(
            "/financeiro/eventos-financeiros/contas-a-receber/buscar", default
        )

    def parcelas_do_evento(self, evento_id):
        data = self._get(f"/financeiro/eventos-financeiros/{evento_id}/parcelas")
        return self._extract_list(data)

    # --- Vendas: endpoint correto e /venda/busca ---
    def listar_vendas(self, filtros=None):
        yield from self.paginate("/venda/busca", filtros)
