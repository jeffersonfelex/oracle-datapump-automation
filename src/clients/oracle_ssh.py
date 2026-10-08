"""Cliente SSH/SFTP do servidor Oracle: upload, gunzip, impdp e limpeza."""

import os
import logging
import paramiko
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger("AtualizacaoOracle")


class OracleSSHClient:
    def __init__(self, config: dict):
        self.host = config.get("host", "oracle-db.example.internal")
        self.port = int(config.get("port", 22))
        self.user = config.get("user", "oracle")
        self.password = config.get("password", "")
        self.import_dir = config.get("import_dir", "/backup/import")
        self.rman_dir = config.get("rman_dir", "/backup/rman")
        self.min_disk_free_gb = float(config.get("min_disk_free_gb", 15))

        self.ssh: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None

    def connect(self):
        """Estabelece conexão SSH e SFTP com o servidor Oracle."""
        logger.info(f"Conectando ao Oracle ({self.host}:{self.port}) via SSH/SFTP...")
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            timeout=30,
            look_for_keys=False,
            allow_agent=False
        )
        self.sftp = self.ssh.open_sftp()
        logger.info(f"Conectado: Oracle ({self.host}:{self.port})")

    def disconnect(self):
        """Encerra sessões SFTP e SSH."""
        if self.sftp:
            try:
                self.sftp.close()
            except Exception:
                pass
            self.sftp = None

        if self.ssh:
            try:
                self.ssh.close()
            except Exception:
                pass
            self.ssh = None
        logger.debug("Conexão encerrada: Oracle")

    def execute_command(self, command: str, cwd: Optional[str] = None, timeout: int = 3600) -> Tuple[int, str]:
        """Executa um comando remoto e devolve (exit_code, saída)."""
        if not self.ssh:
            raise RuntimeError("Sessão SSH não conectada.")

        oracle_env = "source ~/.bash_profile 2>/dev/null; "
        full_cmd = f"{oracle_env}cd {cwd} && {command}" if cwd else f"{oracle_env}{command}"
        logger.debug(f"SSH Exec: {full_cmd}")

        stdin, stdout, stderr = self.ssh.exec_command(full_cmd, timeout=timeout)
        stdout.channel.settimeout(timeout)

        output_lines = []
        for line in iter(stdout.readline, ""):
            clean_line = line.rstrip()
            if clean_line:
                output_lines.append(clean_line)
                logger.debug(f"  [remote] {clean_line}")

        err_lines = stderr.read().decode("utf-8", errors="replace").strip()
        if err_lines:
            output_lines.append(err_lines)
            logger.warning(f"  [stderr] {err_lines}")

        exit_code = stdout.channel.recv_exit_status()
        return exit_code, "\n".join(output_lines)

    def check_disk_space(self) -> Dict[str, str]:
        """Executa 'df -h' e retorna as informações dos sistemas de arquivos."""
        exit_code, output = self.execute_command("df -h")
        logger.info("Espaço em disco no Oracle:")
        for line in output.splitlines()[:15]:
            logger.info(f"  {line}")
        return {"output": output, "exit_code": str(exit_code)}

    def clean_old_rman_if_needed(self, dry_run: bool = False):
        """Remove a pasta RMAN mais antiga se o espaço livre ficar abaixo do mínimo."""
        exit_code, output = self.execute_command(f"df -BG {self.import_dir} | tail -1")
        try:
            parts = output.split()
            avail_gb = float(parts[3].replace("G", ""))
            logger.info(f"Espaço disponível em {self.import_dir}: {avail_gb:.1f} GB")

            if avail_gb < self.min_disk_free_gb:
                logger.warning(f"Espaço abaixo do limite ({self.min_disk_free_gb} GB)! Verificando pasta {self.rman_dir}...")
                exit_code, dirs = self.execute_command(f"ls -dt {self.rman_dir}/*/")
                rman_folders = [d.strip() for d in dirs.splitlines() if d.strip()]
                if rman_folders:
                    oldest = rman_folders[-1]
                    logger.warning(f"Removendo pasta de RMAN do mês mais antigo: {oldest}")
                    if not dry_run:
                        self.execute_command(f"rm -rf {oldest}")
        except Exception as e:
            logger.error(f"Não foi possível calcular espaço ou limpar RMAN: {e}")

    def upload_file(self, local_path: str, remote_filename: str):
        """Envia o arquivo e confere o tamanho remoto, tentando até 3 vezes."""
        if not self.sftp:
            raise RuntimeError("SFTP não conectado.")

        remote_path = f"{self.import_dir}/{remote_filename}"
        expected_size = os.path.getsize(local_path)

        for attempt in range(3):
            logger.info(f"  Upload SFTP: {os.path.basename(local_path)} -> {remote_path}")
            self.sftp.put(local_path, remote_path)

            actual_size = self.sftp.stat(remote_path).st_size
            if actual_size == expected_size:
                logger.info(f"  Upload concluído: {remote_filename}")
                return

            logger.warning(
                f"  Upload truncado/incompleto ({attempt+1}/3): esperado {expected_size} bytes, "
                f"ficou {actual_size} bytes em {remote_filename}. Tentando de novo..."
            )
            if attempt == 2:
                raise IOError(
                    f"Upload de {remote_filename} para o Oracle ficou incompleto após 3 tentativas "
                    f"(esperado {expected_size} bytes, obtido {actual_size} bytes)"
                )

    def download_file(self, remote_filename: str, local_path: str):
        """Baixa um arquivo do Oracle para o disco local."""
        if not self.sftp:
            raise RuntimeError("SFTP não conectado.")

        remote_path = f"{self.import_dir}/{remote_filename}"
        logger.info(f"  Download SFTP: {remote_path} -> {local_path}")
        self.sftp.get(remote_path, local_path)

    def gunzip_file(self, filename_gz: str) -> bool:
        """Descompacta o .dmp.gz no diretório de import."""
        logger.info(f"  Descompactando via SSH: gunzip -f {filename_gz}")
        exit_code, output = self.execute_command(f"gunzip -f {filename_gz}", cwd=self.import_dir)
        if exit_code == 0:
            logger.info(f"  Descompactação concluída: {filename_gz[:-3]}")
            return True
        else:
            logger.error(f"  Falha no gunzip ({exit_code}): {output}")
            return False

    def run_impdp(self, conn_str: str, parfile_relative_path: str, timeout: int = 7200) -> Tuple[int, str]:
        """Executa o impdp com o parfile informado."""
        full_parfile = f"{self.import_dir}/{parfile_relative_path}" if not parfile_relative_path.startswith("/") else parfile_relative_path
        cmd = f"impdp '{conn_str}' parfile='{full_parfile}'"

        logger.info(f"  Executando impdp: parfile={full_parfile}")
        exit_code, output = self.execute_command(cmd, cwd=self.import_dir, timeout=timeout)
        return exit_code, output

    def cleanup_files(self, patterns: List[str]):
        """Remove arquivos temporários no diretório /backup/import/."""
        for pattern in patterns:
            cmd = f"rm -f {self.import_dir}/{pattern}"
            logger.info(f"  Oracle cleanup: rm {pattern}")
            self.execute_command(cmd)
