@echo off
setlocal EnableExtensions

set "SOURCE_SHA256=32de3247bed3c78fdb66a9fe6d6a973ac808982d2472f569a90809135df9cce5"
set "OUTPUT_SHA256=234e9f3bfac930e88cabf779ccc33abe343b4061896634b960c3d3b8deb07f86"
set "PATCH=%~dp0Disgaea_Infinite_ULJS00286_KR_v1.0.xdelta"
set "OUTPUT=%~dp0Disgaea_Infinite_ULJS00286_KR_v1.0.iso"

if "%~1"=="" (
  echo Usage: drag the original Japanese ISO onto this file.
  pause
  exit /b 2
)

set "DI_SOURCE=%~f1"
set "DI_OUTPUT=%OUTPUT%"

where xdelta3 >nul 2>nul
if errorlevel 1 (
  echo ERROR: xdelta3.exe was not found in PATH.
  pause
  exit /b 2
)

for /f %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath $env:DI_SOURCE).Hash.ToLower()"') do set "ACTUAL_SOURCE=%%H"
if /i not "%ACTUAL_SOURCE%"=="%SOURCE_SHA256%" (
  echo ERROR: unsupported source ISO.
  echo Expected: %SOURCE_SHA256%
  echo Actual:   %ACTUAL_SOURCE%
  pause
  exit /b 1
)

xdelta3 -d -s "%~f1" "%PATCH%" "%OUTPUT%"
if errorlevel 1 (
  echo ERROR: xdelta3 failed.
  pause
  exit /b 1
)

for /f %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath $env:DI_OUTPUT).Hash.ToLower()"') do set "ACTUAL_OUTPUT=%%H"
if /i not "%ACTUAL_OUTPUT%"=="%OUTPUT_SHA256%" (
  echo ERROR: output verification failed.
  echo Expected: %OUTPUT_SHA256%
  echo Actual:   %ACTUAL_OUTPUT%
  pause
  exit /b 1
)

echo Complete: %OUTPUT%
echo SHA-256: %ACTUAL_OUTPUT%
pause
