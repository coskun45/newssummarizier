# PostgreSQL + pgvector (Asistan's vector search). Built on the same postgres:16-alpine image the DB
# always ran on, so the existing data volume keeps its musl collation: switching to the Debian-based
# pgvector/pgvector image would change it under the existing text indexes.
FROM postgres:16-alpine

ARG PGVECTOR_VERSION=v0.8.0

RUN apk add --no-cache --virtual .pgvector-build git build-base \
    && git clone --branch "${PGVECTOR_VERSION}" --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && make OPTFLAGS="" with_llvm=no \
    && make install with_llvm=no \
    && cd / && rm -rf /tmp/pgvector \
    && apk del .pgvector-build
