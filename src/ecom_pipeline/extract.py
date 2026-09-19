"""Locate and validate the raw CSV files before anything touches the database.

Checking everything up front means a wrong folder or an unexpected file version fails
in a second with a clear message, instead of half way through a load.
"""

import csv
from collections.abc import Sequence
from pathlib import Path

from ecom_pipeline.tables import TABLES, TableSpec


class ExtractError(RuntimeError):
    """Raised when source files are missing or do not have the expected columns."""


def read_header(path: Path) -> list[str]:
    """Return the column names from the first line of a CSV file.

    The ``utf-8-sig`` encoding silently drops the invisible byte-order mark that some
    exports put at the very start of a file.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle), [])


def count_records(path: Path) -> int:
    """Count the data records of a CSV file (the header is not counted).

    A quoted field that contains line breaks still counts as a single record, which is
    why this uses the ``csv`` module and not a simple line count.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)  # skip the header
        return sum(1 for _ in reader)


def validate_sources(data_dir: Path, tables: Sequence[TableSpec] = TABLES) -> dict[str, Path]:
    """Check that every expected CSV file exists and has the expected header.

    Returns:
        Mapping of staging table name to the path of its CSV file.

    Raises:
        ExtractError: listing *all* problems that were found, not just the first one.
    """
    sources: dict[str, Path] = {}
    problems: list[str] = []

    for spec in tables:
        path = data_dir / spec.csv_file
        if not path.is_file():
            problems.append(f"{spec.name}: file not found: {path}")
            continue
        try:
            header = read_header(path)
        except UnicodeDecodeError:
            problems.append(f"{spec.name}: {path.name} is not a valid UTF-8 text file")
            continue
        if header != list(spec.columns):
            problems.append(
                f"{spec.name}: unexpected columns in {path.name}\n"
                f"      expected: {list(spec.columns)}\n"
                f"      found:    {header}"
            )
            continue
        sources[spec.name] = path

    if problems:
        raise ExtractError("Problems with the source data:\n  - " + "\n  - ".join(problems))
    return sources
