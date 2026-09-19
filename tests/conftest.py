"""Shared pytest configuration."""

from dotenv import find_dotenv, load_dotenv

# Make the values from a local `.env` file visible to the tests, so the integration tests
# can find the database after `make up`. Real environment variables always win.
load_dotenv(find_dotenv(usecwd=True))
