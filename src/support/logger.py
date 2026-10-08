"""Logger com saída colorida no console e gravação em arquivo."""

import os
import sys
import logging
from datetime import datetime
from colorama import init, Fore, Style

init(autoreset=True)


class ColoredFormatter(logging.Formatter):
    """Formatador customizado com cores ANSI para o console."""

    COLORS = {
        logging.DEBUG: Style.DIM + Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED + Style.BRIGHT,
        logging.CRITICAL: Fore.WHITE + Style.BRIGHT,
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        reset = Style.RESET_ALL
        time_str = self.formatTime(record, "%H:%M:%S")
        level_str = f"[{record.levelname:<8}]"
        return f"{time_str} {color}{level_str}{reset} {record.getMessage()}"


def setup_logger(logs_dir: str, log_level: int = logging.INFO) -> tuple[logging.Logger, str]:
    """Configura o logger da aplicação e devolve (logger, caminho do arquivo de log)."""
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(logs_dir, f"atualizacao_{timestamp}.log")

    logger = logging.getLogger("AtualizacaoOracle")
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers():
        logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)

    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%H:%M:%S"
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    logger.info(f"Log salvo em: {log_file}")
    return logger, log_file
