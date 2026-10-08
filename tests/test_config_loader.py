import os
from unittest.mock import patch

from src.config_loader import aplicar_segredos, load_env


def test_aplica_segredos_do_env_no_config():
    config = {"origem": {"host": "h"}, "impdp": {"tns": "ORCLPDB"}}
    env = {"ORIGEM_PASSWORD": "s1", "impdp_password": "s2", "teams_webhook_url": "https://exemplo.invalido/w"}
    with patch.dict(os.environ, {}, clear=True):
        aplicar_segredos(config, env)
    assert config["origem"]["password"] == "s1"
    assert config["impdp"]["password"] == "s2"           # chave do .env em minúsculas também vale
    assert config["alertas"]["teams_webhook_url"] == "https://exemplo.invalido/w"


def test_variavel_de_ambiente_tem_prioridade_sobre_o_env():
    config = {"oracle": {}}
    with patch.dict(os.environ, {"ORACLE_SSH_PASSWORD": "do_sistema"}, clear=True):
        aplicar_segredos(config, {"ORACLE_SSH_PASSWORD": "do_arquivo"})
    assert config["oracle"]["password"] == "do_sistema"


def test_segredo_ausente_nao_cria_chave():
    config = {"oracle": {"host": "h"}}
    with patch.dict(os.environ, {}, clear=True):
        aplicar_segredos(config, {})
    assert "password" not in config["oracle"]


def test_load_env_ignora_comentarios_e_linhas_vazias(tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text("# comentario\n\nCHAVE=valor=com=igual\nSEM_IGUAL\n", encoding="utf-8")
    assert load_env(str(arquivo)) == {"CHAVE": "valor=com=igual"}
    assert load_env(str(tmp_path / "nao_existe")) == {}
