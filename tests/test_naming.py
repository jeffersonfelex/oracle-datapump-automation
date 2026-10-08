from src.core.naming import NamingConvention

NAMING = NamingConvention({"filename_prefix": "EXPORT", "filename_infix": "PROD"}, {"log_prefix": "impdp"}, {"sufixo": "_teste"})


def test_regex_reconhece_dump_e_log_e_captura_a_data():
    regex = NAMING.export_regex("VENDAS")
    assert regex.match("EXPORT_VENDAS_PROD_20260902_1.dmp.gz").group(1) == "20260902"
    assert regex.match("EXPORT_VENDAS_PROD_20260902_2.log")
    assert not regex.match("EXPORT_VENDAS_PROD_20260902_1.dmp")       # só .dmp.gz ou .log na origem
    assert not regex.match("EXPORT_COMPRAS_PROD_20260902_1.dmp.gz")   # outro sistema


def test_globs():
    assert NAMING.export_glob("ESTOQUE", "20260902") == "EXPORT_ESTOQUE_PROD_20260902_*.dmp.gz"
    assert NAMING.export_cleanup_glob("ESTOQUE", "20260902") == "EXPORT_ESTOQUE_PROD_20260902_*.dmp*"
    assert NAMING.impdp_log_glob("ESTOQUE") == "impdp_estoque_*.log"


def test_sufixo_de_teste_respeita_extensao_composta_e_e_idempotente():
    nome = "EXPORT_VENDAS_PROD_20260902_1.dmp.gz"
    com_sufixo = NAMING.apply_test_mode(nome, True)
    assert com_sufixo == "EXPORT_VENDAS_PROD_20260902_1_teste.dmp.gz"
    assert NAMING.apply_test_mode(com_sufixo, True) == com_sufixo     # não duplica
    assert NAMING.apply_test_mode(com_sufixo, False) == nome          # volta ao nome de produção
    assert NAMING.apply_test_mode("impdp_vendas_1.log", True) == "impdp_vendas_1_teste.log"
