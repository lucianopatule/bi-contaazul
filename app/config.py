"""
Configuração centralizada — lê variáveis de ambiente do .env.
Projeto: bi_conta_azul  |  PED Intelligence / JF Consultoria
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Banco de dados -------------------------------------------------------
    db_host: str = Field(default="localhost")
    db_port: int = Field(default=5432)
    db_name: str = Field(default="bi_conta_azul")
    db_user: str = Field(default="postgres")
    db_password: str = Field(default="")

    # --- Criptografia de secrets (pgcrypto) -----------------------------------
    # Chave mestre usada por PGP_SYM_ENCRYPT / PGP_SYM_DECRYPT.
    # TROCAR em produção e guardar em gerenciador de segredos.
    crypto_master_key: str = Field(default="trocar-em-producao-32-bytes-min!!")

    # --- App ContaAzul (Portal Dev) -------------------------------------------
    # Credenciais do app registrado pela PED Intelligence. Cada cliente final
    # usa estas credenciais + seu próprio refresh_token.
    ca_client_id: str = Field(default="")
    ca_client_secret: str = Field(default="")
    ca_redirect_uri: str = Field(default="http://localhost:8000/auth/callback")

    # Endpoints da API v2 (confirmados na documentação oficial)
    ca_auth_base: str = Field(default="https://auth.contaazul.com")
    ca_api_base: str = Field(default="https://api-v2.contaazul.com/v1")

    # --- API local ------------------------------------------------------------
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def dsn(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} "
            f"dbname={self.db_name} user={self.db_user} password={self.db_password}"
        )


settings = Settings()
