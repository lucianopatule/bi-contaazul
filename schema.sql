-- =============================================================================
-- bi_conta_azul  |  Schema multi-tenant  |  PED Intelligence / JF Consultoria
-- =============================================================================
-- Rodar com:  psql -U postgres -d bi_conta_azul -f schema.sql
-- Pré-requisito: CREATE DATABASE bi_conta_azul;  (executado 1x como superuser)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS staging_ca;
CREATE SCHEMA IF NOT EXISTS mart_ca;

-- =============================================================================
-- CORE  |  Gestão multi-tenant e credenciais
-- =============================================================================

-- Tabela mestre de clientes (tenants) -----------------------------------------
CREATE TABLE IF NOT EXISTS core.clientes (
    id                        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nome                      TEXT NOT NULL,
    cnpj                      TEXT,
    email_contato             TEXT,
    ativo                     BOOLEAN NOT NULL DEFAULT TRUE,

    -- OAuth do app ContaAzul (opcional por cliente; NULL = usa app global do .env)
    ca_client_id              TEXT,
    ca_client_secret_enc      BYTEA,     -- pgcrypto PGP_SYM_ENCRYPT

    -- Tokens do cliente (criptografados)
    ca_refresh_token_enc      BYTEA,
    ca_access_token_enc       BYTEA,
    ca_access_token_expira    TIMESTAMPTZ,

    -- Controle de sync
    sync_ativo                BOOLEAN NOT NULL DEFAULT TRUE,
    sync_frequencia_min       INTEGER NOT NULL DEFAULT 60,
    ultimo_sync_em            TIMESTAMPTZ,

    criado_em                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_clientes_cnpj
    ON core.clientes(cnpj) WHERE cnpj IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_clientes_ativo
    ON core.clientes(ativo) WHERE ativo = TRUE;

-- Trigger para atualizar atualizado_em ----------------------------------------
CREATE OR REPLACE FUNCTION core.set_atualizado_em() RETURNS TRIGGER AS $$
BEGIN
    NEW.atualizado_em := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_clientes_atualizado_em ON core.clientes;
CREATE TRIGGER trg_clientes_atualizado_em
    BEFORE UPDATE ON core.clientes
    FOR EACH ROW EXECUTE FUNCTION core.set_atualizado_em();

-- Log de execuções de sincronização -------------------------------------------
CREATE TABLE IF NOT EXISTS core.sync_control (
    id                BIGSERIAL PRIMARY KEY,
    empresa_id        UUID NOT NULL REFERENCES core.clientes(id) ON DELETE CASCADE,
    endpoint          TEXT NOT NULL,
    iniciado_em       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalizado_em     TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'running',   -- running|success|error
    registros         INTEGER,
    mensagem_erro     TEXT
);

CREATE INDEX IF NOT EXISTS ix_sync_control_empresa
    ON core.sync_control(empresa_id, iniciado_em DESC);

-- State do OAuth (CSRF) para fluxo authorization code -------------------------
CREATE TABLE IF NOT EXISTS core.oauth_state (
    state             TEXT PRIMARY KEY,
    empresa_id        UUID NOT NULL REFERENCES core.clientes(id) ON DELETE CASCADE,
    criado_em         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expira_em         TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '10 minutes'
);

CREATE INDEX IF NOT EXISTS ix_oauth_state_expira
    ON core.oauth_state(expira_em);

-- =============================================================================
-- STAGING  |  Payload bruto (JSONB) — resiliente a mudanças da API
-- =============================================================================
CREATE TABLE IF NOT EXISTS staging_ca.raw_eventos (
    empresa_id        UUID NOT NULL REFERENCES core.clientes(id) ON DELETE CASCADE,
    endpoint          TEXT NOT NULL,
    id_externo        TEXT NOT NULL,
    payload           JSONB NOT NULL,
    hash_payload      TEXT NOT NULL,
    sincronizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (empresa_id, endpoint, id_externo)
);

CREATE INDEX IF NOT EXISTS ix_staging_raw_endpoint
    ON staging_ca.raw_eventos(empresa_id, endpoint);

CREATE INDEX IF NOT EXISTS ix_staging_raw_payload_gin
    ON staging_ca.raw_eventos USING GIN (payload);

-- =============================================================================
-- MART  |  Modelo dimensional para BI (Power BI / Excel)
-- =============================================================================

-- Dim: categorias financeiras -------------------------------------------------
CREATE TABLE IF NOT EXISTS mart_ca.dim_categoria (
    empresa_id        UUID NOT NULL REFERENCES core.clientes(id) ON DELETE CASCADE,
    categoria_id      TEXT NOT NULL,
    nome              TEXT,
    tipo              TEXT,                  -- RECEITA|DESPESA
    ativo             BOOLEAN,
    PRIMARY KEY (empresa_id, categoria_id)
);

-- Dim: centro de custo --------------------------------------------------------
CREATE TABLE IF NOT EXISTS mart_ca.dim_centro_custo (
    empresa_id        UUID NOT NULL REFERENCES core.clientes(id) ON DELETE CASCADE,
    centro_id         TEXT NOT NULL,
    nome              TEXT,
    ativo             BOOLEAN,
    PRIMARY KEY (empresa_id, centro_id)
);

-- Dim: conta financeira -------------------------------------------------------
CREATE TABLE IF NOT EXISTS mart_ca.dim_conta_financeira (
    empresa_id        UUID NOT NULL REFERENCES core.clientes(id) ON DELETE CASCADE,
    conta_id          TEXT NOT NULL,
    nome              TEXT,
    tipo              TEXT,
    saldo_inicial     NUMERIC(18,2),
    ativo             BOOLEAN,
    PRIMARY KEY (empresa_id, conta_id)
);

-- Fato: parcelas financeiras (AP/AR) — grão correto para fluxo de caixa -------
CREATE TABLE IF NOT EXISTS mart_ca.fato_parcela (
    empresa_id        UUID NOT NULL REFERENCES core.clientes(id) ON DELETE CASCADE,
    parcela_id        TEXT NOT NULL,
    evento_id         TEXT NOT NULL,
    tipo              TEXT NOT NULL,         -- PAGAR|RECEBER
    numero            INTEGER,
    data_vencimento   DATE,
    data_pagamento    DATE,
    valor_previsto    NUMERIC(18,2),
    valor_pago        NUMERIC(18,2),
    status            TEXT,                  -- ABERTA|PAGA|PARCIAL|CANCELADA
    categoria_id      TEXT,
    centro_custo_id   TEXT,
    conta_id          TEXT,
    pessoa_nome       TEXT,
    descricao         TEXT,
    PRIMARY KEY (empresa_id, parcela_id)
);

CREATE INDEX IF NOT EXISTS ix_fato_parcela_venc
    ON mart_ca.fato_parcela(empresa_id, data_vencimento);
CREATE INDEX IF NOT EXISTS ix_fato_parcela_status
    ON mart_ca.fato_parcela(empresa_id, status);
CREATE INDEX IF NOT EXISTS ix_fato_parcela_tipo
    ON mart_ca.fato_parcela(empresa_id, tipo);

-- Fato: vendas ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mart_ca.fato_venda (
    empresa_id        UUID NOT NULL REFERENCES core.clientes(id) ON DELETE CASCADE,
    venda_id          TEXT NOT NULL,
    numero            TEXT,
    data_venda        DATE,
    cliente_nome      TEXT,
    valor_total       NUMERIC(18,2),
    valor_desconto    NUMERIC(18,2),
    status            TEXT,
    PRIMARY KEY (empresa_id, venda_id)
);

CREATE INDEX IF NOT EXISTS ix_fato_venda_data
    ON mart_ca.fato_venda(empresa_id, data_venda);

-- =============================================================================
-- VIEWS para BI
-- =============================================================================

-- Fluxo de caixa diário (previsto x realizado)
CREATE OR REPLACE VIEW mart_ca.vw_fluxo_caixa_diario AS
SELECT
    empresa_id,
    COALESCE(data_pagamento, data_vencimento) AS data_ref,
    SUM(CASE WHEN tipo='RECEBER' AND data_pagamento IS NOT NULL THEN valor_pago     ELSE 0 END) AS entrada_realizada,
    SUM(CASE WHEN tipo='PAGAR'   AND data_pagamento IS NOT NULL THEN valor_pago     ELSE 0 END) AS saida_realizada,
    SUM(CASE WHEN tipo='RECEBER' AND data_pagamento IS NULL     THEN valor_previsto ELSE 0 END) AS entrada_prevista,
    SUM(CASE WHEN tipo='PAGAR'   AND data_pagamento IS NULL     THEN valor_previsto ELSE 0 END) AS saida_prevista
FROM mart_ca.fato_parcela
GROUP BY empresa_id, COALESCE(data_pagamento, data_vencimento);

-- Aging de recebíveis
CREATE OR REPLACE VIEW mart_ca.vw_aging_receber AS
SELECT
    empresa_id,
    CASE
        WHEN data_vencimento >= CURRENT_DATE                            THEN 'A vencer'
        WHEN CURRENT_DATE - data_vencimento BETWEEN 1   AND 30          THEN '01-30 dias'
        WHEN CURRENT_DATE - data_vencimento BETWEEN 31  AND 60          THEN '31-60 dias'
        WHEN CURRENT_DATE - data_vencimento BETWEEN 61  AND 90          THEN '61-90 dias'
        WHEN CURRENT_DATE - data_vencimento > 90                        THEN '90+ dias'
    END AS faixa,
    COUNT(*)                         AS qtd_parcelas,
    SUM(valor_previsto - COALESCE(valor_pago,0)) AS saldo_aberto
FROM mart_ca.fato_parcela
WHERE tipo = 'RECEBER' AND status <> 'PAGA' AND status <> 'CANCELADA'
GROUP BY empresa_id, faixa;
