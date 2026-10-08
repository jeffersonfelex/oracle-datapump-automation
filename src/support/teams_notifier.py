"""
Módulo de Notificação via Teams (Adaptive Card por webhook).
Usa só a biblioteca padrão (urllib) - sem dependência nova. Uma falha de envio
nunca derruba a execução agendada: só é registrada como aviso no log.
"""

import json
import logging
import urllib.error
import urllib.request
from typing import List, Optional

logger = logging.getLogger("AtualizacaoOracle")

TIMEOUT_SECONDS = 30


def notificar_teams(webhook_url: Optional[str], titulo: str, linhas: List[str]) -> None:
    """
    Envia um Adaptive Card para o webhook do Teams com o título e uma linha por
    item de `linhas`. Sem URL configurada, não faz nada (silenciosamente).
    A URL nunca é incluída em nenhuma mensagem de log, mesmo em caso de erro.
    """
    if not webhook_url:
        logger.debug("Notificação Teams não enviada: teams_webhook_url não configurada.")
        return

    corpo_linhas = "\n\n".join(linhas) if linhas else ""
    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": titulo, "weight": "Bolder", "size": "Medium", "wrap": True},
                        {"type": "TextBlock", "text": corpo_linhas, "wrap": True},
                    ],
                },
            }
        ],
    }

    data = json.dumps(card).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            logger.info(f"Notificação enviada ao Teams (status HTTP {resp.status}).")
    except Exception as e:
        # Propositalmente não loga str(e) na íntegra: alguns erros de rede podem
        # ecoar a URL da requisição, e ela contém uma chave de acesso.
        logger.warning(f"Falha ao enviar notificação ao Teams (ignorada): {type(e).__name__}")
