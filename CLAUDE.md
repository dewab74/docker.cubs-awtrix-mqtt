# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python service that polls the MLB Stats API for Cubs game data and publishes formatted live scorecard updates to an [AWTRIX](https://blueforcer.github.io/awtrix3/) LED matrix display via MQTT. It runs as a Kubernetes Deployment with no inbound ports — pure publisher.

## Running locally

```bash
pip install -r requirements.txt
# Supply env vars (see config.env for full list; MQTT_USERNAME/MQTT_PASSWORD are secrets)
MQTT_BROKER_URL=mqtt://localhost:1883 python cubs-game-service.py
```

Run against a specific env file:
```bash
env $(grep -v '^#' config.env | xargs) python cubs-game-service.py
```

## Linting

```bash
ruff check cubs-game-service.py          # lint
ruff check --fix cubs-game-service.py    # lint + auto-fix
ruff format cubs-game-service.py         # format
hadolint Dockerfile                      # Dockerfile lint
pre-commit run --all-files               # run all hooks at once
```

Pre-commit hooks (ruff + hadolint) run automatically on `git commit`. Install once with `pre-commit install`. Line length is 120.

## CI / CD

`.github/workflows/build.yml` runs on every push to `main` and on PRs:
- **build** job: builds a multi-arch image (`linux/amd64` + `linux/arm64`) via QEMU/Buildx, pushes to `ghcr.io/dewab74/docker.cubs-awtrix-mqtt` with `latest` and `sha-<sha>` tags (push only on `main`)
- **scan** job: runs Trivy against the freshly pushed `latest` image, uploads CRITICAL/HIGH findings as SARIF to the GitHub Security tab

No secrets need to be configured — the workflow uses `GITHUB_TOKEN` for GHCR auth.

## Building and deploying

```bash
# Build image
docker build -t your-registry/cubs-game-service:latest .

# Apply K8s manifests (edit configmap.yaml and secret.yaml with real values first)
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/deployment.yaml
```

Bootstrap the ConfigMap from `config.env` directly:
```bash
kubectl create configmap cubs-game-config --from-env-file=config.env
```

## Architecture

All logic lives in `cubs-game-service.py`. The main loop in `run_service()` calls `fetch_game_state()` each iteration, pattern-matches on a state string, builds colored text segments, and calls `publish_mqtt()`.

**State machine** (`fetch_game_state` returns one of):
- `NO_GAMES` — off-season, polls every 4 h
- `UPCOMING` — next game is a future date, polls every 15 min
- `TODAY_SCHEDULED` — game today but not yet started, polls every 5 min
- `LIVE` — game in progress, polls every 30 s
- `FINAL` — game ended today, polls every 5 min
- `POSTPONED` — falls back to showing next scheduled game
- `ERROR` — API failure, backs off 60 s

**MQTT payload format** — AWTRIX `custom` app schema:
```json
{ "icon": "<id>", "text": [{"t": "CHC", "c": "#0E3386"}, ...], "duration": 5, "scroll": true, "color": "#002C5F" }
```
Text is a list of `{"t": string, "c": hex}` segments so each team name renders in its team color.

**Live game extras** — `fetch_live_details()` makes a second API call to `statsapi.get("game", ...)` to get bases state (bit-packed into a mask → icon lookup) and ball-strike count, displayed alongside the score.

**Standings** — published to a separate MQTT topic (`MQTT_STANDINGS_TOPIC`) at most every 30 min when a game state is active.

## Configuration

All config is via environment variables. Non-secret values are in `config.env` / `k8s/configmap.yaml`. Secrets (`MQTT_USERNAME`, `MQTT_PASSWORD`) go in `k8s/secret.yaml`. The MQTT broker URL can embed credentials: `mqtt://user:pass@host:port`.

Key vars: `AWTRIX_DEVICE` (device name prefix for default topics), `MQTT_BROKER_URL`, `MQTT_ICON` / `MQTT_WIN_ICON` (AWTRIX icon IDs), `POLL_LIVE` (seconds between updates during a live game).
