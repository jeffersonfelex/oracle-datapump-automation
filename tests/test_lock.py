"""Testes do lock de execucao com renovacao (src/core/lock.py)."""

import os
import time

from src.core.lock import ExecutionLock


def test_primeiro_acquire_funciona(tmp_path):
    lock = ExecutionLock(os.path.join(tmp_path, "sub", "agendado.lock"))
    assert lock.acquire() is True
    assert os.path.exists(lock.lock_path)
    lock.release()
    assert not os.path.exists(lock.lock_path)


def test_segundo_acquire_recusado_enquanto_lock_recente(tmp_path):
    lock_path = os.path.join(tmp_path, "agendado.lock")
    lock1 = ExecutionLock(lock_path, stale_after_seconds=3600)
    lock2 = ExecutionLock(lock_path, stale_after_seconds=3600)

    assert lock1.acquire() is True
    assert lock2.acquire() is False  # execucao anterior ainda "viva"

    lock1.release()


def test_lock_e_renovado_periodicamente(tmp_path):
    lock_path = os.path.join(tmp_path, "agendado.lock")
    lock = ExecutionLock(lock_path, renew_interval_seconds=1)
    lock.acquire()

    mtime_inicial = os.path.getmtime(lock_path)
    time.sleep(2.5)  # espera pelo menos uma renovacao (intervalo de 1s)
    mtime_depois = os.path.getmtime(lock_path)

    lock.release()
    assert mtime_depois > mtime_inicial


def test_lock_velho_e_considerado_abandonado(tmp_path):
    lock_path = os.path.join(tmp_path, "agendado.lock")
    os.makedirs(tmp_path, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as f:
        f.write("12345")

    # Forca o lock a parecer antigo (criado ha mais tempo que o limite de "velho").
    antigo = time.time() - 7200
    os.utime(lock_path, (antigo, antigo))

    lock = ExecutionLock(lock_path, stale_after_seconds=3600)
    # Mesmo com um arquivo de lock presente, por estar "velho" (crash anterior),
    # uma nova execucao longa nao deve ser bloqueada por ele.
    assert lock.acquire() is True
    lock.release()
