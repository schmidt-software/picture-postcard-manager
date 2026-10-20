#!/bin/sh
# Launcher for Picture Postcard Manager on macOS and Linux (Refs #67).
#
# Runs the documented `docker run` command for the published container image
# with the persistent `postcard-data` volume mounted at /data, waits until
# the application's health endpoint answers, and then opens the browser.
# Running it again reuses the existing container and volume; no data is
# ever deleted.
#
# A Docker named volume is used instead of a host bind mount on purpose:
# SQLite databases newly created on Docker Desktop (macOS) bind mounts can
# fail on the first write (see the README). The volume persists on the host
# across container stops, removals and image updates.
#
# Configuration (environment variables, all optional):
#   PPM_PORT          Host port to publish on 127.0.0.1 (default: 8000)
#   PPM_IMAGE_TAG     Image tag to run (default: latest)
#   PPM_WAIT_SECONDS  Health-endpoint timeout in seconds (default: 90)

set -eu

CONTAINER="picture-postcard-manager"
VOLUME="postcard-data"
IMAGE="ghcr.io/schmidt-software/picture-postcard-manager:${PPM_IMAGE_TAG:-latest}"
PORT="${PPM_PORT:-8000}"
WAIT_SECONDS="${PPM_WAIT_SECONDS:-90}"
URL="http://127.0.0.1:$PORT"

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 \
    || fail "Docker is not installed or not on PATH. Install Docker and try again."
docker info >/dev/null 2>&1 \
    || fail "the Docker daemon is not running. Start Docker and try again."

# The data volume holds the SQLite database (/data/postcards.db) and the
# uploaded images (/data/images/). Creating it explicitly makes reruns
# obviously safe: an existing volume and its contents are never touched.
docker volume create "$VOLUME" >/dev/null \
    || fail "cannot create the Docker volume: $VOLUME"

state=$(docker container inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || printf 'missing')
case $state in
true)
    printf 'Container %s is already running; reusing it.\n' "$CONTAINER"
    ;;
false)
    printf 'Starting the existing container %s (all data is kept).\n' "$CONTAINER"
    docker start "$CONTAINER" >/dev/null \
        || fail "could not start the existing container. Check: docker logs $CONTAINER"
    ;;
*)
    printf 'Creating container %s from %s.\n' "$CONTAINER" "$IMAGE"
    docker run -d --name "$CONTAINER" \
        -p "127.0.0.1:$PORT:8000" \
        -v "$VOLUME:/data" \
        "$IMAGE" >/dev/null \
        || fail "docker run failed; see the Docker message above."
    ;;
esac

# Probe the application's health endpoint from the host. Prefer curl, fall
# back to wget and then to Python so stock macOS and minimal Linux both work.
probe_health() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsS --max-time 2 "$URL/api/health" >/dev/null 2>&1
    elif command -v wget >/dev/null 2>&1; then
        wget -q -T 2 -O /dev/null "$URL/api/health" 2>/dev/null
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import urllib.request; urllib.request.urlopen('$URL/api/health', timeout=2).close()" >/dev/null 2>&1
    else
        fail "none of curl, wget or python3 is available to check $URL/api/health"
    fi
}

printf 'Waiting up to %s seconds for %s/api/health ...\n' "$WAIT_SECONDS" "$URL"
elapsed=0
until probe_health; do
    running=$(docker container inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || printf 'false')
    [ "$running" = "true" ] \
        || fail "the container stopped unexpectedly. Check: docker logs $CONTAINER"
    [ "$elapsed" -lt "$WAIT_SECONDS" ] \
        || fail "the application did not become healthy within $WAIT_SECONDS seconds.
If you changed PPM_PORT after the container was created, the old container
still publishes the old port. Stop and remove the container (the data volume
is kept), then run this script again. Check: docker logs $CONTAINER"
    sleep 1
    elapsed=$((elapsed + 1))
done

printf 'The application is ready: %s\n' "$URL"
case $(uname -s) in
Darwin)
    open "$URL"
    ;;
*)
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 &
    else
        printf 'Open %s in your browser.\n' "$URL"
    fi
    ;;
esac
