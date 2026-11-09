# Runtime for one coding-agent run: a plain Ubuntu with the tools an agent and a Maven/Ant build need.
# The JDKs, Maven, Ant, dependency caches, the case tree and the Claude Code CLI are bind-mounted.
FROM ubuntu:22.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      git python3 procps psmisc findutils less ca-certificates curl unzip zip file diffutils patch \
      iproute2 netcat-openbsd lsof sudo locales tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
