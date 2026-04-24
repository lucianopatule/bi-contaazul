"""
Script interativo para completar OAuth ContaAzul sem ter que ficar alternando abas.

Uso:
    python oauth_cli.py <empresa_id>
"""
from __future__ import annotations

import sys
import webbrowser
from urllib.parse import parse_qs, urlparse

from app.db import get_conn
from app.oauth import gerar_authorize_url, trocar_code_por_token


def main():
    if len(sys.argv) != 2:
        print("Uso: python oauth_cli.py <empresa_id>")
        print("Exemplo: python oauth_cli.py 81491ad2-1e48-4ec4-aa14-8a9e0b380642")
        sys.exit(1)

    empresa_id = sys.argv[1]

    # Limpa states expirados para nao atrapalhar
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM core.oauth_state WHERE expira_em < NOW()")
        conn.commit()

    # Gera URL de autorizacao
    with get_conn() as conn:
        url = gerar_authorize_url(conn, empresa_id)

    print("\n" + "="*70)
    print(" OAUTH CONTAAZUL - MODO INTERATIVO")
    print("="*70)
    print(f"\n Empresa: {empresa_id}")
    print(f"\n [1/4] Abrindo navegador na tela de login do ContaAzul...")
    print(f"       (Se nao abrir automaticamente, cole a URL abaixo)\n")
    print(f"       {url}\n")

    webbrowser.open(url)

    print(" [2/4] No navegador, faca login com:")
    print("       Usuario: 39dd0969-9caa-4a1a-98a4-bd6dc4bc1832@devportal.com")
    print("       Senha:   C39dd0969-9caa-4a1a-98a4-bd6dc4bc1832")
    print("")
    print(" [3/4] Apos logar, voce sera redirecionado para:")
    print("       https://contaazul.com/?code=XXXX&state=YYYY")
    print("")
    print("       COPIE A URL INTEIRA da barra do navegador")
    print("       (clique na barra, Ctrl+A, Ctrl+C)")
    print("")
    print("="*70)
    callback_url = input(" Cole a URL aqui e pressione ENTER:\n > ").strip()

    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)
    code = (qs.get("code") or [None])[0]
    state = (qs.get("state") or [None])[0]

    if not code or not state:
        print("\n [ERRO] A URL colada nao tem ?code=... e ?state=...")
        print("        Tente de novo, copiando a URL inteira.")
        sys.exit(2)

    print(f"\n [4/4] Trocando codigo por tokens...")
    with get_conn() as conn:
        try:
            result_empresa = trocar_code_por_token(conn, code, state)
        except Exception as e:
            print(f"\n [ERRO] Falha ao trocar tokens: {e}")
            print("        Causas comuns:")
            print("        - Code expirou (>3 minutos)")
            print("        - client_secret errado no .env")
            print("        - Reiniciou o uvicorn entre gerar URL e colar (perde o state)")
            sys.exit(3)

    print("\n" + "="*70)
    print(" SUCESSO!")
    print("="*70)
    print(f"\n Tokens cifrados gravados para empresa {result_empresa}")
    print("\n Proximo passo: disparar sincronizacao")
    print(f"\n    curl -X POST http://localhost:8000/sync/{result_empresa}")
    print("\n Ou na Swagger: http://localhost:8000/docs -> POST /sync/{empresa_id}")
    print("")


if __name__ == "__main__":
    main()
