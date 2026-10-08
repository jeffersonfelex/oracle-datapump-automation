"""Testes do Notifier - avisa no Teams em falha critica, quando configurado."""

from unittest.mock import patch

from src.support.notifier import Notifier


def test_alerta_critico_chama_teams_quando_configurado():
    notifier = Notifier({"responsavel": "equipe de DBA", "teams_webhook_url": "https://exemplo.invalido/webhook"})

    with patch("src.support.notifier.notificar_teams") as mock_notificar:
        notifier.alert_critical_error("ESTOQUE", "impdp (parfile_estoque_2.par)", ["ORA-00001: unique constraint violated"], log_path="C:/log.log")

    mock_notificar.assert_called_once()
    kwargs = mock_notificar.call_args.kwargs
    assert kwargs["titulo"] == "Atualização Oracle: falha no sistema ESTOQUE"
    assert any("ORA-00001" in linha for linha in kwargs["linhas"])


def test_sem_webhook_nao_quebra():
    notifier = Notifier({"responsavel": "equipe de DBA"})
    with patch("src.support.notifier.notificar_teams") as mock_notificar:
        notifier.alert_critical_error("ESTOQUE", "impdp", ["erro"])
    # notificar_teams e sempre chamado (ela mesma decide nao fazer nada sem URL) -
    # o importante e que a chamada nao levanta excecao e passa None como webhook.
    assert mock_notificar.call_args.args[0] is None


def test_avisos_tolerados_tambem_avisam_no_teams():
    # Caso real: ORA-01918/ORA-00942 por schema de origem sem remap_schema (ex:
    # uma tabela de OUTRO_SCHEMA num dos sistemas) - a importacao segue como sucesso,
    # mas precisa avisar mesmo assim, para nao passar batido de novo.
    notifier = Notifier({"teams_webhook_url": "https://exemplo.invalido/webhook"})

    with patch("src.support.notifier.notificar_teams") as mock_notificar:
        notifier.notify_tolerated_warnings(
            "ESTOQUE",
            "impdp (parfile_estoque_1.par)",
            ['ORA-01918: user \'OUTRO_SCHEMA\' does not exist'],
            log_path="C:/log.log",
        )

    mock_notificar.assert_called_once()
    kwargs = mock_notificar.call_args.kwargs
    assert "avisos tolerados" in kwargs["titulo"]
    assert "ESTOQUE" in kwargs["titulo"]
    assert any("OUTRO_SCHEMA" in linha for linha in kwargs["linhas"])
