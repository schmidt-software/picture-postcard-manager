FROM python:3.13-slim

WORKDIR /srv/app
COPY app ./app

ENV PPM_HOST=0.0.0.0 \
    PPM_PORT=8000 \
    PPM_DB_PATH=/data/postcards.db \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "-m", "app"]
