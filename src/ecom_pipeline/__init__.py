"""E-commerce data pipeline: raw CSV -> PostgreSQL star schema."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ecom-pipeline")
except PackageNotFoundError:  # running from a source checkout that is not installed
    __version__ = "0.0.0+unknown"
