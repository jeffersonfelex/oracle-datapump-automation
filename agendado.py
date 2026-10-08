"""
Ponto de Entrada da Verificação Diária Agendada.

Diferente de main.py (execução manual, escolhida pelo operador), este script
roda sozinho todo dia (Agendador de Tarefas do Windows, 02:00) e decide por
conta própria quais sistemas processar: só os que têm um arquivo novo/alterado
no servidor de origem desde a última vez que foram importados com sucesso.

Uso:
  py agendado.py              # verificação diária normal
  py agendado.py --seed       # mostra o estado atual no servidor de origem (não grava nada)
  py agendado.py --seed --confirmar   # grava esse estado como ponto de partida

O "ponto de partida" existe para a primeira execução não acionar uma recarga
completa de todos os sistemas (o banco de controle começa vazio, e sem isso
TUDO pareceria "novo"). Só grava com --confirmar, depois de você validar que
as versões mostradas já estão carregadas no banco de destino.
"""

import os
import sys
import argparse
from datetime import datetime, timedelta, timezone

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from src.config_loader import aplicar_segredos, load_config, load_env
from src.support.logger import setup_logger
from src.support.teams_notifier import notificar_teams
from src.core.naming import NamingConvention
from src.core.control_db import ControlDB
from src.core.lock import ExecutionLock
from src.core.orchestrator import Orchestrator
from src.clients.backup_source import BackupSourceClient

MIN_IDLE_MINUTES = 30
CONTROL_DB_PATH = os.path.join(CURRENT_DIR, "controle", "pipeline.db")
LOCK_PATH = os.path.join(CURRENT_DIR, "controle", "agendado.lock")


def deve_processar(estado, ref, agora, min_idle_minutes: int = MIN_IDLE_MINUTES):
    """
    Decide se uma base deve ser processada nesta rodada, a partir do estado
    gravado (ou None, se nunca processada) e da referência atual no servidor de origem
    (ou None, se não há arquivo). Função pura (sem rede/IO) para ser testável
    diretamente. Retorna (deve_processar: bool, motivo: str).
    """
    if ref is None:
        return False, "sem_arquivo"
    if ref["mtime"] is None:
        return False, "mtime_desconhecido"

    idade = agora - ref["mtime"]
    if idade < timedelta(minutes=min_idle_minutes):
        return False, "modificado_recentemente"

    if (
        estado
        and estado["arquivo"] == ref["arquivo"]
        and estado["tamanho_origem"] == ref["tamanho"]
        and estado["mtime_origem"] == ref["mtime"].isoformat()
    ):
        return False, "sem_mudanca"

    return True, "novo_ou_alterado"


def _referencia_arquivo(origem: BackupSourceClient, sistema: str):
    """
    Identifica o arquivo de referência (o mais recente) de um sistema no
    servidor de origem e seu tamanho/data de modificação. Retorna None se não houver
    nenhum arquivo para o sistema.
    """
    _, arquivos = origem.get_system_files(sistema)
    if not arquivos:
        return None
    ref = arquivos[0]
    tamanho = origem.get_remote_size(ref)
    mtime = origem.get_remote_mtime(ref)
    return {"arquivo": ref, "tamanho": tamanho, "mtime": mtime}


def comando_seed(config: dict, confirmar: bool):
    """Mostra (ou, com --confirmar, grava) o estado atual de cada sistema como ponto de partida."""
    naming = NamingConvention(config["origem"], config["impdp"], config.get("teste", {}))
    origem = BackupSourceClient(config["origem"], naming)
    origem.connect()

    sistemas = config["sistemas"]["ativos"]
    referencias = {}
    print(f"{'Sistema':<14} {'Arquivo':<45} {'Tamanho':>14} {'Modificado em (UTC)'}")
    print("-" * 100)
    for sistema in sistemas:
        ref = _referencia_arquivo(origem, sistema)
        if not ref:
            print(f"{sistema:<14} {'(nenhum arquivo no servidor de origem)':<45}")
            continue
        referencias[sistema] = ref
        tamanho_gb = (ref["tamanho"] / (1024 ** 3)) if ref["tamanho"] else 0
        mtime_str = ref["mtime"].isoformat() if ref["mtime"] else "desconhecido"
        print(f"{sistema:<14} {ref['arquivo']:<45} {tamanho_gb:>10.2f} GB  {mtime_str}")

    origem.disconnect()

    if not confirmar:
        print("\n[Modo apenas leitura - nada foi gravado. Rode com --seed --confirmar para gravar este estado.]")
        return

    control = ControlDB(CONTROL_DB_PATH)
    agora = datetime.now(timezone.utc)
    for sistema, ref in referencias.items():
        control.registrar_execucao(
            base=sistema,
            arquivo=ref["arquivo"],
            tamanho_origem=ref["tamanho"],
            mtime_origem=ref["mtime"],
            inicio=agora,
            fim=agora,
            status="sucesso",
            mensagem="ponto de partida",
        )
    print(f"\nPonto de partida gravado para {len(referencias)} sistema(s) em {CONTROL_DB_PATH}.")


def comando_verificacao_diaria(config: dict, env: dict, logger):
    # Injeta o webhook em alertas, para o Notifier avisar no Teams imediatamente
    # a cada falha crítica de impdp, além do resumo final enviado no fim desta função.
    webhook = env.get("teams_webhook_url") or config.get("alertas", {}).get("teams_webhook_url")
    if webhook:
        config.setdefault("alertas", {})["teams_webhook_url"] = webhook

    lock = ExecutionLock(LOCK_PATH)
    if not lock.acquire():
        logger.warning("Execução agendada anterior ainda em andamento (lock recente). Saindo com código 1.")
        sys.exit(1)

    try:
        control = ControlDB(CONTROL_DB_PATH)
        naming = NamingConvention(config["origem"], config["impdp"], config.get("teste", {}))
        origem = BackupSourceClient(config["origem"], naming)

        try:
            origem.connect()
        except Exception as e:
            logger.critical(f"Falha ao conectar no servidor de origem para verificação diária: {e}")
            sys.exit(1)

        sistemas = config["sistemas"]["ativos"]
        a_processar = []
        agora = datetime.now(timezone.utc)

        for sistema in sistemas:
            try:
                ref = _referencia_arquivo(origem, sistema)
            except Exception as e:
                logger.error(f"[{sistema}] Falha ao consultar servidor de origem: {e}")
                continue

            if not ref:
                continue

            estado = control.get_estado(sistema)
            processar, motivo = deve_processar(estado, ref, agora)

            if not processar:
                if motivo == "mtime_desconhecido":
                    logger.warning(f"[{sistema}] Não foi possível obter a data de modificação de {ref['arquivo']} - pulando nesta rodada.")
                elif motivo == "modificado_recentemente":
                    logger.info(
                        f"[{sistema}] Arquivo {ref['arquivo']} modificado há menos de "
                        f"{MIN_IDLE_MINUTES} min - pode ainda estar sendo enviado. Pulando nesta rodada."
                    )
                else:
                    logger.debug(f"[{sistema}] Nenhuma mudança desde o último sucesso. Nada a fazer.")
                continue

            a_processar.append({"sistema": sistema, **ref})

        origem.disconnect()

        if not a_processar:
            logger.info("Verificação diária concluída: nenhuma base nova ou alterada.")
            sys.exit(0)

        logger.info(f"Bases a processar hoje: {[item['sistema'] for item in a_processar]}")
        orchestrator = Orchestrator(config)
        linhas = []
        houve_falha = False

        for item in a_processar:
            sistema = item["sistema"]
            inicio = datetime.now(timezone.utc)
            try:
                resultado = orchestrator.run(sistemas=[sistema])
                status_sistema = resultado.get(sistema, "ERRO_DESCONHECIDO")
                sucesso = "SUCESSO" in status_sistema
            except Exception as e:
                status_sistema = f"EXCECAO: {e}"
                sucesso = False
                logger.exception(f"[{sistema}] Exceção não tratada durante o processamento agendado.")
            fim = datetime.now(timezone.utc)

            control.registrar_execucao(
                base=sistema,
                arquivo=item["arquivo"],
                tamanho_origem=item["tamanho"],
                mtime_origem=item["mtime"],
                inicio=inicio,
                fim=fim,
                status="sucesso" if sucesso else "erro",
                mensagem=status_sistema,
            )

            emoji = "✅" if sucesso else "❌"
            linhas.append(f"{emoji} {sistema} ({item['arquivo']}): {status_sistema}")
            if not sucesso:
                houve_falha = True

        titulo = "Atualização Oracle: " + (
            "atualização com falha" if houve_falha else "bases atualizadas"
        )
        notificar_teams(webhook, titulo, linhas)

        sys.exit(1 if houve_falha else 0)
    finally:
        lock.release()


def main():
    parser = argparse.ArgumentParser(description="Verificação diária agendada das bases corporativas Oracle.")
    parser.add_argument("--seed", action="store_true", help="Mostra o estado atual no servidor de origem (ponto de partida).")
    parser.add_argument("--confirmar", action="store_true", help="Usado com --seed: grava o estado mostrado como ponto de partida.")
    args = parser.parse_args()

    config = load_config(os.path.join(CURRENT_DIR, "config", "config.yaml"))
    env = load_env(os.path.join(CURRENT_DIR, ".env"))
    aplicar_segredos(config, env)

    if args.seed:
        comando_seed(config, confirmar=args.confirmar)
        return

    logs_dir = config.get("local", {}).get("logs_dir", "data/logs")
    logger, _ = setup_logger(logs_dir)
    comando_verificacao_diaria(config, env, logger)


if __name__ == "__main__":
    main()
