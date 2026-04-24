# bi_conta_azul — MVP Multi-Tenant

**Projeto:** PED Intelligence → JF Consultoria Empresarial
**Objetivo:** ETL multi-tenant que consome a API ContaAzul v2, consolida em PostgreSQL
e disponibiliza modelo dimensional (staging + mart) pronto para Power BI / Excel.

---

## Arquitetura

```
Cliente Final (empresa)           API ContaAzul v2          Postgres (bi_conta_azul)
        │                              │                      │
        │ 1. OAuth                     │                      │
        ▼                              │                      │
  /auth/authorize ── 302 ──▶  auth.contaazul.com              │
        │                              │                      │
        │  ◀── code+state ─────────────┤                      │
  /auth/callback ──────── grava tokens cifrados ────────────▶ core.clientes
                                                              │
  /sync/{empresa_id}  ────────┐                               │
  cron run_etl.py     ────────┼─▶ ETL ─── JSONB ──────▶  staging_ca.raw_eventos
                              │                               │
                              └──────── materializa ─────▶ mart_ca.dim_* / fato_*
                                                                    │
                                                                    ▼
                                                            Power BI / Excel / DAX
```

**Isolamento multi-tenant:** toda tabela (staging e mart) tem `empresa_id UUID`
como 1ª coluna da PK e FK para `core.clientes`. Delete em cascata.

---

## Setup (1ª vez)

### 1. Pré-requisitos
- PostgreSQL 14+ rodando localmente
- Python 3.10+
- App criado no Portal Dev ContaAzul (<https://portaldev.contaazul.com>) com
  `redirect_uri = http://localhost:8000/auth/callback`

### 2. Banco
```powershell
# Windows PowerShell
psql -U postgres -c "CREATE DATABASE bi_conta_azul;"
psql -U postgres -d bi_conta_azul -f schema.sql
```

### 3. Ambiente Python
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Configuração
```powershell
copy .env.example .env
# Editar .env: DB_PASSWORD, CRYPTO_MASTER_KEY (gerar nova!), CA_CLIENT_ID, CA_CLIENT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"   # gera chave forte
```

### 5. Subir API
```powershell
uvicorn app.main:app --reload
# Acessar http://localhost:8000/docs
```

---

## Fluxo de uso

### Cadastrar nova empresa cliente
```bash
curl -X POST http://localhost:8000/clientes \
  -H "Content-Type: application/json" \
  -d '{"nome":"Cliente Teste","cnpj":"00.000.000/0001-00","email_contato":"financeiro@cliente.com"}'
# Retorna: {"id":"<UUID>", ...}
```

### Autorizar no ContaAzul
Abrir no navegador:
```
http://localhost:8000/auth/authorize?empresa_id=<UUID>
```
Isso redireciona o cliente para a tela de autorização da ContaAzul. Após
autorizar, retorna ao `/auth/callback` e os tokens ficam salvos cifrados.

### Disparar sincronização manual
```bash
curl -X POST http://localhost:8000/sync/<UUID>
```

### Agendar sincronização automática (Windows Task Scheduler)
Criar tarefa que executa a cada 1 hora:
```
Programa: C:\caminho\para\.venv\Scripts\python.exe
Argumentos: run_etl.py --all
Iniciar em: C:\Users\adm290\CONTA AZUL
```

---

## Endpoints da API

| Método | Rota                              | Descrição                          |
|--------|-----------------------------------|------------------------------------|
| POST   | `/clientes`                       | Cadastra nova empresa              |
| GET    | `/clientes`                       | Lista empresas                     |
| GET    | `/clientes/{id}`                  | Detalhes de uma empresa            |
| PATCH  | `/clientes/{id}`                  | Atualiza dados                     |
| DELETE | `/clientes/{id}`                  | Desativa (soft delete)             |
| GET    | `/auth/authorize?empresa_id=…`    | Inicia OAuth ContaAzul             |
| GET    | `/auth/callback`                  | Callback OAuth (automático)        |
| POST   | `/sync/{empresa_id}`              | Dispara ETL em background          |
| GET    | `/sync/{empresa_id}/historico`    | Log de sincronizações              |
| GET    | `/health`                         | Healthcheck (API + DB)             |

Docs interativas: `http://localhost:8000/docs`

---

## Modelo de dados

### `core` — gestão multi-tenant
- `clientes` — 1 linha por empresa (com OAuth e config)
- `sync_control` — log de cada execução por endpoint
- `oauth_state` — CSRF temporário do fluxo OAuth

### `staging_ca` — bruto
- `raw_eventos` — JSONB de cada item retornado pela API (com `hash_payload` p/ detectar mudanças)

### `mart_ca` — BI
- `dim_categoria`, `dim_centro_custo`, `dim_conta_financeira`
- `fato_parcela` (grão correto de fluxo de caixa: AP + AR)
- `fato_venda`
- Views: `vw_fluxo_caixa_diario`, `vw_aging_receber`

---

## Queries úteis para BI

```sql
-- Fluxo de caixa 30 dias (1 empresa)
SELECT data_ref,
       entrada_prevista, entrada_realizada,
       saida_prevista, saida_realizada,
       (entrada_prevista + entrada_realizada) - (saida_prevista + saida_realizada) AS saldo
  FROM mart_ca.vw_fluxo_caixa_diario
 WHERE empresa_id = '<UUID>'
   AND data_ref BETWEEN CURRENT_DATE AND CURRENT_DATE + 30
 ORDER BY data_ref;

-- Aging de recebíveis
SELECT * FROM mart_ca.vw_aging_receber WHERE empresa_id = '<UUID>';

-- DRE por categoria
SELECT c.nome AS categoria, c.tipo,
       SUM(p.valor_pago) AS realizado
  FROM mart_ca.fato_parcela p
  JOIN mart_ca.dim_categoria c
    ON p.empresa_id = c.empresa_id AND p.categoria_id = c.categoria_id
 WHERE p.empresa_id = '<UUID>'
   AND p.data_pagamento >= CURRENT_DATE - INTERVAL '30 days'
 GROUP BY c.nome, c.tipo
 ORDER BY c.tipo, realizado DESC;
```

---

## Segurança

- **Secrets (client_secret, refresh_token, access_token):** cifrados no banco via
  `pgcrypto.pgp_sym_encrypt` com chave mestre em `CRYPTO_MASTER_KEY`.
- **Nunca commitar `.env`** — `.gitignore` já protege.
- **HTTPS em produção:** obrigatório no redirect URI. Substituir `localhost` por
  domínio público com certificado (ex.: `https://bi.pedintelligence.com.br/auth/callback`)
  e cadastrar no Portal Dev.
- **Rotação de chave mestre:** se precisar trocar `CRYPTO_MASTER_KEY`, é necessário
  re-encriptar todos os valores existentes. Script utilitário não incluso neste MVP.

---

## Próximos passos sugeridos

1. **Template Power BI (.pbit)** com medidas DAX (Inadimplência %, PMR, PMP, DRE) já apontando para `mart_ca`.
2. **RLS (Row-Level Security)** por `empresa_id` para quando múltiplos usuários
   acessarem o mesmo Postgres.
3. **Webhook de eventos** da ContaAzul (se a API suportar) para sincronização near real-time.
4. **Dashboard web** (FastAPI + HTMX ou React) para o Julio operar sem SQL.
5. **Empacotar como serviço cloud** (Docker + Fly.io / Railway / VPS) para oferta SaaS da PED.
