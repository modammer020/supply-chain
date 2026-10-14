FROM busybox:latest
COPY mc /usr/local/bin/mc
ENTRYPOINT ["/usr/local/bin/mc"]
