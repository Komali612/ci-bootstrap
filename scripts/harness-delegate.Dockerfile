# Harness Docker delegate + a static docker CLI.
#
# The stock harness/delegate image has no `docker` client, but our CD deploy
# steps drive the host Docker through the mounted /var/run/docker.sock. Baking
# the client in at BUILD time (as root) avoids the INIT_SCRIPT approach, which
# runs as the unprivileged `harness` user and can't write to /usr/local/bin.
ARG BASE=harness/delegate:26.07.89703
FROM ${BASE}
USER root
RUN set -eux; \
    arch="$(uname -m)"; \
    curl -fsSL "https://download.docker.com/linux/static/stable/${arch}/docker-27.3.1.tgz" -o /tmp/d.tgz; \
    tar xzf /tmp/d.tgz -C /tmp; \
    install -m0755 /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/d.tgz /tmp/docker; \
    docker --version
USER 1001
