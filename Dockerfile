FROM python:3.13-slim

# Fixed UID/GID for the unprivileged application user. 1000:1000 matches the
# default first user on most Linux hosts, which keeps bind-mounted data
# directories readable there; override at build time (e.g.
# --build-arg PPM_UID="$(id -u)" --build-arg PPM_GID="$(id -g)") when a bind
# mount is owned by a different host account.
ARG PPM_UID=1000
ARG PPM_GID=1000
RUN groupadd --gid "$PPM_GID" ppm \
    && useradd --uid "$PPM_UID" --gid "$PPM_GID" \
         --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin ppm \
    && mkdir -p /data \
    && chown "$PPM_UID:$PPM_GID" /data

WORKDIR /srv/app

# Optional dependencies (Pillow for overview thumbnails). The image installs
# them by default because a Docker deployment serves multiple clients, where
# thumbnail bandwidth savings matter most; build with
# --build-arg INSTALL_OPTIONAL=false for a standard-library-only image.
ARG INSTALL_OPTIONAL=true
COPY requirements-optional.txt ./
RUN chmod a+r requirements-optional.txt \
    && if [ "$INSTALL_OPTIONAL" = "true" ]; then \
      pip install --no-cache-dir -r requirements-optional.txt; \
    fi

# Application code stays owned by root (read-only for the app user); only
# world-read permissions are normalized, because COPY preserves host modes
# and a restrictive umask on the build host would otherwise hide the code.
COPY app ./app
RUN chmod -R a+rX /srv/app

ENV PPM_HOST=0.0.0.0 \
    PPM_PORT=8000 \
    PPM_DB_PATH=/data/postcards.db \
    PPM_IMAGE_DIR=/data/images \
    PYTHONUNBUFFERED=1

# Run unprivileged. /data is owned by ppm above, so a fresh named volume
# (initialized from the image) is writable; see the README for migrating
# existing root-owned volumes and bind mounts.
USER ppm

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "-m", "app"]
