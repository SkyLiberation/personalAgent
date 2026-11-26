ARG BASE_IMAGE=personal-agent-bash:local
FROM node:24-bookworm-slim AS runtime
RUN npm install --prefix /opt/dsh --omit=dev --no-audit --no-fund @deepseek-ai/dsh@0.2.2-rc.5

FROM ${BASE_IMAGE}
USER root
COPY --from=runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=runtime /opt/dsh /opt/dsh
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends bubblewrap \
    && rm -rf /var/lib/apt/lists/*
USER 65534:65534
ENTRYPOINT ["/usr/local/bin/node", "/opt/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js"]
