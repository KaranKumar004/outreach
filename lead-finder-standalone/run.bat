@echo off
setlocal enabledelayedexpansion
title LocalLeads Kit
echo ========================================================
echo        Starting LocalLeads Kit v1.0.2...
echo ========================================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Runtime and cache isolated in %LOCALAPPDATA%\LocalLeadsKit
set "KIT_RUNTIME_DIR=%LOCALAPPDATA%\LocalLeadsKit"
if not exist "%KIT_RUNTIME_DIR%" mkdir "%KIT_RUNTIME_DIR%"
set "UV_CACHE_DIR=%KIT_RUNTIME_DIR%\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%KIT_RUNTIME_DIR%\python"
set "VENV_DIR=%KIT_RUNTIME_DIR%\venv"
set "BIN_DIR=%KIT_RUNTIME_DIR%\bin"
if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"

:: Pinned official uv release 0.6.5 and SHA256 integrity hashes
set "UV_VERSION=0.6.5"

:: Detect architecture including 32-bit CMD on 64-bit Windows ARM64
set "ACTUAL_ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "ACTUAL_ARCH=%PROCESSOR_ARCHITEW6432%"

if /i "%ACTUAL_ARCH%"=="ARM64" (
    set "UV_TARGET=uv-aarch64-pc-windows-msvc.zip"
    set "UV_EXPECTED_HASH=2af20abb3a289d57ae6a8f34ec9f6a60276947fdfb80de6d7304a1b49242cc64"
) else (
    set "UV_TARGET=uv-x86_64-pc-windows-msvc.zip"
    set "UV_EXPECTED_HASH=a3e9f0913189c38b804bf6bb3d348af305a8ceabc690be92b6e111245a821640"
)
set "UV_URL=https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/%UV_TARGET%"

:: 1. Look for uv in kit bin or isolated runtime bin
set "UV_EXE="
if exist "%BIN_DIR%\uv.exe" (
    set "UV_EXE=%BIN_DIR%\uv.exe"
) else if exist "%SCRIPT_DIR%bin\uv.exe" (
    set "UV_EXE=%SCRIPT_DIR%bin\uv.exe"
) else if exist "%SCRIPT_DIR%uv.exe" (
    set "UV_EXE=%SCRIPT_DIR%uv.exe"
)

:: 2. If missing, download pinned uv and verify SHA256 checksum
if not defined UV_EXE (
    echo [1/4] Runtime manager ^(uv^) not found.
    echo       Downloading verified official uv v%UV_VERSION% for %ACTUAL_ARCH%...
    
    set "ZIP_PATH=%KIT_RUNTIME_DIR%\uv_download.zip"
    if exist "!ZIP_PATH!" del /f /q "!ZIP_PATH!"

    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%UV_URL%', '!ZIP_PATH!') } catch { exit 1 }"
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Failed to download uv runtime manager.
        echo Please check your internet connection or network firewall.
        if exist "!ZIP_PATH!" del /f /q "!ZIP_PATH!"
        pause
        exit /b 1
    )

    echo       Verifying cryptographic SHA256 checksum...
    for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 '!ZIP_PATH!').Hash.ToLower()"` ) do (
        set "ACTUAL_HASH=%%H"
    )

    if /i not "!ACTUAL_HASH!"=="%UV_EXPECTED_HASH%" (
        echo.
        echo [ERROR] Cryptographic checksum verification failed!
        echo Expected: %UV_EXPECTED_HASH%
        echo Actual:   !ACTUAL_HASH!
        echo The downloaded archive may be corrupted or compromised. Aborting.
        if exist "!ZIP_PATH!" del /f /q "!ZIP_PATH!"
        pause
        exit /b 1
    )
    echo       Checksum verified successfully.

    powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '!ZIP_PATH!' -DestinationPath '%KIT_RUNTIME_DIR%\bin_tmp' -Force; Move-Item -Path '%KIT_RUNTIME_DIR%\bin_tmp\uv.exe' -Destination '%BIN_DIR%\uv.exe' -Force; Remove-Item -Recurse -Force '%KIT_RUNTIME_DIR%\bin_tmp'"
    if exist "!ZIP_PATH!" del /f /q "!ZIP_PATH!"

    set "UV_EXE=%BIN_DIR%\uv.exe"
)

:: 3. Ensure Streamlit credentials exist to prevent first-run interactive prompt
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general] > "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

:: 4. Create isolated Python 3.11 virtual environment under %LOCALAPPDATA%\LocalLeadsKit if missing
if not exist "%VENV_DIR%" (
    echo [2/4] Setting up isolated Python 3.11 runtime in %KIT_RUNTIME_DIR%...
    "%UV_EXE%" venv "%VENV_DIR%" --python 3.11
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Failed to initialize Python 3.11 environment.
        echo Please verify available disk space and write permissions.
        pause
        exit /b 1
    )
)

:: 5. Install / sync dependencies into runtime venv
echo [3/4] Verifying dependencies...
"%UV_EXE%" pip install --python "%VENV_DIR%" -r "%SCRIPT_DIR%requirements.txt" --quiet
if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Dependency installation failed!
    echo Please verify your internet connection.
    pause
    exit /b 1
)

:: 6. Launch LocalLeads Kit via uv in .venv (CWD remains kit folder for user data)
echo [4/4] Launching LocalLeads Kit in your default browser...
echo.
"%UV_EXE%" run --python "%VENV_DIR%" streamlit run "%SCRIPT_DIR%app.py"

pause
