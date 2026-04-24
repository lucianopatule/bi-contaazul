"""
Fluxo OAuth 2.0 com ContaAzul.

    GET /auth/authorize?empresa_id=...   → redireciona o navegador para o ContaAzul
    GET /auth/callback?code=...&state=...→ recebe callback, salva tokens
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import get_conn
from ..oauth import OAuthError, gerar_authorize_url, trocar_code_por_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/authorize")
def authorize(empresa_id: str = Query(...)):
    """Redireciona o cliente final para a tela de autorização do ContaAzul."""
    with get_conn() as conn:
        try:
            url = gerar_authorize_url(conn, empresa_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"falha gerando authorize URL: {e}")
    return RedirectResponse(url, status_code=302)


@router.get("/callback", response_class=HTMLResponse)
def callback(code: str = Query(...), state: str = Query(...)):
    """Callback do ContaAzul. Troca code por tokens e salva."""
    with get_conn() as conn:
        try:
            empresa_id = trocar_code_por_token(conn, code, state)
        except OAuthError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return HTMLResponse(
        f"""
        <html><body style="font-family:sans-serif;padding:40px;">
        <h2>Conexão realizada com sucesso</h2>
        <p>Empresa: <code>{empresa_id}</code></p>
        <p>Você já pode fechar esta janela. A sincronização será disparada automaticamente
        conforme a agenda configurada ou manualmente em
        <code>POST /sync/{empresa_id}</code>.</p>
        </body></html>
        """
    )
