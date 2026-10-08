"""
Módulo de Notificações e Alertas Operacionais.
Responsável por emitir avisos destacados e acionar auxílio técnico (equipe de DBA)
quando ocorrem falhas relevantes no impdp ou na importação.
"""

import logging
from typing import List, Optional
from colorama import Fore, Style

from .teams_notifier import notificar_teams

logger = logging.getLogger("AtualizacaoOracle")


class Notifier:
    def __init__(self, config: dict):
        self.responsavel = config.get("responsavel", "equipe de DBA")
        self.teams_webhook_url = config.get("teams_webhook_url")

    def alert_critical_error(self, sistema: str, etapa: str, detalhes: List[str], log_path: Optional[str] = None):
        """
        Emite alerta visual (console/log) e avisa no Teams (se o webhook estiver
        configurado) quando ocorre uma falha crítica no impdp/importação.
        """
        msg = f"""
********************************************************************************
{Fore.RED}{Style.BRIGHT}>>> ATENÇÃO: FALHA NA IMPORTAÇÃO DO SISTEMA {sistema} <<<{Style.RESET_ALL}
Etapa: {etapa}
{Fore.YELLOW}{Style.BRIGHT}>>> AVISAR {self.responsavel.upper()} E SOLICITAR AJUDA PARA RESOLVER O PROBLEMA <<<{Style.RESET_ALL}
Detalhes do erro:
"""
        for d in detalhes[:10]:
            msg += f"  - {d}\n"
        if log_path:
            msg += f"\nArquivo de log relevante: {log_path}\n"
        msg += "********************************************************************************"

        logger.error(msg)

        linhas_teams = [f"Etapa: {etapa}"] + [f"- {d}" for d in detalhes[:10]]
        if log_path:
            linhas_teams.append(f"Log: {log_path}")
        notificar_teams(
            self.teams_webhook_url,
            titulo=f"Atualização Oracle: falha no sistema {sistema}",
            linhas=linhas_teams,
        )

    def notify_tolerated_warnings(self, sistema: str, etapa: str, avisos: List[str], log_path: Optional[str] = None):
        """
        Avisa (console/log + Teams) quando o impdp teve erros TOLERADOS (ex:
        ORA-01918/ORA-00942 por schema de origem sem remap_schema) - a importação
        segue como sucesso, mas algum objeto pode ter ficado de fora em silêncio
        (foi o que aconteceu com uma tabela de OUTRO_SCHEMA num dos sistemas). Diferente
        de alert_critical_error: não bloqueia nada, é só visibilidade pra alguém
        revisar e decidir se precisa de um remap_schema novo.
        """
        msg = f"""
--------------------------------------------------------------------------------
{Fore.YELLOW}>>> AVISO: {sistema} teve erro(s) tolerado(s) no impdp (importação seguiu como sucesso) <<<{Style.RESET_ALL}
Etapa: {etapa}
Avisos:
"""
        for a in avisos[:10]:
            msg += f"  - {a}\n"
        if log_path:
            msg += f"\nArquivo de log relevante: {log_path}\n"
        msg += "--------------------------------------------------------------------------------"

        logger.warning(msg)

        linhas_teams = [f"Etapa: {etapa}"] + [f"- {a}" for a in avisos[:10]]
        if log_path:
            linhas_teams.append(f"Log: {log_path}")
        notificar_teams(
            self.teams_webhook_url,
            titulo=f"Atualização Oracle: avisos tolerados no sistema {sistema}",
            linhas=linhas_teams,
        )
