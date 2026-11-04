cmake_minimum_required(VERSION 3.18)
project(stormcore CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(STORM_CORE_SOURCES
    ${CMAKE_CURRENT_LIST_DIR}/src/asset.cpp
    ${CMAKE_CURRENT_LIST_DIR}/src/animation.cpp
    ${CMAKE_CURRENT_LIST_DIR}/src/game.cpp
    ${CMAKE_CURRENT_LIST_DIR}/src/ai.cpp
    ${CMAKE_CURRENT_LIST_DIR}/src/perf.cpp
    ${CMAKE_CURRENT_LIST_DIR}/src/scene.cpp)

if(ANDROID)
    add_library(stormcore STATIC ${STORM_CORE_SOURCES})
    target_include_directories(stormcore PUBLIC ${CMAKE_CURRENT_LIST_DIR}/include)
    target_compile_options(stormcore PRIVATE -O2 -fno-exceptions -fno-rtti -Wall -Wextra)

    add_library(stormjni SHARED
        ${CMAKE_CURRENT_LIST_DIR}/platform/android/jni_bridge.cpp
        ${CMAKE_CURRENT_LIST_DIR}/src/render/gl_renderer.cpp)
    target_include_directories(stormjni PRIVATE
        ${CMAKE_CURRENT_LIST_DIR}/include
        ${CMAKE_CURRENT_LIST_DIR}/src)
    target_compile_options(stormjni PRIVATE -O2 -fno-exceptions -fno-rtti -Wall -Wextra)
    target_link_libraries(stormjni stormcore android log EGL GLESv3)
else()
    add_library(stormcore STATIC ${STORM_CORE_SOURCES})
    target_include_directories(stormcore PUBLIC ${CMAKE_CURRENT_LIST_DIR}/include)
    target_compile_options(stormcore PRIVATE -Wall -Wextra)

    add_executable(storm_host_tests
        ${CMAKE_CURRENT_LIST_DIR}/tests/host_tests.cpp)
    target_link_libraries(storm_host_tests PRIVATE stormcore)
    target_include_directories(storm_host_tests PRIVATE ${CMAKE_CURRENT_LIST_DIR}/include)

    enable_testing()
    set(STORM_REPO_ROOT ${CMAKE_CURRENT_LIST_DIR}/..)
    add_test(NAME storm_host_tests
             COMMAND storm_host_tests ${STORM_REPO_ROOT}/android/app/src/main/assets)
    set_tests_properties(storm_host_tests PROPERTIES
                         WORKING_DIRECTORY ${STORM_REPO_ROOT})
endif()
