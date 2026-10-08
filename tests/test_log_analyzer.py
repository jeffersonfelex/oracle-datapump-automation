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

    is_critical, _, _ = analyzer.analyze_log_content(log)
    assert is_critical is True

    is_critical, _, _ = analyzer.analyze_log_content(log, extra_ignore=["ORA-12345"])
    assert is_critical is False

    is_critical_de_novo, _, _ = analyzer.analyze_log_content(log)
    assert is_critical_de_novo is True
