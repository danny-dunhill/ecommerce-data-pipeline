"""Central logging configuration (the pipeline never uses ``print``)."""

import logging

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once for the whole application.

    ``force=True`` replaces any previously installed handlers, so calling this
    twice (for example from tests) never duplicates log lines.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
        force=True,
    )
