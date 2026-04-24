"""Fluxo OAuth 2.0 com ContaAzul (DEV: form manual; PROD: callback auto)."""
from __future__ import annotations
from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse
from ..db import get_conn
from ..oauth import OAuthError, gerar_authorize_url, trocar_code_por_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/authorize", response_class=HTMLResponse)
def authorize(empresa_id: str = Query(...)):
    with get_conn() as conn:
        try:
            url = gerar_authorize_url(conn, empresa_id)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"falha: {e}")
    html = f"""
    <!doctype html><html lang="pt-br"><head><meta charset="utf-8"><title>Autorizar ContaAzul</title>
    <style>body{{font-family:Segoe UI,Arial,sans-serif;padding:40px;max-width:780px;margin:auto;color:#222}}
    code{{background:#f4f4f4;padding:2px 6px;border-radius:4px;font-size:0.9em;word-break:break-all}}
    .box{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:20px;margin:20px 0}}
    .btn{{display:inline-block;background:#2563eb;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600}}
    input[type=text]{{width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;font-family:monospace;font-size:0.9em;box-sizing:border-box}}
    label{{display:block;font-weight:600;margin-top:12px;margin-bottom:4px}}
    button{{background:#10b981;color:#fff;border:0;padding:10px 18px;border-radius:6px;cursor:pointer;font-weight:600}}
    .hint{{color:#6b7280;font-size:0.9em;margin-top:4px}}</style></head><body>
    <h2>Autorizar empresa na ContaAzul (modo DEV)</h2>
    <p><strong>Empresa:</strong> <code>{empresa_id}</code></p>
    <div class="box">
      <p><strong>Passo 1.</strong> Clique no botao abaixo para abrir a tela de login da ContaAzul:</p>
      <p><a class="btn" href="{url}" target="_blank" rel="noopener">Autorizar no ContaAzul</a></p>
      <p class="hint">Use usuario e senha do ERP de teste.</p>
    </div>
    <div class="box">
      <p><strong>Passo 2.</strong> Apos login voce sera redirecionado para <code>https://contaazul.com?code=...&amp;state=...</code>. Copie a URL inteira e cole abaixo:</p>
      <form method="post" action="/auth/exchange">
        <input type="hidden" name="empresa_id" value="{empresa_id}">
        <label for="callback_url">URL completa do callback:</label>
        <input id="callback_url" type="text" name="callback_url" required
               placeholder="https://contaazul.com?code=xxxxxx&amp;state=xxxxxx">
        <button type="submit">Trocar por tokens</button>
      </form>
    </div></body></html>
    """
    return HTMLResponse(html)


@router.post("/exchange", response_class=HTMLResponse)
def exchange(empresa_id: str = Form(...), callback_url: str = Form(...)):
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)
    code = (qs.get("code") or [None])[0]
    state = (qs.get("state") or [None])[0]
    if not code or not state:
        raise HTTPException(status_code=400, detail="URL sem code/state")
    with get_conn() as conn:
        try:
            eid = trocar_code_por_token(conn, code, state)
        except OAuthError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return HTMLResponse(
        f'<html><body style="font-family:sans-serif;padding:40px"><h2>Autorizacao concluida</h2>'
        f'<p>Empresa: <code>{eid}</code></p><p>Proximo: POST /sync/{eid}</p></body></html>'
    )


@router.get("/callback", response_class=HTMLResponse)
def callback(code: str = Query(...), state: str = Query(...)):
    with get_conn() as conn:
        try:
            eid = trocar_code_por_token(conn, code, state)
        except OAuthError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return HTMLResponse(
        f'<html><body style="font-family:sans-serif;padding:40px"><h2>Conexao realizada</h2>'
        f'<p>Empresa: <code>{eid}</code></p></body></html>'
    )
