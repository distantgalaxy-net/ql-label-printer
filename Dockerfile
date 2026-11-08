# ------------------------------------------------------------------
# labelprinter - label print service image
# Date: 2026-11-08 16:01 GMT (updated; first written 2026-11-07 18:30 GMT)
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
# Built by Container Manager from this folder (see docker-compose.yml).
# ------------------------------------------------------------------
FROM python:3.12-slim

# Fonts used on the labels (DejaVu Sans, Condensed and Mono), plus
# tzdata: the time zone database behind the Settings tab's time zone list
# (it knows every country's daylight saving dates)
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-dejavu-extra tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/

# Settings, presets, custom icons and the optional password hash live in
# /data (mounted from the host so they survive updates)
ENV DATA_DIR=/data ICON_DIR=/data/icons PORT=8013 PYTHONUNBUFFERED=1
EXPOSE 8013

# Container Manager shows "healthy" once the web page answers
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8013/health', timeout=4)" || exit 1

CMD ["python", "main.py"]
