# syntax=docker/dockerfile:1
#
# IntelliSource composite DB image — pgvector/pgvector:pg16 base + SCWS + zhparser
#
# Layered onto pgvector to get both vector similarity search and Chinese FTS in a
# single PostgreSQL 16 instance. Alembic migration 001 then promotes
# `CREATE EXTENSION zhparser` to a hard requirement and creates a `zhparser`
# text-search configuration consumed by storage/vector.py.
#
# Build:    docker build -t intellisource/db:pg16-pgvector-zhparser -f docker/db.Dockerfile .
# Compose:  docker-compose.yml `db` service builds this image automatically.
# Reference: https://github.com/abcfy2/docker_zhparser (SCWS+zhparser build recipe).

FROM pgvector/pgvector:pg16

ARG SCWS_VERSION=1.2.3
ARG ZHPARSER_REPO=https://github.com/amutu/zhparser.git
ARG ZHPARSER_REF=master

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        postgresql-server-dev-16 \
        ca-certificates \
        wget \
        git; \
    \
    cd /tmp; \
    wget -q "http://www.xunsearch.com/scws/down/scws-${SCWS_VERSION}.tar.bz2"; \
    tar -xjf "scws-${SCWS_VERSION}.tar.bz2"; \
    cd "scws-${SCWS_VERSION}"; \
    ./configure --prefix=/usr/local; \
    make -j"$(nproc)"; \
    make install; \
    \
    cd /tmp; \
    git clone --depth=1 --branch "${ZHPARSER_REF}" "${ZHPARSER_REPO}" zhparser; \
    cd zhparser; \
    SCWS_HOME=/usr/local make -j"$(nproc)"; \
    SCWS_HOME=/usr/local make install; \
    \
    apt-get remove -y --purge build-essential postgresql-server-dev-16 wget git; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/* /tmp/scws-* /tmp/zhparser; \
    ldconfig
