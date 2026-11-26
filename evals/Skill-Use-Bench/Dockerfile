FROM personal-agent-bash:local
USER root
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends pdftk-java poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/skill-use-bench/work
USER 65534:65534
