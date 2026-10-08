import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import agendado
from agendado import deve_processar, _referencia_arquivo
from src.core.control_db import ControlDB

AGORA = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

_SEM_MTIME = object()


def _ref(arquivo="a.dmp.gz", tamanho=1000, mtime=_SEM_MTIME):
    if mtime is _SEM_MTIME:
        mtime = AGORA - timedelta(hours=2)
    return {"arquivo": arquivo, "tamanho": tamanho, "mtime": mtime}


def test_sem_arquivo_na_origem_nao_processa():
    processar, motivo = deve_processar(None, None, AGORA)
    assert processar is False
    assert motivo == "sem_arquivo"


def test_base_nunca_processada_e_processada():
    ref = _ref()
    processar, motivo = deve_processar(None, ref, AGORA)
    assert processar is True
    assert motivo == "novo_ou_alterado"


def test_base_ja_processada_sem_mudanca_nao_e_reprocessada():
    ref = _ref(arquivo="a.dmp.gz", tamanho=1000, mtime=AGORA - timedelta(hours=2))
    estado = {"arquivo": "a.dmp.gz", "tamanho_origem": 1000, "mtime_origem": ref["mtime"].isoformat()}
    processar, motivo = deve_processar(estado, ref, AGORA)
    assert processar is False
    assert motivo == "sem_mudanca"


def test_base_com_arquivo_alterado_e_reprocessada():
    ref_antigo_mtime = AGORA - timedelta(days=1)
    estado = {"arquivo": "a.dmp.gz", "tamanho_origem": 1000, "mtime_origem": ref_antigo_mtime.isoformat()}
    ref_novo = _ref(arquivo="a.dmp.gz", tamanho=2000, mtime=AGORA - timedelta(hours=2))
    processar, motivo = deve_processar(estado, ref_novo, AGORA)
    assert processar is True
    assert motivo == "novo_ou_alterado"


def test_arquivo_modificado_a_menos_de_30_min_e_pulado():
    ref = _ref(mtime=AGORA - timedelta(minutes=10))
    processar, motivo = deve_processar(None, ref, AGORA)
    assert processar is False
    assert motivo == "modificado_recentemente"


def test_arquivo_modificado_ha_exatos_31_min_e_processado():
    ref = _ref(mtime=AGORA - timedelta(minutes=31))
    processar, motivo = deve_processar(None, ref, AGORA)
    assert processar is True


def test_mtime_desconhecido_nao_processa():
    ref = _ref(mtime=None)
    processar, motivo = deve_processar(None, ref, AGORA)
    assert processar is False
    assert motivo == "mtime_desconhecido"


def test_referencia_arquivo_usa_o_primeiro_da_lista_mais_recente():
    origem = MagicMock()
    origem.get_system_files.return_value = ("20261009", ["EXPORT_FRE_PROD_20261009_1.dmp.gz", "EXPORT_FRE_PROD_20261009_2.dmp.gz"])
    origem.get_remote_size.return_value = 12345
    origem.get_remote_mtime.return_value = AGORA

    ref = _referencia_arquivo(origem, "VENDAS")

    assert ref["arquivo"] == "EXPORT_FRE_PROD_20261009_1.dmp.gz"
    origem.get_remote_size.assert_called_once_with("EXPORT_FRE_PROD_20261009_1.dmp.gz")
    origem.get_remote_mtime.assert_called_once_with("EXPORT_FRE_PROD_20261009_1.dmp.gz")


def test_referencia_arquivo_none_quando_nao_ha_arquivos():
    origem = MagicMock()
    origem.get_system_files.return_value = ("", [])
    assert _referencia_arquivo(origem, "COMERCIAL") is None


def _config_duas_bases():
    return {
        "sistemas": {"ativos": ["VENDAS", "FROTA"]},
        "origem": {}, "impdp": {}, "teste": {}, "local": {},
    }


@pytest.fixture
def control_db_path(tmp_path, monkeypatch):
    path = os.path.join(tmp_path, "controle", "pipeline.db")
    monkeypatch.setattr(agendado, "CONTROL_DB_PATH", path)
    monkeypatch.setattr(agendado, "LOCK_PATH", os.path.join(tmp_path, "controle", "agendado.lock"))
    return path


def test_falha_de_uma_base_nao_impede_a_outra_e_e_registrada(control_db_path):
    agora_real = datetime.now(timezone.utc)
    ref_vendas = _ref(arquivo="EXPORT_FRE_PROD_20261009_1.dmp.gz", mtime=agora_real - timedelta(hours=2))
    ref_frota = _ref(arquivo="EXPORT_FROTA_PROD_20261009_1.dmp.gz", mtime=agora_real - timedelta(hours=2))

    with patch.object(agendado, "BackupSourceClient") as MockOrigem, \
         patch.object(agendado, "Orchestrator") as MockOrch, \
         patch.object(agendado, "notificar_teams") as mock_notificar, \
         patch.object(agendado, "_referencia_arquivo", side_effect=[ref_vendas, ref_frota]):
        MockOrigem.return_value = MagicMock()

        orch_instance = MockOrch.return_value
        orch_instance.run.side_effect = [
            {"VENDAS": "SUCESSO"},
            {"FROTA": "ERRO_CRITICO_IMPDP"},
        ]

        with pytest.raises(SystemExit) as exc_info:
            agendado.comando_verificacao_diaria(_config_duas_bases(), {}, MagicMock())

        assert exc_info.value.code == 1

    control = ControlDB(control_db_path)
    assert control.get_estado("VENDAS") is not None
    assert control.get_estado("FROTA") is None

    historico_frota = control.listar_execucoes(base="FROTA")
    assert len(historico_frota) == 1
    assert historico_frota[0]["status"] == "erro"

    mock_notificar.assert_called_once()
    _, kwargs_or_args = mock_notificar.call_args, mock_notificar.call_args
    linhas_enviadas = mock_notificar.call_args[0][2]
    assert any("VENDAS" in linha and "✅" in linha for linha in linhas_enviadas)
    assert any("FROTA" in linha and "❌" in linha for linha in linhas_enviadas)


def test_sem_mudanca_em_nenhuma_base_nao_notifica(control_db_path):
    with patch.object(agendado, "BackupSourceClient") as MockOrigem, \
         patch.object(agendado, "Orchestrator") as MockOrch, \
         patch.object(agendado, "notificar_teams") as mock_notificar, \
         patch.object(agendado, "_referencia_arquivo", return_value=None):
        MockOrigem.return_value = MagicMock()

        with pytest.raises(SystemExit) as exc_info:
            agendado.comando_verificacao_diaria(_config_duas_bases(), {}, MagicMock())

        assert exc_info.value.code == 0

    mock_notificar.assert_not_called()
    MockOrch.return_value.run.assert_not_called()


def test_segunda_execucao_concorrente_sai_com_erro_sem_tentar_nada(control_db_path):
    with patch.object(agendado, "BackupSourceClient") as MockOrigem, \
         patch.object(agendado, "Orchestrator") as MockOrch, \
         patch.object(agendado, "notificar_teams") as mock_notificar:
        MockOrigem.return_value = MagicMock()

        lock_manual = agendado.ExecutionLock(agendado.LOCK_PATH)
        assert lock_manual.acquire() is True
        try:
            with pytest.raises(SystemExit) as exc_info:
                agendado.comando_verificacao_diaria(_config_duas_bases(), {}, MagicMock())
            assert exc_info.value.code == 1
        finally:
            lock_manual.release()

    MockOrigem.return_value.connect.assert_not_called()
    MockOrch.return_value.run.assert_not_called()
    mock_notificar.assert_not_called()
