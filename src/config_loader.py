"""
Módulo de Carregamento da Configuração da Automação.
Único ponto responsável por ler o config.yaml e aplicar os segredos (senhas,
webhook) vindos do .env ou de variáveis de ambiente — segredos nunca ficam no YAML.
"""

import os
import yaml


def load_config(config_path: str) -> dict:
    """
    Carrega o arquivo YAML de configuração.
    Lança FileNotFoundError se o caminho informado não existir.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_env(env_path: str) -> dict:
    """
    Carrega variáveis no formato CHAVE=valor de um arquivo .env (ex: segredos
    como teams_webhook_url, que não devem ir para o config.yaml versionável).
    Retorna {} se o arquivo não existir - .env é opcional. Não usa nenhuma
    biblioteca externa (sem dependência nova só para isso).
    """
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


# variável de ambiente / chave do .env  ->  (seção do config.yaml, chave)
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
    """
    Injeta no config os segredos definidos no .env (`env`) ou em variáveis de
    ambiente do sistema (que têm prioridade). Chaves do .env aceitam maiúsculas
    ou minúsculas (ex: TEAMS_WEBHOOK_URL ou teams_webhook_url).
    """
    env_normalizado = {k.upper(): v for k, v in env.items()}
    for variavel, (secao, chave) in SEGREDOS.items():
        valor = os.environ.get(variavel) or env_normalizado.get(variavel)
        if valor:
            config.setdefault(secao, {})[chave] = valor
    return config
