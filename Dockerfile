FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl supervisor \
    && apt-get clean

RUN git clone --depth 1 https://github.com/searxng/searxng.git /searxng-src \
    && cd /searxng-src \
    && pip install --no-cache-dir -e .

RUN mkdir -p /etc/searxng
COPY searxng/settings.yml /etc/searxng/settings.yml

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN printf '[supervisord]\nnodaemon=true\nlogfile=/dev/stdout\nlogfile_maxbytes=0\n\n[program:searxng]\ncommand=python -m searx.webapp\nenvironment=SEARXNG_SETTINGS_PATH="/etc/searxng/settings.yml"\nautostart=true\nautorestart=true\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\nstderr_logfile=/dev/stderr\nstderr_logfile_maxbytes=0\n\n[program:scraper]\ncommand=uvicorn main:app --host 0.0.0.0 --port 8000\ndirectory=/app\nautostart=true\nautorestart=true\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\nstderr_logfile=/dev/stderr\nstderr_logfile_maxbytes=0\n' > /etc/supervisor/conf.d/powerscrapper.conf

EXPOSE 8000
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/powerscrapper.conf"]
