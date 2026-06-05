# ── builder ───────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

COPY requirements.txt .
# hadolint ignore=DL3013
RUN pip install --upgrade --no-cache-dir pip \
    && pip install --no-cache-dir --target /app/deps -r requirements.txt

# ── runtime ───────────────────────────────────────────────────────────────────
# hadolint ignore=DL3006
FROM gcr.io/distroless/python3-debian13

WORKDIR /app

COPY --from=builder /app/deps /app/deps
COPY cubs-game-service.py .

ENV PYTHONPATH=/app/deps

# Config is supplied at runtime via --env-file or K8s envFrom (ConfigMap + Secret).
# No config baked into the image.

CMD ["cubs-game-service.py"]
