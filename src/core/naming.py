"""
Módulo Central de Convenções de Nomenclatura de Arquivos.

Único ponto de verdade para os padrões de nomes de arquivo usados pela automação:
  - Exportações do servidor de origem:  EXPORT_<SISTEMA>_PROD_<AAAAMMDD>_<N>.(dmp.gz|log)
  - Logs gerados pelo impdp:    impdp_<sistema_lower>_....log

Antes, esses padrões estavam duplicados (hardcoded) em backup_source.py e orchestrator.py.
Qualquer ajuste futuro na convenção de nomes (ex: mudança de prefixo/infixo pelo servidor de origem)
deve ser feito apenas aqui, e configurado via config.yaml (chaves opcionais, com os valores
atuais como padrão para não quebrar compatibilidade).

Também concentra o "modo teste" (flag --teste): insere/remove de forma idempotente um
sufixo (ex.: "_teste") nos arquivos que trafegam entre os servidores (.dmp/.dmp.gz enviados
ao Oracle e .log que retornam do impdp), sem tocar nos arquivos de origem no servidor de origem.
"""

import os
import re
from typing import Pattern

# Extensões compostas reconhecidas, da mais específica para a mais genérica,
# para que o sufixo de teste seja inserido/removido antes da extensão correta
# (ex.: "arquivo_teste.dmp.gz", não "arquivo.dmp_teste.gz").
_KNOWN_EXTENSIONS = (".dmp.gz", ".dmp", ".log", ".gz")


class NamingConvention:
    def __init__(self, origem_config: dict, impdp_config: dict, teste_config: dict = None):
        self.export_prefix = origem_config.get("filename_prefix", "EXPORT")
        self.export_infix = origem_config.get("filename_infix", "PROD")
        self.log_prefix = impdp_config.get("log_prefix", "impdp")
        self.test_suffix = (teste_config or {}).get("sufixo", "_teste")

    def export_regex(self, sistema: str) -> Pattern:
        """
        Regex para reconhecer os 4 arquivos de exportação de um sistema no servidor de origem.
        Ex.: EXPORT_FRE_PROD_20260902_1.dmp.gz / EXPORT_FRE_PROD_20260902_1.log
        """
        return re.compile(
            rf"^{re.escape(self.export_prefix)}_{re.escape(sistema)}_"
            rf"{re.escape(self.export_infix)}_(\d{{8}})_\d+\.(dmp\.gz|log)$",
            re.IGNORECASE
        )

    def export_glob(self, sistema: str, date: str = "*") -> str:
        """
        Padrão glob dos arquivos .dmp.gz de exportação de um sistema/período no servidor de origem.
        Ex.: export_glob("ESTOQUE", "20260902") -> "EXPORT_SAD_PROD_20260902_*.dmp.gz"
        """
        return f"{self.export_prefix}_{sistema}_{self.export_infix}_{date}_*.dmp.gz"

    def export_cleanup_glob(self, sistema: str, date: str) -> str:
        """
        Padrão glob para limpeza dos dumps no servidor Oracle após import bem-sucedido
        (cobre tanto o .dmp descompactado quanto eventual .dmp.gz remanescente, com ou
        sem o sufixo de teste, pois o coringa entre a data e ".dmp" já os cobre).
        """
        return f"{self.export_prefix}_{sistema}_{self.export_infix}_{date}_*.dmp*"

    def impdp_log_glob(self, sistema: str) -> str:
        """
        Padrão glob dos logs gerados pelo impdp para o sistema (com ou sem sufixo de teste).
        Ex.: impdp_log_glob("ESTOQUE") -> "impdp_estoque_*.log"
        """
        return f"{self.log_prefix}_{sistema.lower()}_*.log"

    # ------------------------------------------------------------------
    # Modo Teste: inserção/remoção idempotente do sufixo de validação
    # ------------------------------------------------------------------

    @staticmethod
    def _split_ext(filename: str):
        """Separa o nome base da extensão, reconhecendo extensões compostas (.dmp.gz)."""
        lower = filename.lower()
        for ext in _KNOWN_EXTENSIONS:
            if lower.endswith(ext):
                return filename[: -len(ext)], filename[len(filename) - len(ext):]
        return os.path.splitext(filename)

    def strip_test_suffix(self, filename: str, suffix: str = None) -> str:
        """Remove o sufixo de teste do nome do arquivo, se presente. Idempotente."""
        suffix = suffix if suffix is not None else self.test_suffix
        if not suffix:
            return filename
        base, ext = self._split_ext(filename)
        if base.endswith(suffix):
            base = base[: -len(suffix)]
        return f"{base}{ext}"

    def with_test_suffix(self, filename: str, suffix: str = None) -> str:
        """Garante que o nome do arquivo tenha o sufixo de teste. Idempotente."""
        suffix = suffix if suffix is not None else self.test_suffix
        if not suffix:
            return filename
        base, ext = self._split_ext(self.strip_test_suffix(filename, suffix))
        return f"{base}{suffix}{ext}"

    def apply_test_mode(self, filename: str, enable: bool, suffix: str = None) -> str:
        """
        Aplica o modo teste de forma idempotente, independentemente do estado anterior:
          - enable=True  -> garante que o nome TENHA o sufixo (insere se faltar).
          - enable=False -> garante que o nome NÃO TENHA o sufixo (remove se sobrou de
            uma execução de teste anterior), voltando ao nome de produção.
        """
        suffix = suffix if suffix is not None else self.test_suffix
        return self.with_test_suffix(filename, suffix) if enable else self.strip_test_suffix(filename, suffix)
