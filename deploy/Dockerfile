# Supply digest-pinned base images for a deployment release.
ARG NODE_IMAGE=node:24-bookworm-slim
ARG PYTHON_IMAGE=python:3.14-slim-bookworm
# The frontend bundle is architecture-independent; build it natively, not under QEMU.
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS frontend
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
# Nmap is the only program that receives a capability: CAP_NET_RAW as a file
# capability, effective only when the container's bounding set also holds it
# (worker: cap_add NET_RAW). The worker therefore runs without
# no-new-privileges, so every setuid/setgid bit is stripped from the image.
# libcap2-bin stays: iproute2 depends on it, and setcap is inert without
# CAP_SETFCAP, which neither service holds.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nmap iproute2 ca-certificates libcap2-bin \
    && setcap cap_net_raw+ep /usr/bin/nmap \
    && rm -rf /var/lib/apt/lists/* \
    && find / -xdev -type f -perm /6000 -exec chmod a-s {} + \
    && groupadd -g 10001 dragon && useradd -u 10001 -g dragon -M dragon \
    && mkdir /data && chown dragon:dragon /data
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=frontend /build/dist /app/frontend/dist
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["network-dragon"]
CMD ["web", "--host", "127.0.0.1"]
