FROM python:3.12-slim

# Install Node.js (for pi)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg git zsh \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @earendil-works/pi-coding-agent \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 pipal \
    && chsh -s /usr/bin/zsh pipal
USER pipal
WORKDIR /home/pipal
ENV PATH="/home/pipal/.local/bin:${PATH}"

# Install oh-my-zsh + powerlevel10k
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended \
    && git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ${ZSH_CUSTOM:-/home/pipal/.oh-my-zsh/custom}/themes/powerlevel10k \
    && sed -i 's/^ZSH_THEME=.*/ZSH_THEME="powerlevel10k\/powerlevel10k"/' /home/pipal/.zshrc \
    && echo '\n# Load p10k config if present\n[[ -f ~/.p10k.zsh ]] && source ~/.p10k.zsh' >> /home/pipal/.zshrc

# Shared p10k config
COPY --chown=pipal:pipal docker/p10k.zsh /home/pipal/.p10k.zsh

# Install pipal from local source (private repo)
COPY --chown=pipal:pipal . /tmp/pipal
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir /tmp/pipal \
    && rm -rf /tmp/pipal

# When the repo is public, this is simpler:
# RUN python -m pip install --no-cache-dir --upgrade pip \
#     && pip install --no-cache-dir git+https://github.com/mohammadbashiri/pipal.git

ENTRYPOINT ["pipal"]
