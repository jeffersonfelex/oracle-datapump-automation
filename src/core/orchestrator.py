"""
Módulo Orquestrador da Automação.
Coordena todo o fluxo de atualização das bases Oracle para os sistemas corporativos.
"""

import os
import re
import glob
import logging
from datetime import datetime
from typing import List, Dict, Optional

from ..clients.backup_source import BackupSourceClient
from ..clients.oracle_ssh import OracleSSHClient
from .parfile_manager import ParfileManager
from .log_analyzer import LogAnalyzer
from ..support.notifier import Notifier
from .naming import NamingConvention

logger = logging.getLogger("AtualizacaoOracle")


class Orchestrator:
    def __init__(self, config: dict):
        self.config = config
        self.local_base_dir = config["local"]["base_dir"]
        self.sistemas_list = config["sistemas"]["ativos"]
        impdp = config["impdp"]
        self.impdp_conn_str = f"{impdp.get('user', 'system')}/{impdp.get('password', '')}@{impdp['tns']}"
        self.impdp_timeout = int(config["impdp"].get("timeout_seconds", 7200))

        self.naming = NamingConvention(config["origem"], config["impdp"], config.get("teste", {}))
        self.origem_client = BackupSourceClient(config["origem"], self.naming)
        self.oracle_client = OracleSSHClient(config["oracle"])
        self.log_analyzer = LogAnalyzer(config["alertas"].get("ignorar_ora_erros", []))
        self.notifier = Notifier(config["alertas"])

    def run(
        self,
        sistemas: Optional[List[str]] = None,
        dry_run: bool = False,
        skip_origem: bool = False,
        periodo_override: Optional[str] = None,
        from_sistema: Optional[str] = None,
        teste: bool = False
    ) -> Dict[str, str]:
        """
        Executa o pipeline completo para a lista de sistemas fornecida.
        """
        target_sistemas = list(sistemas or self.sistemas_list)
        if from_sistema:
            from_upper = from_sistema.upper()
            if from_upper in target_sistemas:
                idx = target_sistemas.index(from_upper)
                target_sistemas = target_sistemas[idx:]
            else:
                logger.warning(f"Sistema '{from_sistema}' não encontrado na lista. Usando lista completa.")

        results: Dict[str, str] = {}

        logger.info("=" * 70)
        logger.info("  INICIANDO ATUALIZAÇÃO DAS BASES ORACLE - SISTEMAS CORPORATIVOS")
        logger.info(f"  Sistemas a processar : {', '.join(target_sistemas)}")
        logger.info(f"  Modo Dry-Run         : {'ATIVO (Simulação)' if dry_run else 'DESATIVO (Produção)'}")
        logger.info(f"  Pular origem         : {skip_origem}")
        if teste:
            logger.warning(f"  Modo Teste           : ATIVO - arquivos .dmp/.dmp.gz/.log usarão o sufixo '{self.naming.test_suffix}'")
        else:
            logger.info(f"  Modo Teste           : DESATIVO (nomes de produção)")
        logger.info("=" * 70)

        # 1. Conexão ao servidor Oracle
        try:
            if not dry_run:
                self.oracle_client.connect()
                # Verifica espaço inicial em disco e limpa RMAN se necessário
                self.oracle_client.check_disk_space()
                self.oracle_client.clean_old_rman_if_needed(dry_run=dry_run)
            else:
                logger.info("[DRY-RUN] Conexão Oracle simulada com sucesso.")
        except Exception as e:
            logger.critical(f"Falha ao conectar no servidor Oracle: {e}")
            return {sys: f"ERRO_CONEXAO_ORACLE: {e}" for sys in target_sistemas}

        # 2. Conexão ao servidor de origem (se não for pulado)
        if not skip_origem and not dry_run:
            try:
                self.origem_client.connect()
            except Exception as e:
                logger.critical(f"Falha ao conectar no servidor de origem: {e}")
                self.oracle_client.disconnect()
                return {sys: f"ERRO_CONEXAO_ORIGEM: {e}" for sys in target_sistemas}

        # 3. Processamento de cada sistema corporativo
        try:
            for sistema in target_sistemas:
                logger.info("\n" + "=" * 70)
                logger.info(f"  PROCESSANDO SISTEMA: {sistema}")
                logger.info("=" * 70)

                status = self._process_single_system(
                    sistema=sistema,
                    dry_run=dry_run,
                    skip_origem=skip_origem,
                    periodo_override=periodo_override,
                    teste=teste
                )
                results[sistema] = status

        finally:
            # 4. Desconexões finais
            if not skip_origem and not dry_run:
                self.origem_client.disconnect()
            if not dry_run:
                self.oracle_client.disconnect()

        # 5. Relatório Resumido
        self._print_summary(results)
        return results

    def _process_single_system(
        self,
        sistema: str,
        dry_run: bool,
        skip_origem: bool,
        periodo_override: Optional[str],
        teste: bool = False
    ) -> str:
        """
        Executa as 8 etapas para um único sistema corporativo.
        """
        # Define diretório local do sistema
        sys_dir = os.path.join(self.local_base_dir, sistema)

        # ----------------------------------------------------------------------
        # ETAPA 1: Download ou Identificação dos 4 arquivos EXPORT
        # ----------------------------------------------------------------------
        export_date = ""
        local_files = []
        periodo = periodo_override or datetime.now().strftime("%Y-%m")

        if not skip_origem and not dry_run:
            logger.info(f"[{sistema}] [1/8] Baixando arquivos do servidor de origem...")
            try:
                # Primeiro identifica a data mais recente no servidor de origem
                date_found, _ = self.origem_client.get_system_files(sistema)
                if date_found:
                    export_date = date_found
                    # Formata ANO-MÊS com base na data do arquivo (ex: 20260902 -> 2026-09)
                    periodo = f"{export_date[:4]}-{export_date[4:6]}"

                dest_dir = os.path.join(sys_dir, periodo)
                export_date, local_files = self.origem_client.download_system_files(sistema, dest_dir)

                if not local_files:
                    logger.info(f"[{sistema}] Nenhum arquivo de exportação encontrado no servidor de origem para o período atual. Pulando sistema.")
                    return "SEM_ARQUIVOS_ORIGEM"
            except Exception as e:
                logger.error(f"[{sistema}] Falha ao baixar arquivos do servidor de origem: {e}")
                return f"ERRO_DOWNLOAD: {e}"
        else:
            # Identificação local
            logger.info(f"[{sistema}] [1/8] Verificando arquivos locais na pasta {sys_dir}...")
            dest_dir = os.path.join(sys_dir, periodo)
            if not os.path.exists(dest_dir):
                if dry_run:
                    logger.info(f"[{sistema}] [DRY-RUN] Pasta {dest_dir} será criada automaticamente ao baixar do servidor de origem.")
                    return "SUCESSO_SIMULADO"
                else:
                    logger.error(f"[{sistema}] Diretório local não encontrado: {dest_dir}")
                    return "ERRO_DIRETORIO_LOCAL_INEXISTENTE"

            gz_files = glob.glob(os.path.join(dest_dir, self.naming.export_glob(sistema)))
            if not gz_files:
                if dry_run:
                    logger.info(f"[{sistema}] [DRY-RUN] Arquivos .dmp.gz serão baixados do servidor de origem para {dest_dir}.")
                    return "SUCESSO_SIMULADO"
                else:
                    logger.error(f"[{sistema}] Nenhum arquivo .dmp.gz encontrado em {dest_dir}")
                    return "ERRO_ARQUIVOS_LOCAIS_NAO_ENCONTRADOS"

            local_files = gz_files
            # Extrai a data do primeiro arquivo encontrado
            match = re.search(r"_(\d{8})_\d+\.dmp\.gz$", gz_files[0])
            if match:
                export_date = match.group(1)

        logger.info(f"[{sistema}] Período: {periodo} | Data dos exports: {export_date}")

        # Filtra e combina todos os arquivos .dmp.gz da data identificada (remotos baixados + já existentes localmente)
        local_gz_pattern = os.path.join(dest_dir, self.naming.export_glob(sistema, export_date))
        found_gz_files = glob.glob(local_gz_pattern)
        combined_gz = set([f for f in local_files if f.endswith(".dmp.gz")] + found_gz_files)
        dmp_gz_files = sorted(list(combined_gz))

        if len(dmp_gz_files) < 2:
            logger.warning(f"[{sistema}] Esperados 2 arquivos .dmp.gz, encontrados: {len(dmp_gz_files)}")

        if dry_run:
            logger.info(f"[{sistema}] [DRY-RUN] Simulação das etapas 2 a 8 para {sistema}.")
            return "SUCESSO_SIMULADO"

        # ----------------------------------------------------------------------
        # ETAPA 2: Atualização dos Parfiles no Servidor Oracle
        # ----------------------------------------------------------------------
        logger.info(f"[{sistema}] [2/8] Atualizando parfiles no Oracle...")
        par_manager = ParfileManager(self.oracle_client.sftp, self.config["oracle"]["import_dir"], self.naming)
        parfiles = par_manager.get_parfiles_for_system(sistema)

        if not parfiles:
            logger.error(f"[{sistema}] Nenhum parfile encontrado para o sistema {sistema} no Oracle.")
            return "ERRO_PARFILES_NAO_ENCONTRADOS"

        parfile_logs: Dict[str, Optional[str]] = {}
        parfile_dumps: Dict[str, Optional[str]] = {}
        for pf in parfiles:
            ok, expected_log, expected_dump = par_manager.update_parfile_date(sistema, pf, export_date, teste=teste)
            if not ok:
                logger.error(f"[{sistema}] Falha ao atualizar parfile {pf}")
                return f"ERRO_ATUALIZACAO_PARFILE_{pf}"
            parfile_logs[pf] = expected_log
            parfile_dumps[pf] = expected_dump

        # ----------------------------------------------------------------------
        # ETAPAS 3 a 6: Upload + Descompactação + impdp + Análise, arquivo por
        # arquivo (não mais "descompacta tudo, depois importa tudo"). Sistemas
        # grandes e multi-arquivo (ex: FINANCEIRO, CONTRATOS, RH) já esgotaram o espaço em
        # /backup ("No space left on device") quando os 2 dumps descompactados
        # precisavam caber no disco ao mesmo tempo. Processando um de cada vez e
        # apagando o .dmp assim que o SEU impdp termina com sucesso, só é preciso
        # espaço para o maior arquivo individual, não para a soma de todos.
        # ----------------------------------------------------------------------
        logger.info(f"[{sistema}] [3/8 a 6/8] Preparando, importando e limpando cada arquivo...")
        sistema_lower = sistema.lower()
        has_any_critical_error = False
        executed_logs = []

        # Exceções de ORA- válidas SOMENTE para este sistema (config.yaml ->
        # alertas.ignorar_ora_erros_por_sistema). Não afeta os demais sistemas.
        extra_ignore_ora = self.config.get("alertas", {}).get("ignorar_ora_erros_por_sistema", {}).get(sistema, [])
        if extra_ignore_ora:
            logger.warning(f"[{sistema}] Exceção temporária ativa só para este sistema: {extra_ignore_ora} (ver comentário no config.yaml)")

        for pf in parfiles:
            expected_dump = parfile_dumps.get(pf)

            # Localiza o .dmp.gz local correspondente a este parfile específico
            # (mesmo nome de arquivo esperado, com ou sem sufixo de teste).
            local_gz = None
            if expected_dump:
                for gz in dmp_gz_files:
                    filename_gz = self.naming.apply_test_mode(os.path.basename(gz), teste)
                    filename_dmp = filename_gz[:-3] if filename_gz.endswith(".gz") else filename_gz
                    if filename_dmp == expected_dump:
                        local_gz = gz
                        break

            remote_dump_path = f"{self.config['oracle']['import_dir']}/{expected_dump}" if expected_dump else None
            dump_exists = False
            if remote_dump_path:
                try:
                    st = self.oracle_client.sftp.stat(remote_dump_path)
                    if st.st_size > 0:
                        dump_exists = True
                        logger.info(f"[{sistema}] Arquivo {expected_dump} já existe descompactado no Oracle ({st.st_size / (1024**3):.2f} GB). Pulando upload/gunzip.")
                except Exception:
                    dump_exists = False

            if not dump_exists:
                if not local_gz:
                    logger.warning(f"[{sistema}] Dumpfile '{expected_dump}' esperado por {pf} não existe em /backup/import/ nem localmente (não gerado no servidor de origem). Pulando este parfile.")
                    continue

                filename_gz = self.naming.apply_test_mode(os.path.basename(local_gz), teste)
                remote_gz_path = f"{self.config['oracle']['import_dir']}/{filename_gz}"
                local_gz_size = os.path.getsize(local_gz)

                # Evita reenviar o .gz (pode passar de 20 GB) se uma tentativa
                # anterior já deixou ele lá, íntegro, do jeito certo.
                gz_already_uploaded = False
                try:
                    st_gz = self.oracle_client.sftp.stat(remote_gz_path)
                    if st_gz.st_size == local_gz_size:
                        gz_already_uploaded = True
                        logger.info(f"[{sistema}] {filename_gz} já está no Oracle com o tamanho correto. Pulando upload.")
                except Exception:
                    gz_already_uploaded = False

                if not gz_already_uploaded:
                    logger.info(f"[{sistema}] Copiando {filename_gz} para /backup/import/...")
                    self.oracle_client.upload_file(local_gz, filename_gz)

                success = self.oracle_client.gunzip_file(filename_gz)
                if not success:
                    logger.error(f"[{sistema}] Falha ao descompactar {filename_gz}")
                    return f"ERRO_GUNZIP_{filename_gz}"

            relative_parfile_path = f"{sistema_lower}/{pf}"
            logger.info(f"[{sistema}] Executando impdp com {pf}...")

            exit_code, impdp_output = self.oracle_client.run_impdp(
                conn_str=self.impdp_conn_str,
                parfile_relative_path=relative_parfile_path,
                timeout=self.impdp_timeout
            )

            # Identifica o nome do arquivo de log
            expected_log = parfile_logs.get(pf)
            if not expected_log:
                # Tenta inferir nome padrão se não veio no parfile
                pf_suffix = pf.split('_')[-1].replace('.par', '')
                expected_log = f"{self.naming.log_prefix}_{sistema_lower}_{export_date}_{pf_suffix}.log"
                expected_log = self.naming.apply_test_mode(expected_log, teste)

            executed_logs.append(expected_log)

            # Baixa e inspeciona o log no Oracle
            logger.info(f"[{sistema}] Inspecionando log gerado: {expected_log}")
            local_log_temp = os.path.join(dest_dir, expected_log)
            pf_critical = False
            try:
                self.oracle_client.download_file(expected_log, local_log_temp)
                with open(local_log_temp, "r", encoding="utf-8", errors="replace") as f:
                    log_text = f.read()

                is_critical, critical_errs, ignored_errs = self.log_analyzer.analyze_log_content(log_text, extra_ignore=extra_ignore_ora)

                # No Oracle Data Pump: exit code 0 = EX_SUCC, exit code 5 = EX_WARN (sucesso com avisos não-fatais)
                if exit_code == 5 and not is_critical:
                    logger.info(f"[{sistema}] impdp concluído com avisos não-críticos (código 5 - EX_WARN). Considerado SUCESSO.")

                if is_critical or exit_code not in (0, 5):
                    pf_critical = True
                    has_any_critical_error = True
                    self.notifier.alert_critical_error(
                        sistema=sistema,
                        etapa=f"impdp ({pf})",
                        detalhes=critical_errs if critical_errs else [f"Código de saída fatal do impdp: {exit_code}"],
                        log_path=local_log_temp
                    )
                elif ignored_errs:
                    # Erro tolerado (ex: ORA-01918/ORA-00942 por schema de origem não
                    # mapeado) não barra a importação, mas pode indicar um objeto
                    # inteiro ficando de fora silenciosamente (como aconteceu com
                    # uma tabela de OUTRO_SCHEMA num dos sistemas) - avisa mesmo assim,
                    # para alguém revisar e decidir se precisa de um remap_schema.
                    self.notifier.notify_tolerated_warnings(
                        sistema=sistema,
                        etapa=f"impdp ({pf})",
                        avisos=ignored_errs,
                        log_path=local_log_temp
                    )
            except Exception as e:
                logger.error(f"[{sistema}] Não foi possível baixar/analisar o log {expected_log}: {e}")
                pf_critical = True
                has_any_critical_error = True

            # Libera espaço em disco imediatamente: se este arquivo importou com
            # sucesso, seu .dmp não é mais necessário. Não espera os demais
            # arquivos do sistema terminarem (ao contrário do log, que só é
            # limpo no fim, na ETAPA 7 - logs são pequenos, não pressionam disco).
            if not pf_critical and expected_dump:
                self.oracle_client.cleanup_files([expected_dump])

        # ----------------------------------------------------------------------
        # ETAPA 7: Decisão e Limpeza no Oracle
        # ----------------------------------------------------------------------
        logger.info(f"[{sistema}] [7/8] Gerenciando arquivos e limpeza no Oracle...")

        if has_any_critical_error:
            logger.error(f"[{sistema}] Processamento interrompido devido a erros críticos no impdp.")
            logger.warning(
                f"[{sistema}] Os arquivos .dmp e .log do impdp NÃO foram apagados "
                f"no Oracle, e os arquivos do servidor de origem NÃO foram apagados, para permitir reexecução."
            )
            return "ERRO_CRITICO_IMPDP"

        # Se não houve erro relevante: copia já ocorreu na etapa anterior (download do log para D:\...),
        # então apaga tanto os dumps quanto os logs do impdp no servidor Oracle.
        dump_cleanup_patterns = [self.naming.export_cleanup_glob(sistema, export_date)]
        log_cleanup_patterns = [self.naming.impdp_log_glob(sistema)]
        self.oracle_client.cleanup_files(dump_cleanup_patterns + log_cleanup_patterns)

        # ----------------------------------------------------------------------
        # ETAPA 8: Política de Retenção no servidor de origem
        # ----------------------------------------------------------------------
        if not skip_origem:
            logger.info(f"[{sistema}] [8/8] Aplicando política de retenção no servidor de origem (guardar 3 últimos)...")
            try:
                self.origem_client.apply_retention(sistema=sistema, keep=self.origem_client.retention_count)
            except Exception as e:
                logger.warning(f"[{sistema}] Falha ao aplicar retenção no servidor de origem: {e}")

        logger.info(f"[{sistema}] Processamento concluído com SUCESSO!")
        return "SUCESSO"

    def _print_summary(self, results: Dict[str, str]):
        """Exibe tabela de resumo da execução de todos os sistemas."""
        logger.info("\n" + "=" * 70)
        logger.info("  RESUMO DA EXECUÇÃO - SISTEMAS CORPORATIVOS")
        logger.info("=" * 70)
        for sys_name, status in results.items():
            if "SUCESSO" in status:
                logger.info(f"  {sys_name:<15} : [OK] {status}")
            else:
                logger.error(f"  {sys_name:<15} : [FALHA] {status}")
        logger.info("=" * 70)
