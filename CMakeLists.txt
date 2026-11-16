cmake_minimum_required(VERSION 3.24)
if(POLICY CMP0141)
    cmake_policy(SET CMP0141 NEW)
endif()
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "$<$<CONFIG:Debug,RelWithDebInfo>:Embedded>")
set(CMAKE_TRY_COMPILE_CONFIGURATION Release)
project(KirbyTripleDeluxeNative LANGUAGES C CXX)

if(WIN32)
    if(NOT MSVC OR NOT MSVC_CXX_ARCHITECTURE_ID STREQUAL "x64")
        message(FATAL_ERROR "Use the Windows x64 MSVC toolchain")
    endif()
elseif(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR
       NOT CMAKE_SIZEOF_VOID_P EQUAL 8 OR NOT CMAKE_SYSTEM_PROCESSOR STREQUAL "x86_64")
    message(FATAL_ERROR "Supported systems are Windows x64 and Linux x86-64")
endif()
set(CMAKE_C_STANDARD 17)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

set(KIRBY_UPSTREAM "${CMAKE_CURRENT_SOURCE_DIR}/build/upstream" CACHE PATH "Pinned dependency directory")
set(RUNTIME "${CMAKE_CURRENT_BINARY_DIR}/runtime")
set(GENERATED "${CMAKE_CURRENT_SOURCE_DIR}/generated/kirby-eur")
find_package(Python3 REQUIRED COMPONENTS Interpreter)
if(WIN32)
    set(SDL_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/build/upstream/SDL3-3.4.0-src")
else()
    set(SDL_SOURCE "${KIRBY_UPSTREAM}/SDL3-3.4.0-linux")
endif()
if(NOT EXISTS "${SDL_SOURCE}/CMakeLists.txt")
    message(FATAL_ERROR "Prepare the SDL source with build.cmd on Windows or build.sh on Linux")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS tools/patch_sdl.py)
execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/patch_sdl.py"
    "${SDL_SOURCE}/src/gpu/vulkan/SDL_gpu_vulkan.c"
    COMMAND_ERROR_IS_FATAL ANY)
set(SDL_TEST_LIBRARY OFF)
if(WIN32)
    set(SDL_SHARED ON)
    set(SDL_STATIC OFF)
    set(DXC "${KIRBY_UPSTREAM}/dxc-1.8.2505.1/bin/x64/dxc.exe")
else()
    find_package(Threads REQUIRED)
    find_package(OpenSSL REQUIRED COMPONENTS Crypto)
    set(SDL_SHARED OFF)
    set(SDL_STATIC ON)
    set(DXC "${KIRBY_UPSTREAM}/dxc-linux-1.8.2505.1/bin/dxc")
endif()
add_subdirectory("${SDL_SOURCE}" "${CMAKE_CURRENT_BINARY_DIR}/sdl" EXCLUDE_FROM_ALL)

set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS tools/prepare_runtime.py tools/render_optimizations.py)
execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_runtime.py"
    "${KIRBY_UPSTREAM}/clockwork-master/runtime" "${RUNTIME}"
    COMMAND_ERROR_IS_FATAL ANY)

file(GLOB TRANSLATED CONFIGURE_DEPENDS "${GENERATED}/*.c")
if(NOT TRANSLATED)
    message(FATAL_ERROR "Generate the native game code with build.cmd or build.sh first")
endif()
add_library(game_code OBJECT ${TRANSLATED})
set_source_files_properties(${TRANSLATED} PROPERTIES
    OBJECT_DEPENDS "${RUNTIME}/include/recomp.h;${GENERATED}/funcs.h")
target_include_directories(game_code PRIVATE "${RUNTIME}/include" "${GENERATED}")
target_compile_definitions(game_code PRIVATE RECOMP_TRACE_CALLS)
option(KIRBY_FAST_BUILD "Skip optimization of generated code for iterations" OFF)
if(MSVC)
    target_compile_options(game_code PRIVATE /bigobj /fp:precise /utf-8 /w
        $<IF:$<BOOL:${KIRBY_FAST_BUILD}>,/Od,/O1>)
else()
    target_compile_options(game_code PRIVATE -ffp-contract=off -fwrapv
        $<IF:$<BOOL:${KIRBY_FAST_BUILD}>,-O0,-O1>)
endif()

set(RUNTIME_FILES
    arm_ops.c audio/bcstm.cpp audio/dsp_hle.cpp
    dump.cpp frontend/sdl.cpp frontend/settings.cpp
    hle/apt.cpp hle/cfg.cpp hle/dsp.cpp hle/err.cpp hle/frd.cpp hle/fs.cpp
    hle/gsp.cpp hle/hid.cpp hle/offline.cpp hle/ptm.cpp hle/service.cpp hle/srv.cpp
    hle/stubs.cpp hle/uds.cpp hle/y2r.cpp
    kernel/kernel.cpp kernel/svc.cpp level5.cpp loader.cpp log.cpp memory.cpp mods.cpp
    net/air.cpp net/relay.cpp platform.cpp
    video/gpu/gpu.cpp video/lighting.cpp video/pica.cpp video/raster.cpp video/shader.cpp
    video/texture.cpp video/transfer.cpp video/upscale.cpp video/widescreen.cpp
)
list(TRANSFORM RUNTIME_FILES PREPEND "${RUNTIME}/src/")

set(PORT_FILES src/main.cpp src/shared_font.cpp src/account.cpp src/cecd.cpp src/pica_shader_jit.cpp ${RUNTIME_FILES})
# The copied ABI and runtime headers also need to trigger rebuilds with localized MSVC.
file(GLOB_RECURSE RUNTIME_HEADERS CONFIGURE_DEPENDS "${RUNTIME}/src/*.h" "${RUNTIME}/include/*.h")
file(GLOB PORT_HEADERS CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/src/*.h")
set_source_files_properties(${PORT_FILES} PROPERTIES OBJECT_DEPENDS "${RUNTIME_HEADERS};${PORT_HEADERS}")
add_executable(KirbyTripleDeluxe ${PORT_FILES})
set(XBYAK "${KIRBY_UPSTREAM}/xbyak-df112862583c2d327c1d9782fd28f53aa675f11d")
set(LCD_HEADER "${CMAKE_CURRENT_BINARY_DIR}/kirby_lcd.inc")
add_custom_command(OUTPUT "${LCD_HEADER}"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/compile_lcd.py"
        "${DXC}" "${CMAKE_CURRENT_SOURCE_DIR}/src/lcd_blit.hlsl" "${LCD_HEADER}"
    DEPENDS tools/compile_lcd.py src/lcd_blit.hlsl "${DXC}"
    VERBATIM)
target_sources(KirbyTripleDeluxe PRIVATE "${LCD_HEADER}")
set_property(SOURCE "${RUNTIME}/src/video/gpu/gpu.cpp" APPEND PROPERTY OBJECT_DEPENDS "${LCD_HEADER}")
target_include_directories(KirbyTripleDeluxe PRIVATE "${RUNTIME}/include" "${RUNTIME}/src" src "${XBYAK}" "${CMAKE_CURRENT_BINARY_DIR}")
target_link_libraries(KirbyTripleDeluxe PRIVATE game_code SDL3::SDL3)
if(WIN32)
    target_compile_definitions(KirbyTripleDeluxe PRIVATE NOMINMAX _CRT_SECURE_NO_WARNINGS)
    target_compile_options(KirbyTripleDeluxe PRIVATE /W3 /utf-8 /Zc:__cplusplus)
    # A translated call frame contains more host state than the corresponding ARM stack frame.
    target_link_options(KirbyTripleDeluxe PRIVATE /STACK:8388608)
    target_link_libraries(KirbyTripleDeluxe PRIVATE ws2_32 bcrypt)
    # Recopy the DLL when only SDL has changed, even if the executable did not relink.
    add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/SDL3.dll"
        COMMAND "${CMAKE_COMMAND}" -E copy "$<TARGET_FILE:SDL3::SDL3>" "${CMAKE_CURRENT_BINARY_DIR}/SDL3.dll"
        DEPENDS SDL3::SDL3
        VERBATIM)
    add_custom_target(kirby_sdl_dll DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/SDL3.dll")
    add_dependencies(KirbyTripleDeluxe kirby_sdl_dll)
else()
    target_link_libraries(KirbyTripleDeluxe PRIVATE OpenSSL::Crypto Threads::Threads)
endif()

enable_testing()
add_test(NAME cartridge_integrity COMMAND "${Python3_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/verify_extraction.py" "${CMAKE_CURRENT_SOURCE_DIR}/extracted/KIRBY-EUR.cxi")
add_test(NAME native_startup_bss COMMAND KirbyTripleDeluxe --verify-startup "${CMAKE_CURRENT_SOURCE_DIR}/extracted/KIRBY-EUR.cxi")
add_test(NAME sdl_gamepad_mapping COMMAND KirbyTripleDeluxe --verify-gamepad)
