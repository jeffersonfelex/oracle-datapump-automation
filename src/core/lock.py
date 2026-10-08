"""Lock de execução renovado por heartbeat; sem renovação, é considerado abandonado."""

import os
import time
import logging
import threading

logger = logging.getLogger("AtualizacaoOracle")


class ExecutionLock:
    def __init__(self, lock_path: str, stale_after_seconds: int = 3600, renew_interval_seconds: int = 60):
        self.lock_path = lock_path
        self.stale_after_seconds = stale_after_seconds
        self.renew_interval_seconds = renew_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread = None

    def acquire(self) -> bool:
        """Obtém o lock; False se outra execução estiver em andamento."""
        if os.path.exists(self.lock_path):
            age = time.time() - os.path.getmtime(self.lock_path)
            if age < self.stale_after_seconds:
                logger.warning(
                    f"Lock de execução recente encontrado ({age:.0f}s atrás, "
                    f"limite {self.stale_after_seconds}s) - outra execução parece estar em andamento."
                )
                return False
            logger.warning(
                f"Lock de execução encontrado mas sem renovação há {age:.0f}s "
                f"(> {self.stale_after_seconds}s) - considerado abandonado de uma execução anterior. Assumindo."
            )

        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        with open(self.lock_path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        return True

    def _heartbeat_loop(self):
        while not self._stop_event.wait(self.renew_interval_seconds):
            try:
                os.utime(self.lock_path, None)
            except Exception as e:
                logger.warning(f"Falha ao renovar lock de execução: {e}")

    def release(self):
        """Para a renovação e remove o arquivo de lock."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Falha ao remover lock de execução: {e}")
