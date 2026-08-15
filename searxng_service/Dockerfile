FROM searxng/searxng:latest
COPY settings.yml /etc/searxng/settings.yml
COPY entrypoint.sh /custom-entrypoint.sh
RUN chmod +x /custom-entrypoint.sh
ENTRYPOINT ["/custom-entrypoint.sh"]
