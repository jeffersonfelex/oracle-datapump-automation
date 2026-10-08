"""Atualização das datas e do sufixo de teste nos parfiles do servidor Oracle."""

import re
import logging
from typing import List, Optional, Tuple
import paramiko

from .naming import NamingConvention

logger = logging.getLogger("AtualizacaoOracle")


class ParfileManager:
    def __init__(self, sftp_client: paramiko.SFTPClient, base_import_dir: str, naming: NamingConvention):
        self.sftp = sftp_client
        self.base_import_dir = base_import_dir
        self.naming = naming

    def get_parfiles_for_system(self, sistema: str) -> List[str]:
        """Parfiles padrão do sistema (parfile_<sistema>_1/2.par), em ordem."""
        sistema_lower = sistema.lower()
        remote_sys_dir = f"{self.base_import_dir}/{sistema_lower}"

        try:
            files = self.sftp.listdir(remote_sys_dir)
            std_parfiles = sorted([f for f in files if re.match(rf"^parfile_{re.escape(sistema_lower)}_[12]\.par$", f, re.IGNORECASE)])
            if std_parfiles:
                parfiles = std_parfiles
            else:
                parfiles = sorted([f for f in files if f.endswith(".par") and "view" not in f.lower()])
            logger.info(f"Parfiles selecionados para {sistema}: {parfiles}")
            return parfiles
        except Exception as e:
            logger.error(f"Erro ao listar parfiles em {remote_sys_dir}: {e}")
            return []

    def _apply_test_mode_to_param(self, content: str, param_name: str, teste: bool) -> Tuple[str, Optional[str]]:
        """Aplica o modo teste ao valor do parâmetro e devolve (conteúdo, valor final)."""
        pattern = re.compile(rf"^(\s*{param_name}\s*=\s*)([^\s,;]+)", re.IGNORECASE | re.MULTILINE)
        match = pattern.search(content)
        if not match:
            return content, None

        original_value = match.group(2).strip()
        new_value = self.naming.apply_test_mode(original_value, teste)

        if new_value != original_value:
            content = pattern.sub(lambda m: f"{m.group(1)}{new_value}", content, count=1)
            estado = "ATIVO" if teste else "inativo (produção)"
            logger.info(f"  Parfile: {param_name} '{original_value}' -> '{new_value}' (modo teste {estado})")

        return content, new_value

    def update_parfile_date(
        self, sistema: str, parfile_name: str, new_date: str, teste: bool = False
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Troca as datas do parfile pela do export e aplica o modo teste. Retorna (ok, logfile, dumpfile)."""
        sistema_lower = sistema.lower()
        parfile_path = f"{self.base_import_dir}/{sistema_lower}/{parfile_name}"

        try:
            with self.sftp.file(parfile_path, "r") as f:
                content = f.read().decode("utf-8", errors="replace")

            found_dates = re.findall(r"(20\d{6})", content)
            if not found_dates:
                logger.warning(f"  Nenhuma data de 8 dígitos encontrada em {parfile_name}")

            new_content = content
            for old_date in set(found_dates):
                if old_date != new_date:
                    new_content = new_content.replace(old_date, new_date)
                    logger.info(f"  Parfile {parfile_name}: data {old_date} -> {new_date}")

            lines = new_content.splitlines()
            seen_params = set()
            cleaned_lines = []
            for line in lines:
                m_param = re.match(r"^\s*([a-zA-Z_]+)\s*=", line)
                if m_param:
                    pname = m_param.group(1).lower()
                    if pname == "table_exists_action":
                        if pname in seen_params:
                            logger.warning(f"  Removendo parâmetro duplicado '{line.strip()}' em {parfile_name} para evitar LRM-00112")
                            continue
                        seen_params.add(pname)
                cleaned_lines.append(line)
            new_content = "\n".join(cleaned_lines)

            new_content, dumpfile_name = self._apply_test_mode_to_param(new_content, "dumpfile", teste)
            new_content, logfile_name = self._apply_test_mode_to_param(new_content, "logfile", teste)

            if new_content != content:
                with self.sftp.file(parfile_path, "w") as f:
                    f.write(new_content.encode("utf-8"))
                logger.info(f"  Parfile atualizado com sucesso: {parfile_name}")
            else:
                logger.info(f"  Parfile {parfile_name} já estava atualizado (data {new_date})")

            return True, logfile_name, dumpfile_name

        except Exception as e:
            logger.error(f"  Erro ao atualizar {parfile_path}: {e}")
            return False, None, None
