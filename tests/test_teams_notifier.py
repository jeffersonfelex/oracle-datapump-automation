"""Testes do notificador do Teams (src/support/teams_notifier.py)."""

from unittest.mock import patch, MagicMock
import urllib.error

from src.support.teams_notifier import notificar_teams


def test_sem_url_nao_faz_nada():
    with patch("src.support.teams_notifier.urllib.request.urlopen") as mock_urlopen:
        notificar_teams(None, "titulo", ["linha"])
        mock_urlopen.assert_not_called()


def test_com_url_envia_post():
    resposta = MagicMock()
    resposta.status = 202
    resposta.__enter__.return_value = resposta

    with patch("src.support.teams_notifier.urllib.request.urlopen", return_value=resposta) as mock_urlopen:
        notificar_teams("https://exemplo.invalido/webhook", "titulo", ["linha 1", "linha 2"])
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://exemplo.invalido/webhook"
        assert req.get_method() == "POST"


def test_falha_de_rede_nao_levanta_excecao():
    with patch(
        "src.support.teams_notifier.urllib.request.urlopen",
        side_effect=urllib.error.URLError("falhou"),
    ):
        # Nao deve levantar excecao - uma falha de notificacao nunca pode
        # derrubar a execucao agendada.
        notificar_teams("https://exemplo.invalido/webhook", "titulo", ["linha"])


def test_falha_nao_expoe_url_no_log(caplog):
    url_secreta = "https://exemplo.invalido/webhook?sig=SEGREDO123"
    with patch(
        "src.support.teams_notifier.urllib.request.urlopen",
        side_effect=urllib.error.URLError(url_secreta),
    ):
        notificar_teams(url_secreta, "titulo", ["linha"])

    for record in caplog.records:
        assert "SEGREDO123" not in record.getMessage()
