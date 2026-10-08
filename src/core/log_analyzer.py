"""
Módulo de Análise e Validação de Logs do Oracle Data Pump (impdp).
Identifica erros ORA-, LRM- e UDI-, filtrando exceções benignas conhecidas.
"""

import re
import logging
from typing import List, Dict, Tuple, Set

logger = logging.getLogger("AtualizacaoOracle")


class LogAnalyzer:
    def __init__(self, ignore_ora_list: List[str] = None):
        # Códigos que não bloqueiam a importação (ex: objeto já existente)
        self.ignore_ora_list: Set[str] = set(ignore_ora_list or ["ORA-31684", "ORA-39111"])

    def analyze_log_content(
        self, log_content: str, extra_ignore: List[str] = None
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Analisa o texto completo de um arquivo .log gerado pelo impdp.

        `extra_ignore`: códigos adicionais a tolerar SOMENTE nesta chamada (ex: uma
        exceção conhecida e válida apenas para um sistema específico), sem alterar
        a lista global usada pelos demais sistemas.

        Retorna:
          - has_relevant_errors (bool): True se houver erro impeditivo.
          - relevant_errors (list): Lista de linhas com erros relevantes.
          - ignored_errors (list): Lista de linhas com erros ignorados.
        """
        relevant_errors = []
        ignored_errors = []
        ignore_list = self.ignore_ora_list | set(extra_ignore or [])

        # Cada entrada da lista pode ser:
        #   - um código isolado (ex: "ORA-31684"): ignora QUALQUER ocorrência desse código;
        #   - um trecho mais específico (ex: 'ORA-12899: value too large for column
        #     "COLUNA_EXEMPLO"'): ignora SOMENTE quando esse texto aparece
        #     literalmente na linha, permitindo tolerar um caso pontual e validado sem
        #     mascarar o mesmo código de erro ocorrendo em outra coluna/tabela.
        bare_codes = {e.upper() for e in ignore_list if re.fullmatch(r"(ORA|LRM|UDI)-\d{5}", e.upper())}
        specific_snippets = [e for e in ignore_list if e.upper() not in bare_codes]

        # Padrão para capturar ORA-, LRM- e UDI-
        error_pattern = re.compile(r"^(ORA-\d{5}|LRM-\d{5}|UDI-\d{5}):(.*)$", re.MULTILINE)

        for line in log_content.splitlines():
            line_clean = line.strip()
            match = error_pattern.match(line_clean)
            if match:
                code = match.group(1).upper()
                if code in bare_codes or any(snippet in line_clean for snippet in specific_snippets):
                    ignored_errors.append(line_clean)
                else:
                    relevant_errors.append(line_clean)

        has_relevant_errors = len(relevant_errors) > 0

        if has_relevant_errors:
            logger.error("=" * 60)
            logger.error("  ALERTA: ERROS RELEVANTES ENCONTRADOS NO LOG DO IMPDP!")
            logger.error("=" * 60)
            for err in relevant_errors[:15]:
                logger.error(f"    {err}")
            if len(relevant_errors) > 15:
                logger.error(f"    ... e mais {len(relevant_errors) - 15} erro(s).")
            logger.error("=" * 60)
        elif ignored_errors:
            logger.info(f"  {len(ignored_errors)} avisos conhecidos/ignorados no log (ex: {list(ignore_list)}).")
        else:
            logger.info("  Nenhum erro ORA- detectado no log. Importação concluída com sucesso.")

        return has_relevant_errors, relevant_errors, ignored_errors
