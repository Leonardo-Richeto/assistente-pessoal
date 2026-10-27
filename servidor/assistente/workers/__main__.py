"""Agendador dos workers: roda o Pluggy na subida e depois às 00, 06, 12 e 18 h (Ficha 10, regra 10).

Laço simples em vez de APScheduler: um horário fixo por worker não pede uma dependência a mais. Falha numa rodada
fica anotada em `sincronizacoes` e no log; o laço segue para o próximo horário.
"""

import logging
import time
from datetime import datetime, timedelta

from ..db import Bancos
from .pluggy import ClientePluggy, ConfigPluggy, ErroPluggy, sincronizar

log = logging.getLogger("assistente.workers")

HORAS = (0, 6, 12, 18)


def proximo_horario(agora: datetime, horas: tuple[int, ...] = HORAS) -> datetime:
    """O próximo horário cheio da lista, estritamente depois de `agora` (mesmo fuso de `agora`)."""
    dia = agora.replace(minute=0, second=0, microsecond=0)
    for extra in (0, 1):
        for h in sorted(horas):
            candidato = (dia + timedelta(days=extra)).replace(hour=h)
            if candidato > agora:
                return candidato
    raise AssertionError("inalcançável")


def rodar_uma_vez(bancos: Bancos, cfg: ConfigPluggy) -> None:
    cliente = ClientePluggy(cfg.pluggy_client_id, cfg.pluggy_client_secret, cfg.pluggy_url)
    try:
        sincronizar(bancos, cliente, cfg)
    except ErroPluggy as e:
        log.error("pluggy: %s", e)
    except Exception as e:  # sem traceback: os parâmetros do SQL levariam descrição e valor do gasto para o log
        log.error("pluggy: falha inesperada (%s)", type(e).__name__)
    finally:
        cliente.fechar()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)  # o INFO dele loga a URL, com id de item e de conta
    cfg = ConfigPluggy()
    if not cfg.database_url_escrita:
        raise SystemExit("workers: falta DATABASE_URL_ESCRITA")
    bancos = Bancos.de_urls(cfg.database_url_escrita, cfg.database_url_escrita)
    log.info("workers: pluggy às %s h", ", ".join(f"{h:02d}" for h in HORAS))
    rodar_uma_vez(bancos, cfg)
    while True:
        alvo = proximo_horario(datetime.now(cfg.tz))
        log.info("workers: próxima rodada em %s", alvo.isoformat(timespec="minutes"))
        while (falta := (alvo - datetime.now(cfg.tz)).total_seconds()) > 0:
            time.sleep(min(falta, 300))  # acorda a cada 5 min: relógio ajustado ou máquina suspensa não atrasam muito
        rodar_uma_vez(bancos, cfg)


if __name__ == "__main__":
    main()
