"""Convenção única dos nomes de arquivo (exports, logs do impdp) e do sufixo do modo teste."""

import os
import re
from typing import Pattern

_KNOWN_EXTENSIONS = (".dmp.gz", ".dmp", ".log", ".gz")


class NamingConvention:
    def __init__(self, origem_config: dict, impdp_config: dict, teste_config: dict = None):
        self.export_prefix = origem_config.get("filename_prefix", "EXPORT")
        self.export_infix = origem_config.get("filename_infix", "PROD")
        self.log_prefix = impdp_config.get("log_prefix", "impdp")
        self.test_suffix = (teste_config or {}).get("sufixo", "_teste")

    def export_regex(self, sistema: str) -> Pattern:
        """Regex dos arquivos de export do sistema; o grupo 1 captura a data (AAAAMMDD)."""
        return re.compile(
            rf"^{re.escape(self.export_prefix)}_{re.escape(sistema)}_"
            rf"{re.escape(self.export_infix)}_(\d{{8}})_\d+\.(dmp\.gz|log)$",
            re.IGNORECASE
        )

    def export_glob(self, sistema: str, date: str = "*") -> str:
        """Glob dos .dmp.gz de export do sistema na data."""
        return f"{self.export_prefix}_{sistema}_{self.export_infix}_{date}_*.dmp.gz"

    def export_cleanup_glob(self, sistema: str, date: str) -> str:
        """Glob dos dumps do sistema no Oracle (.dmp e .dmp.gz, com ou sem sufixo de teste)."""
        return f"{self.export_prefix}_{sistema}_{self.export_infix}_{date}_*.dmp*"

    def impdp_log_glob(self, sistema: str) -> str:
        """Glob dos logs do impdp do sistema."""
        return f"{self.log_prefix}_{sistema.lower()}_*.log"

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
        """Garante o nome com o sufixo de teste (enable=True) ou sem ele (enable=False)."""
        suffix = suffix if suffix is not None else self.test_suffix
        return self.with_test_suffix(filename, suffix) if enable else self.strip_test_suffix(filename, suffix)
