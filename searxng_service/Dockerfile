FROM searxng/searxng:latest
COPY settings.yml /etc/searxng/settings.yml
# Override Granian defaults for Railway compatibility
ENV GRANIAN_HOST="0.0.0.0"
ENV GRANIAN_INTERFACE="wsgi"
ENV GRANIAN_BLOCKING_THREADS="4"
# Use the image's own entrypoint — no override
