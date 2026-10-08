"""
Módulo do Banco de Controle da Execução Agendada.
Guarda, por sistema, o último arquivo de origem processado com sucesso
(tamanho e data de modificação) e o histórico de cada execução. Usa SQLite
(biblioteca padrão) em vez de um schema novo no Oracle: não depende de
privilégio de criação de usuário/schema no banco de destino, e continua
disponível mesmo se o Oracle estiver fora do ar na hora de só consultar o
estado. Fica separado de qualquer schema recarregado pela automação, então
o histórico nunca é apagado por um import com table_exists_action=replace.
"""

import os
import sqlite3
import logging
from contextlib import closing
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("AtualizacaoOracle")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_estado (
    base            TEXT PRIMARY KEY,
    arquivo         TEXT,
    tamanho_origem  INTEGER,
    mtime_origem    TEXT,
    processado_em   TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_execucoes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    base            TEXT NOT NULL,
    arquivo         TEXT,
    tamanho_origem  INTEGER,
    mtime_origem    TEXT,
    inicio          TEXT,
    fim             TEXT,
    status          TEXT NOT NULL CHECK (status IN ('sucesso', 'erro')),
    mensagem        TEXT
);
"""


class ControlDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def get_estado(self, base: str) -> Optional[Dict]:
        """Retorna o último estado de sucesso registrado para a base, ou None."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT base, arquivo, tamanho_origem, mtime_origem, processado_em "
                "FROM pipeline_estado WHERE base = ?",
                (base,),
            ).fetchone()
            return dict(row) if row else None

    def listar_estados(self) -> Dict[str, Dict]:
        """Retorna todos os estados conhecidos, indexados por base."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT base, arquivo, tamanho_origem, mtime_origem, processado_em FROM pipeline_estado"
            ).fetchall()
            return {row["base"]: dict(row) for row in rows}

    def registrar_execucao(
        self,
        base: str,
        arquivo: Optional[str],
        tamanho_origem: Optional[int],
        mtime_origem: Optional[datetime],
        inicio: datetime,
        fim: datetime,
        status: str,
        mensagem: str,
    ):
        """
        Registra uma execução em pipeline_execucoes e, se status == "sucesso",
        atualiza pipeline_estado - tudo na mesma transação, para o log e o
        estado nunca ficarem dessincronizados (ex: processo morrer entre os dois
        inserts). O estado só avança em caso de sucesso, de propósito: uma falha
        não "esquece" a mudança pendente, então a base é tentada de novo na
        próxima rodada com os mesmos dados de origem.
        """
        if status not in ("sucesso", "erro"):
            raise ValueError(f"status inválido: {status!r} (esperado 'sucesso' ou 'erro')")

        mtime_str = mtime_origem.isoformat() if mtime_origem else None
        inicio_str = inicio.isoformat()
        fim_str = fim.isoformat()

        with closing(self._connect()) as conn:
            with conn:  # commit/rollback automático ao sair do bloco
                conn.execute(
                    "INSERT INTO pipeline_execucoes "
                    "(base, arquivo, tamanho_origem, mtime_origem, inicio, fim, status, mensagem) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (base, arquivo, tamanho_origem, mtime_str, inicio_str, fim_str, status, mensagem),
                )
                if status == "sucesso":
                    conn.execute(
                        "INSERT INTO pipeline_estado (base, arquivo, tamanho_origem, mtime_origem, processado_em) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(base) DO UPDATE SET "
                        "arquivo=excluded.arquivo, tamanho_origem=excluded.tamanho_origem, "
                        "mtime_origem=excluded.mtime_origem, processado_em=excluded.processado_em",
                        (base, arquivo, tamanho_origem, mtime_str, fim_str),
                    )

    def listar_execucoes(self, base: Optional[str] = None, limite: int = 50) -> List[Dict]:
        """Histórico de execuções, mais recente primeiro (útil para diagnóstico)."""
        with closing(self._connect()) as conn:
            if base:
                rows = conn.execute(
                    "SELECT * FROM pipeline_execucoes WHERE base = ? ORDER BY id DESC LIMIT ?",
                    (base, limite),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pipeline_execucoes ORDER BY id DESC LIMIT ?", (limite,)
                ).fetchall()
            return [dict(row) for row in rows]
