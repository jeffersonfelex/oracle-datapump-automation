"""Leitura do config.yaml e injeção dos segredos vindos do .env ou do ambiente."""

import os
import yaml


def load_config(config_path: str) -> dict:
    """Carrega o YAML de configuração."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_env(env_path: str) -> dict:
    """Lê um arquivo .env (CHAVE=valor); devolve {} se ele não existir."""
    env = {}
    if not os.path.exists(env_path):
        return env
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


SEGREDOS = {
    "ORIGEM_USER": ("origem", "user"),
    "ORIGEM_PASSWORD": ("origem", "password"),
    "ORACLE_SSH_USER": ("oracle", "user"),
    "ORACLE_SSH_PASSWORD": ("oracle", "password"),
    "IMPDP_USER": ("impdp", "user"),
    "IMPDP_PASSWORD": ("impdp", "password"),
    "TEAMS_WEBHOOK_URL": ("alertas", "teams_webhook_url"),
}


def aplicar_segredos(config: dict, env: dict) -> dict:
    """Injeta no config os segredos do .env; variáveis de ambiente têm prioridade."""
    env_normalizado = {k.upper(): v for k, v in env.items()}
    for variavel, (secao, chave) in SEGREDOS.items():
        valor = os.environ.get(variavel) or env_normalizado.get(variavel)
        if valor:
            config.setdefault(secao, {})[chave] = valor
    return config
