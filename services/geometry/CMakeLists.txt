cmake_minimum_required(VERSION 3.28)
project(physical_ai_geometry LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
add_executable(geometry-service src/main.cpp)
# TODO(T-003/F-064): find_package(OpenCASCADE 8 REQUIRED) and link selected modules.
