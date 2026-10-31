cmake_minimum_required(VERSION 3.18)
project(amxpy_module CXX)

# 32-битный CPython (scripts/build-runtime.sh) и заголовки SDK (scripts/fetch-sdk.sh)
set(AMXPY_RUNTIME "${CMAKE_CURRENT_SOURCE_DIR}/../build/runtime-i386" CACHE PATH "Префикс 32-битного CPython")
set(AMXPY_SDK "${CMAKE_CURRENT_SOURCE_DIR}/third_party/reapi/reapi/include" CACHE PATH "include/ из ReAPI")
set(AMXPY_PY_VERSION "3.14" CACHE STRING "Версия CPython рантайма")

if(NOT EXISTS "${AMXPY_SDK}/cssdk/dlls/regamedll_api.h")
    message(FATAL_ERROR "Нет заголовков SDK в ${AMXPY_SDK}: запустите scripts/fetch-sdk.sh")
endif()
if(NOT EXISTS "${AMXPY_RUNTIME}/include/python${AMXPY_PY_VERSION}/Python.h")
    message(FATAL_ERROR "Нет 32-битного CPython в ${AMXPY_RUNTIME}: запустите scripts/build-runtime.sh")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(SDK_INCLUDES
    ${AMXPY_SDK}/cssdk/common
    ${AMXPY_SDK}/cssdk/dlls
    ${AMXPY_SDK}/cssdk/engine
    ${AMXPY_SDK}/cssdk/game_shared
    ${AMXPY_SDK}/cssdk/pm_shared
    ${AMXPY_SDK}/cssdk/public
    ${AMXPY_SDK}/metamod
)
set(SDK_DEFINES _LINUX LINUX HAVE_STRONG_TYPEDEF _stricmp=strcasecmp _strnicmp=strncasecmp
    _vsnprintf=vsnprintf _snprintf=snprintf)
set(COMMON_FLAGS -m32 -Wall -Wno-unknown-pragmas -Wno-invalid-offsetof -fno-strict-aliasing)

add_library(amxpy_amxx SHARED
    src/amxx_api.cpp
    src/meta_glue.cpp
    src/module.cpp
    src/python_host.cpp
    src/core_module.cpp
    src/natives.cpp
    src/hooks.cpp
    src/bridge.cpp
    ${AMXPY_SDK}/cssdk/public/interface.cpp
)
# libpython ищется рядом с модулем: cstrike/addons/amxpy/runtime/lib.
# Через свойства, а не -Wl,-rpath: так CMake сам экранирует $ORIGIN под любой генератор.
set_target_properties(amxpy_amxx PROPERTIES
    OUTPUT_NAME amxpy_amxx_i386
    PREFIX ""
    BUILD_WITH_INSTALL_RPATH TRUE
    INSTALL_RPATH "$ORIGIN/../../amxpy/runtime/lib"
)
target_include_directories(amxpy_amxx PRIVATE src ${SDK_INCLUDES}
    ${AMXPY_RUNTIME}/include/python${AMXPY_PY_VERSION})
target_compile_definitions(amxpy_amxx PRIVATE ${SDK_DEFINES}
    AMXPY_PYTHON_SONAME="libpython${AMXPY_PY_VERSION}.so.1.0")
target_compile_options(amxpy_amxx PRIVATE ${COMMON_FLAGS} -O2 -fvisibility=hidden)
target_link_options(amxpy_amxx PRIVATE -m32 -static-libgcc -static-libstdc++ -Wl,--exclude-libs,ALL)
target_link_libraries(amxpy_amxx PRIVATE
    ${AMXPY_RUNTIME}/lib/libpython${AMXPY_PY_VERSION}.so dl)

# Фейковый HLDS + Metamod + AMXX: проверка модуля без сервера (scripts/test-module.sh)
add_executable(amxpy_harness tests/harness.cpp)
target_include_directories(amxpy_harness PRIVATE src ${SDK_INCLUDES})
target_compile_definitions(amxpy_harness PRIVATE ${SDK_DEFINES})
target_compile_options(amxpy_harness PRIVATE ${COMMON_FLAGS} -O0 -g)
target_link_options(amxpy_harness PRIVATE -m32)
target_link_libraries(amxpy_harness PRIVATE dl z)
