"""
Testes do LogAnalyzer - a regra de tolerancia a erro que agendado.py reaproveita
(em vez de reimplementar uma regra propria) para decidir sucesso x falha de
cada base.
"""

from src.core.log_analyzer import LogAnalyzer


def test_codigo_bare_tolera_qualquer_ocorrencia():
    analyzer = LogAnalyzer(["ORA-31684"])
    log = 'ORA-31684: Object type TABLE already exists\n'
    is_critical, relevantes, ignorados = analyzer.analyze_log_content(log)
    assert is_critical is False
    assert ignorados == [log.strip()]


def test_trecho_especifico_so_tolera_a_mesma_coluna():
    analyzer = LogAnalyzer(['ORA-12899: value too large for column "COLUNA_EXEMPLO"'])

    log_validado = 'ORA-12899: value too large for column "COLUNA_EXEMPLO" (actual: 40, maximum: 12)'
    is_critical, _, _ = analyzer.analyze_log_content(log_validado)
    assert is_critical is False

    log_outra_coluna = 'ORA-12899: value too large for column "OUTRA_COLUNA" (actual: 100, maximum: 20)'
    is_critical, relevantes, _ = analyzer.analyze_log_content(log_outra_coluna)
    assert is_critical is True
    assert relevantes == [log_outra_coluna]


def test_erro_nao_listado_e_critico():
    analyzer = LogAnalyzer(["ORA-31684"])
    log = "ORA-00001: unique constraint violated"
    is_critical, relevantes, _ = analyzer.analyze_log_content(log)
    assert is_critical is True
    assert relevantes == [log]


def test_extra_ignore_vale_so_para_a_chamada():
    analyzer = LogAnalyzer(["ORA-31684"])
    log = "ORA-12345: erro especifico de um sistema"

    # Sem a excecao pontual, e critico.
    is_critical, _, _ = analyzer.analyze_log_content(log)
    assert is_critical is True

    # Com a excecao pontual (ex: so para um sistema), deixa de ser.
    is_critical, _, _ = analyzer.analyze_log_content(log, extra_ignore=["ORA-12345"])
    assert is_critical is False

    # A lista global do analyzer nao foi alterada pela chamada anterior.
    is_critical_de_novo, _, _ = analyzer.analyze_log_content(log)
    assert is_critical_de_novo is True
