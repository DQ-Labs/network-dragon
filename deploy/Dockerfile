# Supply digest-pinned base images for a deployment release.
ARG NODE_IMAGE=node:24-bookworm-slim
ARG PYTHON_IMAGE=python:3.14-slim-bookworm
FROM ${NODE_IMAGE} AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS build
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.1
COPY pyproject.toml uv.lock ./
COPY backend/ backend/
RUN uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python

FROM ${PYTHON_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends nmap iproute2 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 dragon && useradd -u 10001 -g dragon -M dragon \
    && mkdir /data && chown dragon:dragon /data
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=frontend /build/dist /app/frontend/dist
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["network-dragon"]
CMD ["web", "--host", "0.0.0.0"]
