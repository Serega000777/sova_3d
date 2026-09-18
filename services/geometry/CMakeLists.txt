cmake_minimum_required(VERSION 3.22)
project(physical_ai_geometry VERSION 0.2.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(PHYSICAL_AI_BUILD_TESTS "Build CTest suite" ON)

find_package(OpenCASCADE REQUIRED)
find_package(nlohmann_json 3.11 REQUIRED)

set(OCCT_LIBS TKernel TKMath TKG2d TKG3d TKGeomBase TKGeomAlgo TKBRep TKTopAlgo TKPrim TKBO
              TKBool TKFillet TKShHealing TKMesh TKDESTL
              # STEP/IGES import (T-022)
              TKDESTEP TKDEIGES TKXSBase)
# OCCT < 7.8 names the data-exchange toolkits differently.
if(NOT TARGET TKDESTL AND TARGET TKSTL)
  list(TRANSFORM OCCT_LIBS REPLACE "TKDESTL" "TKSTL")
endif()
if(NOT TARGET TKDESTEP AND TARGET TKSTEP)
  list(TRANSFORM OCCT_LIBS REPLACE "TKDESTEP" "TKSTEP")
endif()
if(NOT TARGET TKDEIGES AND TARGET TKIGES)
  list(TRANSFORM OCCT_LIBS REPLACE "TKDEIGES" "TKIGES")
endif()

add_library(geometry_core src/geometry_core.cpp src/plan.cpp src/kernel.cpp)
target_include_directories(geometry_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src
                                                ${OpenCASCADE_INCLUDE_DIR})
target_link_libraries(geometry_core PUBLIC ${OCCT_LIBS} nlohmann_json::nlohmann_json)
target_compile_definitions(geometry_core PUBLIC
  GEOMETRY_SERVICE_VERSION="${PROJECT_VERSION}")
if(MSVC)
  target_compile_options(geometry_core PRIVATE /W4 /WX)
else()
  target_compile_options(geometry_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_executable(geometry-service src/main.cpp)
target_link_libraries(geometry-service PRIVATE geometry_core)
install(TARGETS geometry-service RUNTIME DESTINATION bin)

if(PHYSICAL_AI_BUILD_TESTS)
  enable_testing()
  add_executable(geometry_core_tests tests/test_geometry_core.cpp tests/test_kernel.cpp)
  target_link_libraries(geometry_core_tests PRIVATE geometry_core)
  target_compile_definitions(geometry_core_tests PRIVATE
    FIXTURES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures")
  add_test(NAME geometry_core_tests COMMAND geometry_core_tests)
  add_test(NAME cli_determinism
           COMMAND sh ${CMAKE_CURRENT_SOURCE_DIR}/tests/cli_determinism.sh
                   $<TARGET_FILE:geometry-service> ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures)
endif()
