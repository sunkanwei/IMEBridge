@echo off
setlocal EnableExtensions EnableDelayedExpansion

chcp 65001 >nul
title Build IMEBridge Extension

set "EXT_DIR=%~dp0"
set "EXT_DIR=%EXT_DIR:~0,-1%"
set "MANIFEST=%EXT_DIR%\blender_manifest.toml"
set "BLENDER_EXE=%EXT_DIR%\..\..\..\..\blender.exe"

for %%I in ("%BLENDER_EXE%") do set "BLENDER_EXE=%%~fI"

if not exist "%MANIFEST%" (
    echo ERROR: blender_manifest.toml was not found.
    echo Path: "%MANIFEST%"
    pause
    exit /b 1
)

if not exist "%BLENDER_EXE%" (
    for %%I in (blender.exe) do set "BLENDER_EXE=%%~$PATH:I"
)

if not exist "%BLENDER_EXE%" (
    echo ERROR: Blender executable was not found.
    echo Expected: "%EXT_DIR%\..\..\..\..\blender.exe"
    echo You can also add blender.exe to PATH.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP_DIR=%%D"
if not defined DESKTOP_DIR set "DESKTOP_DIR=%USERPROFILE%\Desktop"

if not exist "%DESKTOP_DIR%" (
    echo ERROR: Desktop directory was not found.
    echo Path: "%DESKTOP_DIR%"
    pause
    exit /b 1
)

set "EXT_ID="
set "EXT_VERSION="
for /f "tokens=1,* delims==" %%A in ('findstr /r /c:"^id[ ]*=" /c:"^version[ ]*=" "%MANIFEST%"') do (
    set "KEY=%%A"
    set "VALUE=%%B"
    set "KEY=!KEY: =!"
    set "VALUE=!VALUE: =!"
    set "VALUE=!VALUE:"=!"
    if /i "!KEY!"=="id" set "EXT_ID=!VALUE!"
    if /i "!KEY!"=="version" set "EXT_VERSION=!VALUE!"
)

if defined EXT_ID if defined EXT_VERSION set "ZIP_NAME=%EXT_ID%-%EXT_VERSION%.zip"

if not defined ZIP_NAME (
    echo ERROR: Could not read id/version from blender_manifest.toml.
    pause
    exit /b 1
)

set "ZIP_PATH=%DESKTOP_DIR%\%ZIP_NAME%"

echo.
echo IMEBridge extension build
echo Source : "%EXT_DIR%"
echo Blender: "%BLENDER_EXE%"
echo Output : "%ZIP_PATH%"
echo.

echo Checking package exclusions...
echo README.md, build_extension.bat, .git, __pycache__, and .pyc files are outside [build].paths.

if exist "%ZIP_PATH%" (
    echo Removing previous package on Desktop...
    del /q "%ZIP_PATH%"
)

echo.
echo Validating extension source...
"%BLENDER_EXE%" --factory-startup --command extension validate "%EXT_DIR%"
if errorlevel 1 goto :fail

echo.
echo Building extension package...
"%BLENDER_EXE%" --factory-startup --command extension build --source-dir "%EXT_DIR%" --output-dir "%DESKTOP_DIR%" --verbose
if errorlevel 1 goto :fail

if not exist "%ZIP_PATH%" (
    echo ERROR: Build finished but the package was not found.
    echo Expected: "%ZIP_PATH%"
    pause
    exit /b 1
)

echo.
echo Checking package contents...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $zip = '%ZIP_PATH%'; $archive = [IO.Compression.ZipFile]::OpenRead($zip); try { $bad = @($archive.Entries | Where-Object { $_.FullName -match '(^|/)README\.md$|(^|/)build_extension\.bat$|(^|/)\.git(/|$)|__pycache__|\.pyc$|\.bat$' } | ForEach-Object { $_.FullName }); if ($bad.Count -gt 0) { Write-Host 'ERROR: package contains excluded files:'; $bad | ForEach-Object { Write-Host ('  ' + $_) }; exit 1 } } finally { $archive.Dispose() }"
if errorlevel 1 goto :fail

echo.
echo Done.
echo Created: "%ZIP_PATH%"
echo.
echo The package is built by Blender's official extension command.
echo README.md, this BAT file, .git, __pycache__, and .pyc files were not included.
pause
exit /b 0

:fail
echo.
echo ERROR: Build failed.
pause
exit /b 1
