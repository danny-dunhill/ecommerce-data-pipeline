FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the package (dependencies + the `pipeline` command)
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Do not run as root inside the container
RUN useradd --create-home appuser
USER appuser

ENTRYPOINT ["pipeline"]
CMD ["--help"]
