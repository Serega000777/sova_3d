cmake_minimum_required(VERSION 3.22)
project(physical_ai_geometry VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(PHYSICAL_AI_WITH_OCCT "Link Open CASCADE Technology (T-022/T-033)" OFF)
option(PHYSICAL_AI_BUILD_TESTS "Build CTest suite" ON)

add_library(geometry_core src/geometry_core.cpp)
target_include_directories(geometry_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_definitions(geometry_core PUBLIC
  GEOMETRY_SERVICE_VERSION="${PROJECT_VERSION}")
if(MSVC)
  target_compile_options(geometry_core PRIVATE /W4 /WX)
else()
  target_compile_options(geometry_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

if(PHYSICAL_AI_WITH_OCCT)
  find_package(OpenCASCADE REQUIRED)
  target_link_libraries(geometry_core PUBLIC ${OpenCASCADE_LIBRARIES})
  target_compile_definitions(geometry_core PUBLIC PHYSICAL_AI_WITH_OCCT=1)
endif()

add_executable(geometry-service src/main.cpp)
target_link_libraries(geometry-service PRIVATE geometry_core)

if(PHYSICAL_AI_BUILD_TESTS)
  enable_testing()
  add_executable(geometry_core_tests tests/test_geometry_core.cpp)
  target_link_libraries(geometry_core_tests PRIVATE geometry_core)
  add_test(NAME geometry_core_tests COMMAND geometry_core_tests)
endif()
