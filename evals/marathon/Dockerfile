ARG BASE_IMAGE=personal-agent-bash:local
FROM ${BASE_IMAGE}
USER root
COPY --from=toolchain /go.tar.gz /tmp/marathon-go.tar.gz
COPY --from=toolchain /node.tar.xz /tmp/marathon-node.tar.xz
RUN echo '65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40  /tmp/marathon-go.tar.gz' | sha256sum -c - \
    && echo '9aa8e9d2298ab68c600bd6fb86a6c13bce11a4eca1ba9b39d79fa021755d7c37  /tmp/marathon-node.tar.xz' | sha256sum -c - \
    && tar -C /opt -xzf /tmp/marathon-go.tar.gz \
    && python -m tarfile -e /tmp/marathon-node.tar.xz /opt \
    && rm /tmp/marathon-go.tar.gz /tmp/marathon-node.tar.xz
ENV PATH="/opt/go/bin:/opt/node-v22.22.0-linux-x64/bin:${PATH}"
COPY --from=toolchain /package.json /opt/marathon/package.json
RUN npm --prefix /opt/marathon install --no-audit --no-fund \
    && python -m pip install --no-cache-dir pytest==8.4.2 scipy==1.16.3 sympy==1.14.0 h5py==3.15.1 httpx==0.28.1
ENV GOFLAGS=-mod=mod GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off CGO_ENABLED=0 \
    GOCACHE=/workspace/marathon/work/.scratch/go-cache GOPATH=/workspace/marathon/work/.scratch/go \
    GOTMPDIR=/workspace/marathon/work/.scratch
WORKDIR /workspace/marathon/work
USER 65534:65534
