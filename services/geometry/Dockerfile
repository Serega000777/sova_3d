# Build + test the deterministic geometry service against Open CASCADE from Debian
# (7.8.x on trixie; the pack pins 8.0 — upgrade when a distro or vendored build lands).
# The runtime stage matches python:3.13-slim (trixie) so the worker image can COPY the binary.
FROM debian:trixie-slim AS build
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::http::Pipeline-Depth "0";\n' > /etc/apt/apt.conf.d/99network
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build nlohmann-json3-dev libtbb-dev libfontconfig-dev \
      libocct-foundation-dev libocct-modeling-data-dev libocct-modeling-algorithms-dev \
      libocct-data-exchange-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build \
    && ctest --test-dir build --output-on-failure

FROM debian:trixie-slim
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::http::Pipeline-Depth "0";\n' > /etc/apt/apt.conf.d/99network
RUN apt-get update && apt-get install -y --no-install-recommends \
      libocct-foundation-7.8 libocct-modeling-data-7.8 libocct-modeling-algorithms-7.8 \
      libocct-data-exchange-7.8 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/geometry-service /usr/local/bin/geometry-service
ENTRYPOINT ["geometry-service"]
CMD ["version"]
