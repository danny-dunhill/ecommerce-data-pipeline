# Airflow image that can also run the pipeline.
#
# The pipeline gets its own virtualenv. Airflow pins many libraries (SQLAlchemy, ...), and
# installing the pipeline next to them could change those pins and break Airflow. The DAG
# calls the `pipeline` command of this virtualenv, so the two never share a Python environment.
#
# Build context: the project root (see docker-compose.yml).
FROM apache/airflow:3.3.2-python3.12

COPY --chown=airflow:root pyproject.toml README.md /tmp/pipeline-src/
COPY --chown=airflow:root src /tmp/pipeline-src/src

RUN mkdir -p /opt/airflow/logs \
    && python -m venv /opt/airflow/pipeline-venv \
    && /opt/airflow/pipeline-venv/bin/pip install --no-cache-dir /tmp/pipeline-src \
    && rm -rf /tmp/pipeline-src
