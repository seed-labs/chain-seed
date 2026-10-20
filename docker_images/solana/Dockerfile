# seedemu-solana base image
#
# Ships the Agave validator toolchain (the production Solana client maintained by
# Anza, successor to the original solana-labs validator) so that SolanaService
# nodes can run a real, self-contained Solana cluster inside the emulator.
#
# Built on handsonsecurity/seedemu-base:2.0, the same base image used by
# the standard Docker compiler defaults.
#
# Design note (PRINCIPLES.md P5 "real production software, pinned version"):
# the Agave version is pinned for reproducibility. Binaries are obtained per
# target architecture:
#   * amd64 (x86_64): download the official pre-built release bundle (fast),
#                     pinned by SHA-256.
#   * arm64 (aarch64): Anza ships no arm64 Linux binaries, so build the same
#                      pinned version from source on this base (so glibc matches
#                      the runtime). The compile happens in a throwaway builder
#                      stage, so the final image stays lean.
#
# Build it (run once before compiling a Solana emulation):
#   amd64 host:        docker build -t seedemu-solana docker_images/solana
#   arm64 host:        docker build -t seedemu-solana docker_images/solana
#   (cross / force):   docker build --platform linux/amd64 -t seedemu-solana docker_images/solana
#
# The SolanaService maps BaseSystem.SEEDEMU_SOLANA to this image, so every Solana
# node shares it and the (download or compile) cost is paid only once.
#
# NOTE: the arm64 source build compiles a large Rust workspace; expect a long
#       build (tens of minutes) and give Docker ample RAM (>= 8 GB) and disk.

ARG SOLANA_VERSION=v2.2.14
ARG SOLANA_SHA256_AMD64=b5dadeb39ab7f31062c599ead459b9d809dd9d709365df6cb5943828b7693b36

# ---------------------------------------------------------------------------
# Common base image (same image the standard Docker compiler defaults use).
# ---------------------------------------------------------------------------
FROM handsonsecurity/seedemu-base:2.0 AS base

# ---------------------------------------------------------------------------
# amd64: download the official pre-built release into /out.
# ---------------------------------------------------------------------------
FROM base AS build-amd64
ARG SOLANA_VERSION
ARG SOLANA_SHA256_AMD64
ARG DEBIAN_FRONTEND=noninteractive
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl bzip2; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /out/bin; \
    archive="solana-release-x86_64-unknown-linux-gnu.tar.bz2"; \
    url="https://github.com/anza-xyz/agave/releases/download/${SOLANA_VERSION}/${archive}"; \
    curl -L --fail --retry 3 "$url" -o "/tmp/${archive}"; \
    echo "${SOLANA_SHA256_AMD64}  /tmp/${archive}" | sha256sum -c -; \
    mkdir -p /tmp/solana; \
    tar -xf "/tmp/${archive}" --strip-components=1 -C /tmp/solana; \
    for bin in solana solana-keygen solana-genesis solana-faucet agave-validator solana-test-validator; do \
        cp "/tmp/solana/bin/${bin}" /out/bin/; \
    done; \
    rm -rf "/tmp/${archive}" /tmp/solana

# ---------------------------------------------------------------------------
# arm64: build the same pinned version from source into /out, on this base so
# the resulting binaries match the runtime glibc.
# (Anza publishes no aarch64 Linux release binaries.)
# ---------------------------------------------------------------------------
FROM base AS build-arm64
ARG SOLANA_VERSION
ARG DEBIAN_FRONTEND=noninteractive
ENV CARGO_HOME=/root/.cargo \
    RUSTUP_HOME=/root/.rustup \
    PATH=/root/.cargo/bin:$PATH
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl git build-essential \
        libssl-dev libudev-dev pkg-config zlib1g-dev \
        llvm clang cmake make libprotobuf-dev protobuf-compiler; \
    rm -rf /var/lib/apt/lists/*
# Install rustup; the repo's rust-toolchain.toml pins the exact Rust version,
# which rustup installs automatically on first cargo invocation in the tree.
RUN set -eux; \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --no-modify-path --default-toolchain none
RUN set -eux; \
    git clone --depth 1 --branch "${SOLANA_VERSION}" https://github.com/anza-xyz/agave.git /tmp/agave; \
    cd /tmp/agave; \
    cargo build --release \
        --bin solana \
        --bin solana-keygen \
        --bin solana-genesis \
        --bin solana-faucet \
        --bin agave-validator; \
    mkdir -p /out/bin; \
    for bin in solana solana-keygen solana-genesis solana-faucet agave-validator; do \
        cp "/tmp/agave/target/release/${bin}" /out/bin/; \
    done; \
    # solana-test-validator is convenient for single-node debugging; build if possible.
    (cargo build --release --bin solana-test-validator \
        && cp /tmp/agave/target/release/solana-test-validator /out/bin/ || true); \
    rm -rf /tmp/agave /root/.cargo/registry /root/.cargo/git

# ---------------------------------------------------------------------------
# Select the per-architecture binary source. TARGETARCH is set by the builder
# to the target platform's arch (amd64 / arm64), so the matching stage is used.
# ---------------------------------------------------------------------------
FROM build-${TARGETARCH} AS binaries

# ---------------------------------------------------------------------------
# Final runtime image: the SEED base + the selected Agave binaries.
# ---------------------------------------------------------------------------
FROM base
ARG DEBIAN_FRONTEND=noninteractive
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates bzip2 jq; \
    rm -rf /var/lib/apt/lists/*

COPY --from=binaries /out/bin/ /opt/solana/bin/
RUN set -eux; \
    for bin in /opt/solana/bin/*; do ln -sf "$bin" "/usr/local/bin/$(basename "$bin")"; done; \
    /usr/local/bin/solana --version

# Keep WORKDIR at '/'. seedemu's generated start.sh and interface_setup run from
# the container's WORKDIR and read helper files such as ifinfo.txt by relative
# path (they live at '/'); a non-root WORKDIR would break interface renaming and
# routing on every node.
WORKDIR /

CMD ["/bin/bash"]
