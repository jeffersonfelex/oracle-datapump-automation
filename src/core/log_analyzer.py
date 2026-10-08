"""Análise dos logs do impdp (erros ORA-, LRM- e UDI-)."""

import re
import logging
from typing import List, Dict, Tuple, Set

logger = logging.getLogger("AtualizacaoOracle")


class LogAnalyzer:
    def __init__(self, ignore_ora_list: List[str] = None):
        self.ignore_ora_list: Set[str] = set(ignore_ora_list or ["ORA-31684", "ORA-39111"])

    def analyze_log_content(
        self, log_content: str, extra_ignore: List[str] = None
    ) -> Tuple[bool, List[str], List[str]]:
        """Classifica os erros do log. Retorna (tem_erro_relevante, relevantes, tolerados).

        Um item tolerado pode ser um código (ORA-31684) ou um trecho exato de mensagem, que só
        tolera aquele caso, sem mascarar o mesmo código em outra coluna ou tabela.
        """
        relevant_errors = []
        ignored_errors = []
        ignore_list = self.ignore_ora_list | set(extra_ignore or [])

        bare_codes = {e.upper() for e in ignore_list if re.fullmatch(r"(ORA|LRM|UDI)-\d{5}", e.upper())}
        specific_snippets = [e for e in ignore_list if e.upper() not in bare_codes]

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
