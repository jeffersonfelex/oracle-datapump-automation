"""
Módulo de Integração com o Servidor de Origem dos Backups.
Gerencia conexão via FTP ou SFTP, download dos 4 arquivos EXPORT por sistema
e política de retenção (guardar somente os 3 últimos arquivos).
"""

import os
import ftplib
import logging
import paramiko
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

from ..core.naming import NamingConvention

logger = logging.getLogger("AtualizacaoOracle")


class BackupSourceClient:
    def __init__(self, config: dict, naming: NamingConvention):
        self.host = config.get("host", "backup.example.com")
        self.port = int(config.get("port", 21))
        self.protocol = config.get("protocol", "ftp").lower()
        self.user = config.get("user", "")
        self.password = config.get("password", "")
        self.remote_dir = config.get("remote_dir", "/backups/export")
        self.retention_count = int(config.get("retention_count", 3))
        self.naming = naming

        self.ftp: Optional[ftplib.FTP] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
        self.ssh_transport: Optional[paramiko.Transport] = None

    def connect(self):
        """Estabelece conexão com o servidor de origem."""
        if self.protocol == "ftp":
            logger.info(f"Conectando ao servidor de origem via FTP ({self.host}:{self.port})...")
            self.ftp = ftplib.FTP()
            self.ftp.connect(self.host, self.port, timeout=30)
            self.ftp.login(self.user, self.password)
            self.ftp.cwd(self.remote_dir)
            logger.info(f"Conectado: origem ({self.host}:{self.port}) - FTP")
        elif self.protocol == "sftp":
            logger.info(f"Conectando ao servidor de origem via SFTP ({self.host}:{self.port})...")
            self.ssh_transport = paramiko.Transport((self.host, self.port))
            self.ssh_transport.connect(username=self.user, password=self.password)
            self.sftp = paramiko.SFTPClient.from_transport(self.ssh_transport)
            self.sftp.chdir(self.remote_dir)
            logger.info(f"Conectado: origem ({self.host}:{self.port}) - SFTP")
        else:
            raise ValueError(f"Protocolo não suportado: {self.protocol}")

    def disconnect(self):
        """Fecha a conexão com o servidor de origem."""
        try:
            if self.ftp:
                self.ftp.quit()
        except Exception:
            pass
        finally:
            self.ftp = None

        try:
            if self.sftp:
                self.sftp.close()
            if self.ssh_transport:
                self.ssh_transport.close()
        except Exception:
            pass
        finally:
            self.sftp = None
            self.ssh_transport = None
        logger.debug("Conexão encerrada: origem")

    def ensure_connected(self):
        """Garante que a conexão com o servidor de origem está ativa, reconectando se expirou."""
        if self.protocol == "ftp":
            if self.ftp:
                try:
                    self.ftp.voidcmd("NOOP")
                    return
                except Exception:
                    logger.warning("Conexão FTP com o servidor de origem expirou ou caiu. Reconectando...")
                    try:
                        self.ftp.close()
                    except Exception:
                        pass
                    self.ftp = None
            self.connect()
        elif self.protocol == "sftp":
            if self.ssh_transport and self.ssh_transport.is_active():
                return
            logger.warning("Conexão SFTP com o servidor de origem expirou ou caiu. Reconectando...")
            self.disconnect()
            self.connect()

    def list_files(self) -> List[str]:
        """Lista todos os arquivos no diretório remoto com garantia de conexão."""
        for attempt in range(3):
            try:
                self.ensure_connected()
                if self.protocol == "ftp" and self.ftp:
                    return self.ftp.nlst()
                elif self.protocol == "sftp" and self.sftp:
                    return self.sftp.listdir()
            except Exception as e:
                logger.warning(f"Tentativa {attempt+1}/3 de listar arquivos no servidor de origem falhou: {e}")
                self.disconnect()
        return []

    def get_system_files(self, sistema: str) -> Tuple[str, List[str]]:
        """
        Localiza os 4 arquivos do sistema mais recentes no servidor de origem.
        Retorna uma tupla: (data_str, lista_arquivos)
        Exemplo de retorno: ('20260902', ['EXPORT_FRE_PROD_20260902_1.dmp.gz', ...])
        """
        all_files = self.list_files()
        pattern = self.naming.export_regex(sistema)

        files_by_date: Dict[str, List[str]] = {}
        for f in all_files:
            match = pattern.match(f)
            if match:
                date_str = match.group(1)
                files_by_date.setdefault(date_str, []).append(f)

        if not files_by_date:
            logger.warning(f"Origem - {sistema}: Nenhum arquivo de exportação encontrado.")
            return "", []

        available_dates = sorted(files_by_date.keys())
        if len(available_dates) > 1:
            logger.info(f"Origem - {sistema}: múltiplas datas {available_dates} - usando apenas a mais recente ({available_dates[-1]})")

        latest_date = available_dates[-1]
        selected_files = sorted(files_by_date[latest_date])
        logger.info(f"Origem - {sistema}: {len(selected_files)} arquivo(s) encontrado(s) para a data {latest_date}")
        return latest_date, selected_files

    def get_remote_size(self, remote_file: str) -> Optional[int]:
        """Consulta o tamanho do arquivo no servidor de origem, sem baixar o conteúdo."""
        for attempt in range(3):
            try:
                self.ensure_connected()
                if self.protocol == "ftp" and self.ftp:
                    self.ftp.voidcmd("TYPE I")  # modo binário, senão SIZE pode falhar/variar
                    return self.ftp.size(remote_file)
                elif self.protocol == "sftp" and self.sftp:
                    return self.sftp.stat(remote_file).st_size
            except Exception as e:
                logger.warning(f"  Falha ao consultar tamanho ({attempt+1}/3) de {remote_file}: {e}")
                self.disconnect()
        return None

    def get_remote_mtime(self, remote_file: str) -> Optional[datetime]:
        """
        Consulta a data de modificação do arquivo no servidor de origem (UTC), sem baixar
        o conteúdo. Usado pela verificação diária (agendado.py) para saber se um
        arquivo é novo/foi reenviado, e para esperar ele "assentar" (ver
        MIN_IDLE_MINUTES) antes de processar - evita pegar um arquivo ainda sendo
        transferido pela origem.
        """
        for attempt in range(3):
            try:
                self.ensure_connected()
                if self.protocol == "ftp" and self.ftp:
                    # MDTM retorna "213" + "YYYYMMDDHHMMSS" (UTC) se o servidor suportar.
                    resp = self.ftp.sendcmd(f"MDTM {remote_file}")
                    ts = resp.split()[-1]
                    return datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                elif self.protocol == "sftp" and self.sftp:
                    st = self.sftp.stat(remote_file)
                    return datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            except Exception as e:
                logger.warning(f"  Falha ao consultar data de modificação ({attempt+1}/3) de {remote_file}: {e}")
                self.disconnect()
        return None

    def download_file(self, remote_file: str, local_path: str):
        """
        Baixa um único arquivo do servidor de origem para o disco local com suporte a retry.
        Após cada tentativa, confere o tamanho do arquivo baixado contra o tamanho
        real no servidor — um download interrompido/truncado (ex: conexão instável,
        limite de conexões simultâneas) não fica sem barulho por trás de um arquivo
        que só parece "presente"; ele é tratado como falha e re-tentado.
        """
        logger.info(f"  Download: {remote_file} -> {local_path}")
        expected_size = self.get_remote_size(remote_file)

        for attempt in range(3):
            try:
                self.ensure_connected()
                if self.protocol == "ftp" and self.ftp:
                    with open(local_path, "wb") as f:
                        self.ftp.retrbinary(f"RETR {remote_file}", f.write, blocksize=65536)
                elif self.protocol == "sftp" and self.sftp:
                    self.sftp.get(remote_file, local_path)

                if expected_size is not None:
                    actual_size = os.path.getsize(local_path)
                    if actual_size != expected_size:
                        raise IOError(
                            f"Tamanho divergente após download: esperado {expected_size} bytes, "
                            f"obtido {actual_size} bytes (download truncado/incompleto)"
                        )
                return
            except Exception as e:
                logger.warning(f"  Falha no download ({attempt+1}/3) de {remote_file}: {e}")
                try:
                    if os.path.exists(local_path):
                        os.remove(local_path)  # remove parcial antes de tentar de novo
                except Exception:
                    pass
                self.disconnect()
                if attempt == 2:
                    raise

    def download_system_files(self, sistema: str, local_dest_dir: str) -> Tuple[str, List[str]]:
        """
        Localiza e baixa os 4 arquivos do sistema para a pasta local especificada.
        Retorna a data detectada e a lista de caminhos locais baixados.
        """
        latest_date, remote_files = self.get_system_files(sistema)
        if not remote_files:
            return "", []

        os.makedirs(local_dest_dir, exist_ok=True)
        downloaded_paths = []

        for r_file in remote_files:
            l_path = os.path.join(local_dest_dir, r_file)
            # Só pula o download se o arquivo já existir localmente com o MESMO tamanho
            # do servidor (não apenas "maior que zero" — isso já deixou passar um
            # download truncado em silêncio, que ficou sendo reenviado por semanas).
            if os.path.exists(l_path) and os.path.getsize(l_path) > 0:
                remote_size = self.get_remote_size(r_file)
                local_size = os.path.getsize(l_path)
                if remote_size is not None and local_size != remote_size:
                    logger.warning(
                        f"  Arquivo local {r_file} tem tamanho diferente do servidor "
                        f"({local_size} vs {remote_size} bytes) — baixando novamente."
                    )
                else:
                    logger.info(f"  Arquivo já presente localmente: {r_file}")
                    downloaded_paths.append(l_path)
                    continue

            self.download_file(r_file, l_path)
            downloaded_paths.append(l_path)

        logger.info(f"  {len(downloaded_paths)} arquivo(s) salvos em {local_dest_dir}")
        return latest_date, downloaded_paths

    def apply_retention(self, sistema: str, keep: int = 3, dry_run: bool = False):
        """
        Aplica a política de retenção no servidor de origem:
        Apaga os arquivos antigos do sistema, guardando somente os 'keep' últimos.
        """
        all_files = self.list_files()
        pattern = self.naming.export_regex(sistema)

        system_files = [f for f in all_files if pattern.match(f)]
        if not system_files:
            return

        # Agrupa arquivos por data para não quebrar conjuntos de export
        files_by_date: Dict[str, List[str]] = {}
        for f in system_files:
            match = pattern.match(f)
            if match:
                dt = match.group(1)
                files_by_date.setdefault(dt, []).append(f)

        sorted_dates = sorted(files_by_date.keys())
        if len(sorted_dates) <= keep:
            logger.info(f"Origem - {sistema}: total de {len(sorted_dates)} data(s) de export ({len(system_files)} arquivos). Retenção OK (limite={keep} datas).")
            return

        dates_to_delete = sorted_dates[:-keep]
        files_to_delete = []
        for dt in dates_to_delete:
            files_to_delete.extend(files_by_date[dt])

        if not files_to_delete:
            return

        logger.info(f"Origem - {sistema}: removendo {len(files_to_delete)} arquivo(s) de {len(dates_to_delete)} data(s) antiga(s) para manter as {keep} datas mais recentes...")
        for f in files_to_delete:
            if dry_run:
                logger.info(f"  [DRY-RUN] Remoção simulada no servidor de origem: {f}")
            else:
                try:
                    self.ensure_connected()
                    if self.protocol == "ftp" and self.ftp:
                        self.ftp.delete(f)
                    elif self.protocol == "sftp" and self.sftp:
                        self.sftp.remove(f)
                    logger.info(f"  Removido do servidor de origem: {f}")
                except Exception as e:
                    logger.error(f"  Erro ao remover {f} no servidor de origem: {e}")
