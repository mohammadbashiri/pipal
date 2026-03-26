FROM python:3.12-slim

# Install Node.js (for pi)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @mariozechner/pi-coding-agent \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 pipal
USER pipal
WORKDIR /home/pipal
ENV PATH="/home/pipal/.local/bin:${PATH}"

# Install pipal from local source (private repo)
COPY --chown=pipal:pipal . /tmp/pipal
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir /tmp/pipal \
    && rm -rf /tmp/pipal

# When the repo is public, this is simpler:
# RUN python -m pip install --no-cache-dir --upgrade pip \
#     && pip install --no-cache-dir git+https://github.com/mohammadbashiri/pipal.git

ENTRYPOINT ["pipal"]
