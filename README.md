# cubs-awtrix-mqtt

[![Build and Publish](https://github.com/dewab74/docker.cubs-awtrix-mqtt/actions/workflows/build.yml/badge.svg)](https://github.com/dewab74/docker.cubs-awtrix-mqtt/actions/workflows/build.yml)

Polls the MLB Stats API for Cubs game data and pushes live scorecard updates to an [AWTRIX](https://blueforcer.github.io/awtrix3/) LED matrix display over MQTT.

While a game is in progress it updates every 30 seconds with the current score, inning, ball-strike count, and a bases-state icon. Between games it shows the next scheduled matchup with a countdown. NL Central standings are published to a separate topic every 30 minutes.

## Quick start

```bash
docker run --rm \
  -e MQTT_BROKER_URL=mqtt://your-broker:1883 \
  -e MQTT_USERNAME=homeassistant \
  -e MQTT_PASSWORD=secret \
  ghcr.io/dewab74/docker.cubs-awtrix-mqtt:latest
```

Or with the env file:

```bash
# Copy and edit config.env, then add credentials:
docker run --rm --env-file config.env \
  -e MQTT_USERNAME=homeassistant \
  -e MQTT_PASSWORD=secret \
  ghcr.io/dewab74/docker.cubs-awtrix-mqtt:latest
```

## Kubernetes

```bash
# Create the ConfigMap from config.env (edit values first)
kubectl create configmap cubs-game-config --from-env-file=config.env

# Create the Secret with broker credentials
kubectl create secret generic cubs-game-secret \
  --from-literal=MQTT_USERNAME=homeassistant \
  --from-literal=MQTT_PASSWORD=secret

# Deploy
kubectl apply -f k8s/deployment.yaml
```

Update `k8s/deployment.yaml` with your actual image tag before applying.

## Configuration

All configuration is via environment variables. Non-secret values can go in a ConfigMap; credentials belong in a Secret.

| Variable | Default | Description |
|---|---|---|
| `MQTT_BROKER_URL` | `mqtt://localhost:1883` | Broker URL; may embed credentials (`mqtt://user:pass@host:port`) |
| `MQTT_USERNAME` | — | Broker username (overrides URL credentials) |
| `MQTT_PASSWORD` | — | Broker password |
| `AWTRIX_DEVICE` | `awtrix` | Device name; used as topic prefix when topic vars are left at defaults |
| `MQTT_TOPIC` | `{AWTRIX_DEVICE}/custom/cubs_game_next` | Topic for game updates |
| `MQTT_STANDINGS_TOPIC` | `{AWTRIX_DEVICE}/custom/cubs_standings` | Topic for standings updates |
| `MQTT_ICON` | `40217` | AWTRIX icon ID (default game) |
| `MQTT_WIN_ICON` | `74405` | AWTRIX icon ID (Cubs win) |
| `MQTT_DURATION` | `5` | Display duration in seconds (non-live) |
| `MQTT_DURATION_LIVE` | `7` | Display duration in seconds (live game) |
| `MQTT_SCROLL` | `true` | Scroll long text |
| `MQTT_COLOR` | `#002C5F` | Default text color |
| `MQTT_RETAIN` | `false` | MQTT retain flag |
| `POLL_NO_GAMES` | `14400` | Poll interval (s) when no games are scheduled |
| `POLL_UPCOMING` | `900` | Poll interval (s) for a future game |
| `POLL_TODAY` | `300` | Poll interval (s) for a game today, not yet started |
| `POLL_LIVE` | `30` | Poll interval (s) during a live game |
| `POLL_FINAL` | `300` | Poll interval (s) after a game ends |

## Building locally

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t cubs-awtrix-mqtt .
```
