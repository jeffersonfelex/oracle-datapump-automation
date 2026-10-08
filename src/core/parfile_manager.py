"""
Módulo de Gerenciamento de Arquivos Parfile no Servidor Oracle.
Lê, atualiza a máscara de datas nos parfiles, aplica/remove o sufixo do modo
teste em dumpfile/logfile, e extrai os nomes finais dos arquivos referenciados.
"""

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
        """
        Lista os arquivos .par existentes para o sistema na pasta /backup/import/<sistema>/.
        Retorna os nomes dos arquivos ordenados, ex: ['parfile_vendas_1.par', 'parfile_vendas_2.par']
        """
        sistema_lower = sistema.lower()
        remote_sys_dir = f"{self.base_import_dir}/{sistema_lower}"

        try:
            files = self.sftp.listdir(remote_sys_dir)
            # Padrão: cada sistema tem até 2 parfiles (um por arquivo de dump): parfile_<sistema>_1/2.par
            # Ignora parfiles de views ou outros que não fazem parte do dump mensal padrão
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
        """
        Localiza o parâmetro (dumpfile= ou logfile=) no conteúdo do parfile e garante,
        de forma idempotente, que seu valor tenha (teste=True) ou não tenha (teste=False)
        o sufixo de teste configurado (ex.: "_teste"), independente de execuções anteriores.
        Retorna (conteúdo atualizado, valor final do parâmetro ou None se não encontrado).
        """
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
        """
        Atualiza as strings de data (formato YYYYMMDD, 8 dígitos) dentro do arquivo .par
        e garante o sufixo do modo teste em dumpfile/logfile (inserido se teste=True,
        removido se teste=False, mesmo que tenha sobrado de uma execução de teste anterior).
        Retorna (sucesso: bool, logfile_name: Optional[str], dumpfile_name: Optional[str]).
        """
        sistema_lower = sistema.lower()
        parfile_path = f"{self.base_import_dir}/{sistema_lower}/{parfile_name}"

        try:
            # Lê o conteúdo original do parfile
            with self.sftp.file(parfile_path, "r") as f:
                content = f.read().decode("utf-8", errors="replace")

            # Identifica datas existentes no parfile (sequência de 8 dígitos iniciada em 20)
            found_dates = re.findall(r"(20\d{6})", content)
            if not found_dates:
                logger.warning(f"  Nenhuma data de 8 dígitos encontrada em {parfile_name}")

            # Substitui as datas antigas pela nova data
            new_content = content
            for old_date in set(found_dates):
                if old_date != new_date:
                    new_content = new_content.replace(old_date, new_date)
                    logger.info(f"  Parfile {parfile_name}: data {old_date} -> {new_date}")

            # Remove parâmetros duplicados (ex: table_exists_action duplicado que causa LRM-00112)
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

            # Garante (insere ou remove) o sufixo do modo teste em dumpfile= e logfile=
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
