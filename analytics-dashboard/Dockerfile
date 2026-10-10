FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]" "psycopg2-binary" "kafka-python" \
    "duckdb>=1.5.2" "trino" "pyyaml" "prometheus-client" "pyarrow" "httpx" \
    "weasyprint" "matplotlib" "pypdf"

# weasyprint nodig: system fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ducklake-spark connector jar (horizon: Spark-writes naar DuckLake)
RUN mkdir -p /opt/jars && cd /opt/jars && \
    curl -fsSL -o ducklake-spark.jar \
    https://github.com/motherduckdb/ducklake-spark/releases/download/0.1.0-prerelease/ducklake-spark_2.12-0.1.0-SNAPSHOT.jar \
    || echo "WARN: ducklake-spark jar unavailable (fallback: duckdb-native writer)"

WORKDIR /app
COPY contracts/ /app/contracts/
COPY parts/ /app/parts/
COPY init/ /app/init/
COPY captor/ /app/captor/
COPY pipeline/ /app/pipeline/
COPY dashboard/ /app/dashboard/

EXPOSE 8400 8401 8410

CMD ["sleep", "infinity"]
