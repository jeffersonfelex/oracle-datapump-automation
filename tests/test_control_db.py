"""Testes do banco de controle (controle/pipeline.db via ControlDB)."""

import os
from datetime import datetime, timezone

import pytest

from src.core.control_db import ControlDB


@pytest.fixture
def control(tmp_path):
    return ControlDB(os.path.join(tmp_path, "pipeline.db"))


def test_estado_inicial_e_none(control):
    assert control.get_estado("VENDAS") is None


def test_sucesso_grava_estado(control):
    inicio = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    fim = datetime(2026, 10, 2, 10, 5, tzinfo=timezone.utc)
    mtime = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)

    control.registrar_execucao(
        base="VENDAS", arquivo="EXPORT_FRE_PROD_20261002_1.dmp.gz", tamanho_origem=1000,
        mtime_origem=mtime, inicio=inicio, fim=fim, status="sucesso", mensagem="SUCESSO",
    )

    estado = control.get_estado("VENDAS")
    assert estado["arquivo"] == "EXPORT_FRE_PROD_20261002_1.dmp.gz"
    assert estado["tamanho_origem"] == 1000
    assert estado["mtime_origem"] == mtime.isoformat()


def test_erro_nao_grava_estado(control):
    inicio = fim = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    mtime = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)

    control.registrar_execucao(
        base="VENDAS", arquivo="EXPORT_FRE_PROD_20261002_1.dmp.gz", tamanho_origem=1000,
        mtime_origem=mtime, inicio=inicio, fim=fim, status="erro", mensagem="ERRO_CRITICO_IMPDP",
    )

    # Falha nao avanca o estado - a base continua "nunca processada com sucesso",
    # entao a proxima rodada tenta de novo com os mesmos dados de origem.
    assert control.get_estado("VENDAS") is None
    historico = control.listar_execucoes(base="VENDAS")
    assert len(historico) == 1
    assert historico[0]["status"] == "erro"


def test_sucesso_subsequente_atualiza_estado(control):
    mtime1 = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    mtime2 = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
    inicio = fim = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)

    control.registrar_execucao(
        base="VENDAS", arquivo="a1.dmp.gz", tamanho_origem=1000, mtime_origem=mtime1,
        inicio=inicio, fim=fim, status="sucesso", mensagem="SUCESSO",
    )
    control.registrar_execucao(
        base="VENDAS", arquivo="a2.dmp.gz", tamanho_origem=2000, mtime_origem=mtime2,
        inicio=inicio, fim=fim, status="sucesso", mensagem="SUCESSO",
    )

    estado = control.get_estado("VENDAS")
    assert estado["arquivo"] == "a2.dmp.gz"
    assert estado["tamanho_origem"] == 2000

    # As duas execucoes ficam no historico, uma linha nao sobrescreve a outra.
    assert len(control.listar_execucoes(base="VENDAS")) == 2


def test_status_invalido_levanta_erro(control):
    with pytest.raises(ValueError):
        control.registrar_execucao(
            base="VENDAS", arquivo="a.dmp.gz", tamanho_origem=1, mtime_origem=None,
            inicio=datetime.now(timezone.utc), fim=datetime.now(timezone.utc),
            status="pendente", mensagem="x",
        )


def test_bases_independentes(control):
    inicio = fim = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    control.registrar_execucao(
        base="VENDAS", arquivo="a.dmp.gz", tamanho_origem=1, mtime_origem=None,
        inicio=inicio, fim=fim, status="sucesso", mensagem="SUCESSO",
    )
    control.registrar_execucao(
        base="FROTA", arquivo="b.dmp.gz", tamanho_origem=2, mtime_origem=None,
        inicio=inicio, fim=fim, status="erro", mensagem="ERRO_CRITICO_IMPDP",
    )

    assert control.get_estado("VENDAS") is not None
    assert control.get_estado("FROTA") is None  # falha de uma base nao contamina a outra
