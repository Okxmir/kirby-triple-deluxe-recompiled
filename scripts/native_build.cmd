@echo off
setlocal
if "%~5"=="" exit /b 2
call "%~1" -arch=x64 -host_arch=x64 >nul
if errorlevel 1 exit /b 1
cd /d "%~dp0.."
set "CMAKEBIN=%~2\Common7\IDE\CommonExtensions\Microsoft\CMake"
set "PATH=%CMAKEBIN%\CMake\bin;%CMAKEBIN%\Ninja;%PATH%"
set "BUILD=build\windows-%~3"
if not defined CMAKE_BUILD_PARALLEL_LEVEL set "CMAKE_BUILD_PARALLEL_LEVEL=6"
cmake -S . -B "%BUILD%" -G Ninja "-DCMAKE_BUILD_TYPE=%~3" "-DKIRBY_UPSTREAM=%~4" "-DKIRBY_FAST_BUILD=%~5"
if errorlevel 1 exit /b 1
cmake --build "%BUILD%"
exit /b %errorlevel%
