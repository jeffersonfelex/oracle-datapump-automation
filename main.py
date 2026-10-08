"""
Ponto de Entrada Principal (CLI) da Automação das Bases Oracle.

Uso:
  # Executar simulação para um sistema específico:
  py main.py --sistema VENDAS --dry-run

  # Executar em produção para o sistema VENDAS:
  py main.py --sistema VENDAS

  # Executar para todos os sistemas corporativos:
  py main.py --all

  # Executar aproveitando dumps já baixados no disco local:
  py main.py --sistema VENDAS --skip-origem

Este arquivo é intencionalmente enxuto: apenas conecta os módulos em src/
(carregamento de config, CLI/menu interativo, logger e orquestrador).
Toda a lógica de negócio vive em src/core/, src/clients/ e src/support/.
"""

import os
import sys

# Adiciona o diretório atual ao sys.path para importação dos módulos
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from src.cli import parse_args
from src.config_loader import aplicar_segredos, load_config, load_env
from src.support.logger import setup_logger
from src.core.orchestrator import Orchestrator


def main():
    args = parse_args(CURRENT_DIR)

    # Carrega configurações
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"ERRO FATAL ao carregar configuração: {e}")
        sys.exit(1)

    # Senhas e webhook vêm do .env (ou de variáveis de ambiente), nunca do config.yaml.
    # O webhook também é usado no fluxo manual, para avisar no Teams em falhas críticas.
    aplicar_segredos(config, load_env(os.path.join(CURRENT_DIR, ".env")))

    # Inicializa Logger
    logs_dir = config.get("local", {}).get("logs_dir", "data/logs")
    logger, log_file = setup_logger(logs_dir)

    # Identifica lista de sistemas alvo
    if args.all:
        target_sistemas = config["sistemas"]["ativos"]
    else:
        target_sistemas = [args.sistema.upper()]

    # Instancia o orquestrador e inicia a execução
    orchestrator = Orchestrator(config)
    results = orchestrator.run(
        sistemas=target_sistemas,
        dry_run=args.dry_run,
        skip_origem=args.skip_origem,
        periodo_override=args.periodo,
        from_sistema=args.from_sistema,
        teste=args.teste
    )

    # Se algum sistema falhou, encerra com exit code 1
    has_failure = any("SUCESSO" not in status for status in results.values())
    sys.exit(1 if has_failure else 0)


if __name__ == "__main__":
    main()
