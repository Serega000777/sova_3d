# Build + test the deterministic geometry service. OCCT is not linked yet (T-022).
FROM ubuntu:24.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build \
    && ctest --test-dir build --output-on-failure

FROM ubuntu:24.04
COPY --from=build /src/build/geometry-service /usr/local/bin/geometry-service
ENTRYPOINT ["geometry-service"]
