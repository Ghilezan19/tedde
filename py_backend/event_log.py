"""
Loguri explicite pentru terminal — ESP / buton / etape înregistrare.

Folosește logger-ul `tedde` ca să apară clar în consolă lângă liniile Uvicorn.
"""

import logging

_log = logging.getLogger("tedde")


def banner(title: str) -> None:
    """Linie dublă, ușor de scanat vizual."""
    line = "=" * 62
    _log.info(line)
    _log.info("  %s", title)
    _log.info(line)


def step(msg: str) -> None:
    """O etapă din workflow."""
    _log.info("  >> %s", msg)


def warn(msg: str) -> None:
    _log.warning("  !! %s", msg)
