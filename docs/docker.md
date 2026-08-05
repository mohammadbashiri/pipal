# Docker usage

## Build image

From the repo root:
```bash
docker build -t pipal:latest .
```

## Choose data directories (fresh vs reuse)

You can mix and match any combination:
- **Fresh (docker-only)**: `~/.pipal-docker` and `~/.pi-docker`
- **Reuse host data**: `~/.pipal` and/or `~/.pi`

Create fresh data dirs (recommended for a clean Docker-only setup):
```bash
mkdir -p ~/.pipal-docker ~/.pi-docker
```

## Run a pipal command
```bash
docker run -it --rm \
  -v ~/.pipal-docker:/home/pipal/.pipal \
  -v ~/.pi-docker:/home/pipal/.pi \
  pipal:latest agent chat momo
```

## Run the server

`pipal serve` defaults to `127.0.0.1`. In Docker, bind to `0.0.0.0` inside the container and set an auth token. Pipal refuses non-local binds without one.

```bash
docker run -it --rm -p 127.0.0.1:8000:8000 \
  -e PIPAL_AUTH_TOKEN="replace-with-long-random-token" \
  -v ~/.pipal-docker:/home/pipal/.pipal \
  -v ~/.pi-docker:/home/pipal/.pi \
  pipal:latest serve --host 0.0.0.0 --port 8000
```

Keep the published port on localhost unless remote access is intentional. For remote access, use TLS and network controls such as a VPN, firewall, or authenticated reverse proxy.

## Log in to pi inside the container
```bash
docker run -it --rm \
  -v ~/.pipal-docker:/home/pipal/.pipal \
  -v ~/.pi-docker:/home/pipal/.pi \
  --entrypoint pi \
  pipal:latest
```

## Open a shell inside the container
```bash
docker run -it --rm \
  -v ~/.pipal-docker:/home/pipal/.pipal \
  -v ~/.pi-docker:/home/pipal/.pi \
  --entrypoint /bin/zsh \
  pipal:latest
```

## Mount current directory into the container
```bash
docker run -it --rm \
  -v ~/.pipal-docker:/home/pipal/.pipal \
  -v ~/.pi-docker:/home/pipal/.pi \
  -v "$(pwd)":/home/pipal/work \
  --entrypoint /bin/zsh \
  pipal:latest
```

Inside the container:
```bash
cd /home/pipal/work
```
