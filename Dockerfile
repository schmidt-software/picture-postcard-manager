FROM python:3.13-slim

WORKDIR /srv/app

# Optional dependencies (Pillow for overview thumbnails). The image installs
# them by default because a Docker deployment serves multiple clients, where
# thumbnail bandwidth savings matter most; build with
# --build-arg INSTALL_OPTIONAL=false for a standard-library-only image.
ARG INSTALL_OPTIONAL=true
COPY requirements-optional.txt ./
RUN if [ "$INSTALL_OPTIONAL" = "true" ]; then \
      pip install --no-cache-dir -r requirements-optional.txt; \
    fi

COPY app ./app

ENV PPM_HOST=0.0.0.0 \
    PPM_PORT=8000 \
    PPM_DB_PATH=/data/postcards.db \
    PPM_IMAGE_DIR=/data/images \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "-m", "app"]
