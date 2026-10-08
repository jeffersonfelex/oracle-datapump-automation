"""Execução manual da automação (linha de comando ou menu interativo)."""

import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from src.cli import parse_args
from src.config_loader import aplicar_segredos, load_config, load_env
from src.support.logger import setup_logger
from src.core.orchestrator import Orchestrator


def main():
    args = parse_args(CURRENT_DIR)

    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"ERRO FATAL ao carregar configuração: {e}")
        sys.exit(1)

    aplicar_segredos(config, load_env(os.path.join(CURRENT_DIR, ".env")))

    logs_dir = config.get("local", {}).get("logs_dir", "data/logs")
    logger, log_file = setup_logger(logs_dir)

    if args.all:
        target_sistemas = config["sistemas"]["ativos"]
    else:
        target_sistemas = [args.sistema.upper()]

    orchestrator = Orchestrator(config)
    results = orchestrator.run(
        sistemas=target_sistemas,
        dry_run=args.dry_run,
        skip_origem=args.skip_origem,
        periodo_override=args.periodo,
        from_sistema=args.from_sistema,
        teste=args.teste
    )

    has_failure = any("SUCESSO" not in status for status in results.values())
    sys.exit(1 if has_failure else 0)


if __name__ == "__main__":
    main()
