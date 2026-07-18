@echo off
setlocal EnableExtensions DisableDelayedExpansion
title File Converter Installer

set "NO_PAUSE=0"
set "ASSUME_YES=0"

:ParseArguments
if "%~1"=="" goto ArgumentsReady
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"
if /I "%~1"=="--yes" set "ASSUME_YES=1"
shift
goto ParseArguments

:ArgumentsReady

set "ROOT=%~dp0"
set "APP_FILE=%ROOT%File Converter.pyw"
set "LOG=%ROOT%setup.log"
set "RUNTIME=%ROOT%.runtime"
set "DOWNLOADS=%RUNTIME%\downloads"
set "VENV=%ROOT%.venv"
set "VENV_PY=%VENV%\Scripts\python.exe"
set "VENV_PYW=%VENV%\Scripts\pythonw.exe"
set "FFMPEG_DIR=%RUNTIME%\ffmpeg"
set "FFMPEG_EXE=%FFMPEG_DIR%\ffmpeg.exe"
set "FFPROBE_EXE=%FFMPEG_DIR%\ffprobe.exe"
set "PYSIDE_VERSION=6.11.1"
set "PILLOW_VERSION=12.3.0"
set "PILLOW_HEIF_VERSION=1.4.0"
set "PY7ZR_VERSION=1.1.3"
set "FFMPEG_VERSION=8.1.2"
set "PYPI_INDEX=https://pypi.org/simple"
set "FFMPEG_URL=https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/ffmpeg-8.1.2-essentials_build.zip"
set "FFMPEG_SHA256=DB580001CAA24AC104C8CB856CD113A87B0A443F7BDF47D8C12B1D740584A2EC"

set "NATIVE_ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "NATIVE_ARCH=%PROCESSOR_ARCHITEW6432%"
if /I "%NATIVE_ARCH%"=="AMD64" goto ArchitectureReady
set "FAIL_MESSAGE=This installer currently supports x64 Windows only."
goto Failed

:ArchitectureReady
if not exist "%RUNTIME%" mkdir "%RUNTIME%" >nul 2>&1
if not exist "%RUNTIME%" (
    set "FAIL_MESSAGE=Could not create the private runtime folder."
    goto Failed
)
if not exist "%DOWNLOADS%" mkdir "%DOWNLOADS%" >nul 2>&1
if not exist "%DOWNLOADS%" (
    set "FAIL_MESSAGE=Could not create the private download folder."
    goto Failed
)

>>"%LOG%" echo.
>>"%LOG%" echo ============================================================
>>"%LOG%" echo Setup started: %DATE% %TIME%
>>"%LOG%" echo Project root: "%ROOT%"
>>"%LOG%" echo Native architecture: %NATIVE_ARCH%
>>"%LOG%" echo ============================================================

cls
echo.
echo  ==================================================
echo                 FILE CONVERTER SETUP
echo  ==================================================
echo.
echo   App-specific components stay inside this folder.
echo   It does not need administrator access.
echo.
echo      Python environment     runs the app
echo      PySide6                the app window
echo      Pillow and HEIF        convert images
echo      py7zr                  converts archives
echo      FFmpeg                 converts audio and video
echo.
echo   Keep this window open until every check passes.
echo   The first setup can take a few minutes.
echo.
echo  ==================================================

if not exist "%APP_FILE%" (
    set "FAIL_MESSAGE=File Converter.pyw is missing from this folder."
    goto Failed
)

echo.
echo   [ STEP 1 / 5 ]   Private Python environment
echo.
call :ValidateVenv
if not errorlevel 1 (
    echo      Existing environment is valid. Keeping it.
    call :Log "Existing virtual environment passed validation."
    goto PythonEnvironmentReady
)

call :FindBasePython
if defined BASE_PY goto BasePythonReady

echo      No compatible 64-bit CPython was found.
echo.
echo      This app supports Python 3.10 through 3.14.
echo      An older or unsupported version may stop it from working.
echo      Setup can install Python 3.13 for your Windows user
echo      through winget. It does not need administrator access.
echo.
where winget.exe >nul 2>nul
if errorlevel 1 (
    set "FAIL_MESSAGE=Python is missing and winget is unavailable. Install Python 3.10 through 3.14, then run setup again."
    goto Failed
)

if "%ASSUME_YES%"=="1" (
    echo      Install Python 3.13 now? [Y/N]: Y
) else (
    choice /C YN /N /M "      Install Python 3.13 now? [Y/N]: "
    if errorlevel 2 goto Cancelled
)

echo.
echo      Installing Python for the current Windows user...
winget install --id Python.Python.3.13 --exact --source winget --silent --scope user --accept-source-agreements --accept-package-agreements >>"%LOG%" 2>&1
if errorlevel 1 (
    set "FAIL_MESSAGE=Python could not be installed through winget."
    goto Failed
)
call :FindBasePython
if not defined BASE_PY (
    set "FAIL_MESSAGE=Python was installed but could not be detected. Restart Windows, then run setup again."
    goto Failed
)

:BasePythonReady
call :DescribePython "%BASE_PY%"
echo      Creating the app's private environment...
call :CreateVenv
if errorlevel 1 (
    set "FAIL_MESSAGE=The private Python environment could not be created."
    goto Failed
)

:PythonEnvironmentReady
call :ValidateVenv
if errorlevel 1 (
    set "FAIL_MESSAGE=The private Python environment did not pass validation."
    goto Failed
)
echo      Done.

echo.
echo   [ STEP 2 / 5 ]   App components
echo.
echo      Installing or updating trusted packages from PyPI...
echo      Existing components are reused whenever possible.
call :InstallPySide
if errorlevel 1 (
    set "FAIL_MESSAGE=PySide6 could not be installed or verified."
    goto Failed
)
echo      Done.

echo.
echo   [ STEP 3 / 5 ]   File formats
echo.
echo      Installing or updating trusted packages from PyPI...
echo      Existing components are reused whenever possible.
call :InstallFormats
if errorlevel 1 (
    set "FAIL_MESSAGE=Image and archive components could not be installed or verified."
    goto Failed
)
echo      Done.

echo.
echo   [ STEP 4 / 5 ]   FFmpeg and FFprobe
echo.
call :ValidateFfmpeg
if errorlevel 1 goto InstallFfmpegNow
echo      Current local copy is valid. Keeping it.
call :Log "Existing FFmpeg tools passed validation."
goto FfmpegReady

:InstallFfmpegNow
echo      Downloading the verified FFmpeg tools...
call :InstallFfmpeg
if errorlevel 1 (
    set "FAIL_MESSAGE=FFmpeg or FFprobe could not be installed or verified."
    goto Failed
)
:FfmpegReady
echo      Done.

echo.
echo   [ STEP 5 / 5 ]   Final checks
echo.
echo      Testing every required component and conversion type...
call :VerifyEverything
if errorlevel 1 (
    set "FAIL_MESSAGE=One or more final component checks failed."
    goto Failed
)
echo      Every check passed.

if exist "%DOWNLOADS%" rmdir /s /q "%DOWNLOADS%" >>"%LOG%" 2>&1
call :Log "Setup completed successfully."

echo.
echo  ==================================================
echo                ALL SET, YOU ARE READY
echo  ==================================================
echo.
echo   Double click "File Converter.pyw" to start.
echo.
echo   Run this installer again whenever you want to
echo   repair the app's private components.
echo.
echo   Setup details were saved to:
echo   "%LOG%"
echo.
call :PauseIfNeeded
exit /b 0

:Cancelled
call :Log "Setup cancelled by the user before Python installation."
echo.
echo  ==================================================
echo                     SETUP CANCELLED
echo  ==================================================
echo.
echo   Nothing was installed outside this project folder.
echo   Run Installer.bat again whenever you are ready.
echo.
call :PauseIfNeeded
exit /b 1

:Failed
if not defined FAIL_MESSAGE set "FAIL_MESSAGE=Setup stopped because an unexpected error occurred."
call :Log "ERROR: %FAIL_MESSAGE%"
echo.
echo  ==================================================
echo                     SETUP STOPPED
echo  ==================================================
echo.
echo   %FAIL_MESSAGE%
echo.
echo   No success was reported because all checks did not pass.
echo   The detailed log is here:
echo.
echo   "%LOG%"
echo.
echo   Fix the listed problem, then run Installer.bat again.
echo.
call :PauseIfNeeded
exit /b 1

:FindBasePython
set "BASE_PY="
for %%V in (3.14 3.13 3.12 3.11 3.10) do call :TryPyTag %%V
if defined BASE_PY exit /b 0
for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /V /I /C:"Microsoft\WindowsApps"') do call :TryPythonPath "%%P"
if defined BASE_PY exit /b 0
for %%P in (
    "%LocalAppData%\Programs\Python\Python314\python.exe"
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python314\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
) do call :TryPythonPath "%%~fP"
exit /b 0

:TryPyTag
if defined BASE_PY exit /b 0
set "CANDIDATE_FILE=%RUNTIME%\python-candidate.txt"
py -%~1 -I -c "import sys; print(sys.executable)" >"%CANDIDATE_FILE%" 2>nul
if errorlevel 1 exit /b 1
set "CANDIDATE="
set /p "CANDIDATE="<"%CANDIDATE_FILE%"
del /f /q "%CANDIDATE_FILE%" >nul 2>nul
if not defined CANDIDATE exit /b 1
call :TryPythonPath "%CANDIDATE%"
exit /b %ERRORLEVEL%

:TryPythonPath
if defined BASE_PY exit /b 0
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1
call :ValidatePython "%~1"
if errorlevel 1 exit /b 1
set "BASE_PY=%~1"
call :Log "Found compatible base CPython: %~1"
exit /b 0

:ValidatePython
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1
"%~1" -I -c "import sys, struct, venv, ensurepip; ok = sys.implementation.name == 'cpython' and (3, 10) <= sys.version_info[:2] < (3, 15) and struct.calcsize('P') == 8; raise SystemExit(0 if ok else 1)" >>"%LOG%" 2>&1
exit /b %ERRORLEVEL%

:DescribePython
"%~1" -I -c "import platform, sys; print('Selected CPython ' + platform.python_version() + ' at ' + sys.executable)" >>"%LOG%" 2>&1
exit /b 0

:CreateVenv
if not defined BASE_PY exit /b 1
call :ValidatePython "%BASE_PY%"
if errorlevel 1 exit /b 1
if exist "%VENV%" rmdir /s /q "%VENV%" >>"%LOG%" 2>&1
if exist "%VENV%" exit /b 1
"%BASE_PY%" -I -m venv --copies "%VENV%" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
call :ValidateVenv
exit /b %ERRORLEVEL%

:ValidateVenv
if not exist "%VENV_PY%" exit /b 1
if not exist "%VENV_PYW%" exit /b 1
"%VENV_PY%" -I -c "import sys, struct; ok = sys.implementation.name == 'cpython' and (3, 10) <= sys.version_info[:2] < (3, 15) and struct.calcsize('P') == 8 and sys.prefix != sys.base_prefix; raise SystemExit(0 if ok else 1)" >>"%LOG%" 2>&1
exit /b %ERRORLEVEL%

:InstallPySide
call :ValidateVenv
if errorlevel 1 exit /b 1
"%VENV_PY%" -I -m pip --isolated --disable-pip-version-check install --upgrade --no-cache-dir --only-binary=:all: --index-url "%PYPI_INDEX%" pip >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
"%VENV_PY%" -I -m pip --isolated --disable-pip-version-check install --upgrade --no-cache-dir --only-binary=:all: --index-url "%PYPI_INDEX%" "PySide6==%PYSIDE_VERSION%" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
call :VerifyPySide
exit /b %ERRORLEVEL%

:VerifyPySide
if not exist "%VENV_PY%" exit /b 1
"%VENV_PY%" -I -c "import PySide6; from importlib.metadata import version; assert version('PySide6') == '%PYSIDE_VERSION%'; print('PySide6=' + version('PySide6'))" >>"%LOG%" 2>&1
exit /b %ERRORLEVEL%

:InstallFormats
call :ValidateVenv
if errorlevel 1 exit /b 1
"%VENV_PY%" -I -m pip --isolated --disable-pip-version-check install --upgrade --no-cache-dir --only-binary=:all: --index-url "%PYPI_INDEX%" "Pillow==%PILLOW_VERSION%" "pillow-heif==%PILLOW_HEIF_VERSION%" "py7zr==%PY7ZR_VERSION%" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
call :VerifyFormats
exit /b %ERRORLEVEL%

:VerifyFormats
if not exist "%VENV_PY%" exit /b 1
"%VENV_PY%" -I -c "import PIL, py7zr, pillow_heif; from PIL import Image, features; from importlib.metadata import version; pillow_heif.register_heif_opener(); assert version('Pillow') == '%PILLOW_VERSION%'; assert version('pillow-heif') == '%PILLOW_HEIF_VERSION%'; assert version('py7zr') == '%PY7ZR_VERSION%'; assert features.check('webp'); assert features.check('avif'); assert Image.registered_extensions().get('.heic') == 'HEIF'; print('Pillow=' + version('Pillow')); print('pillow-heif=' + version('pillow-heif')); print('py7zr=' + version('py7zr')); print('WEBP, AVIF, and HEIC support=available')" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
"%VENV_PY%" -I -m pip --isolated --disable-pip-version-check check >>"%LOG%" 2>&1
exit /b %ERRORLEVEL%

:VerifyPackages
if not exist "%VENV_PY%" exit /b 1
"%VENV_PY%" -I -c "import PySide6, PIL, py7zr, pillow_heif; from PIL import Image, features; from importlib.metadata import version; pillow_heif.register_heif_opener(); assert version('PySide6') == '%PYSIDE_VERSION%'; assert version('Pillow') == '%PILLOW_VERSION%'; assert version('pillow-heif') == '%PILLOW_HEIF_VERSION%'; assert version('py7zr') == '%PY7ZR_VERSION%'; assert features.check('webp'); assert features.check('avif'); assert Image.registered_extensions().get('.heic') == 'HEIF'; print('PySide6=' + version('PySide6')); print('Pillow=' + version('Pillow')); print('pillow-heif=' + version('pillow-heif')); print('py7zr=' + version('py7zr')); print('WEBP, AVIF, and HEIC support=available')" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
"%VENV_PY%" -I -m pip --isolated --disable-pip-version-check check >>"%LOG%" 2>&1
exit /b %ERRORLEVEL%

:ValidateFfmpeg
if not exist "%FFMPEG_EXE%" exit /b 1
if not exist "%FFPROBE_EXE%" exit /b 1
set "FFMPEG_CHECK=%RUNTIME%\ffmpeg-check.txt"
"%FFMPEG_EXE%" -version >"%FFMPEG_CHECK%" 2>&1
if errorlevel 1 exit /b 1
findstr /B /C:"ffmpeg version %FFMPEG_VERSION%" "%FFMPEG_CHECK%" >nul
if errorlevel 1 exit /b 1
type "%FFMPEG_CHECK%" >>"%LOG%"
"%FFPROBE_EXE%" -version >"%FFMPEG_CHECK%" 2>&1
if errorlevel 1 exit /b 1
findstr /B /C:"ffprobe version %FFMPEG_VERSION%" "%FFMPEG_CHECK%" >nul
if errorlevel 1 exit /b 1
type "%FFMPEG_CHECK%" >>"%LOG%"
del /f /q "%FFMPEG_CHECK%" >nul 2>nul
exit /b 0

:InstallFfmpeg
set "FFMPEG_ARCHIVE=%DOWNLOADS%\ffmpeg-%FFMPEG_VERSION%.zip"
set "FFMPEG_EXTRACT=%RUNTIME%\ffmpeg.extract"
set "FFMPEG_NEW=%RUNTIME%\ffmpeg.new"
call :DownloadAndVerify "%FFMPEG_URL%" "%FFMPEG_ARCHIVE%" "%FFMPEG_SHA256%"
if errorlevel 1 exit /b 1
if exist "%FFMPEG_EXTRACT%" rmdir /s /q "%FFMPEG_EXTRACT%" >>"%LOG%" 2>&1
if exist "%FFMPEG_NEW%" rmdir /s /q "%FFMPEG_NEW%" >>"%LOG%" 2>&1
set "ARCHIVE_FILE=%FFMPEG_ARCHIVE%"
set "EXTRACT_DIR=%FFMPEG_EXTRACT%"
set "NEW_DIR=%FFMPEG_NEW%"
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath $env:ARCHIVE_FILE -DestinationPath $env:EXTRACT_DIR -Force; $ff=Get-ChildItem -LiteralPath $env:EXTRACT_DIR -Filter ffmpeg.exe -File -Recurse | Select-Object -First 1; $fp=Get-ChildItem -LiteralPath $env:EXTRACT_DIR -Filter ffprobe.exe -File -Recurse | Select-Object -First 1; if(-not $ff -or -not $fp){throw 'FFmpeg archive did not contain both required programs.'}; New-Item -ItemType Directory -Path $env:NEW_DIR -Force | Out-Null; Copy-Item -LiteralPath $ff.FullName -Destination (Join-Path $env:NEW_DIR 'ffmpeg.exe') -Force; Copy-Item -LiteralPath $fp.FullName -Destination (Join-Path $env:NEW_DIR 'ffprobe.exe') -Force" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
set "OLD_FFMPEG_DIR=%FFMPEG_DIR%"
set "FFMPEG_DIR=%FFMPEG_NEW%"
set "FFMPEG_EXE=%FFMPEG_NEW%\ffmpeg.exe"
set "FFPROBE_EXE=%FFMPEG_NEW%\ffprobe.exe"
call :ValidateFfmpeg
set "TEMP_VALIDATE_CODE=%ERRORLEVEL%"
set "FFMPEG_DIR=%OLD_FFMPEG_DIR%"
set "FFMPEG_EXE=%FFMPEG_DIR%\ffmpeg.exe"
set "FFPROBE_EXE=%FFMPEG_DIR%\ffprobe.exe"
if not "%TEMP_VALIDATE_CODE%"=="0" exit /b 1
call :ReplaceDirectory "%FFMPEG_NEW%" "%FFMPEG_DIR%"
if errorlevel 1 exit /b 1
if exist "%FFMPEG_EXTRACT%" rmdir /s /q "%FFMPEG_EXTRACT%" >>"%LOG%" 2>&1
del /f /q "%FFMPEG_ARCHIVE%" >nul 2>nul
call :ValidateFfmpeg
exit /b %ERRORLEVEL%

:ReplaceDirectory
set "REPLACE_NEW=%~1"
set "REPLACE_TARGET=%~2"
set "REPLACE_BACKUP=%~2.old"
if not exist "%REPLACE_NEW%" exit /b 1
if exist "%REPLACE_BACKUP%" rmdir /s /q "%REPLACE_BACKUP%" >>"%LOG%" 2>&1
if exist "%REPLACE_BACKUP%" exit /b 1
if not exist "%REPLACE_TARGET%" goto ReplaceMoveNew
move "%REPLACE_TARGET%" "%REPLACE_BACKUP%" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1

:ReplaceMoveNew
move "%REPLACE_NEW%" "%REPLACE_TARGET%" >>"%LOG%" 2>&1
if errorlevel 1 goto ReplaceRollback
if exist "%REPLACE_BACKUP%" rmdir /s /q "%REPLACE_BACKUP%" >>"%LOG%" 2>&1
exit /b 0

:ReplaceRollback
if exist "%REPLACE_TARGET%" rmdir /s /q "%REPLACE_TARGET%" >>"%LOG%" 2>&1
if exist "%REPLACE_BACKUP%" move "%REPLACE_BACKUP%" "%REPLACE_TARGET%" >>"%LOG%" 2>&1
exit /b 1

:DownloadAndVerify
set "DL_URL=%~1"
set "DL_FILE=%~2"
set "DL_HASH=%~3"
if exist "%DL_FILE%" del /f /q "%DL_FILE%" >nul 2>nul
call :Log "Downloading: %DL_URL%"
where curl.exe >nul 2>nul
if errorlevel 1 goto DownloadWithPowerShell
curl.exe --fail --location --silent --show-error --retry 3 --retry-delay 2 --connect-timeout 30 --proto "=https" --proto-redir "=https" -o "%DL_FILE%" "%DL_URL%" >>"%LOG%" 2>&1
if not errorlevel 1 goto VerifyDownload
call :Log "curl failed; retrying with PowerShell."

:DownloadWithPowerShell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri $env:DL_URL -OutFile $env:DL_FILE" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1

:VerifyDownload
if not exist "%DL_FILE%" exit /b 1
call :VerifyFileHash "%DL_FILE%" "%DL_HASH%"
exit /b %ERRORLEVEL%

:VerifyFileHash
set "VERIFY_FILE=%~1"
set "VERIFY_HASH=%~2"
if not exist "%VERIFY_FILE%" exit /b 1
if not defined VERIFY_HASH exit /b 1
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $stream=[IO.File]::OpenRead($env:VERIFY_FILE); try{$sha=[Security.Cryptography.SHA256]::Create(); try{$actual=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','')} finally{$sha.Dispose()}} finally{$stream.Dispose()}; if($actual -ne $env:VERIFY_HASH){throw ('SHA-256 mismatch. Expected {0}, got {1}' -f $env:VERIFY_HASH,$actual)}; Write-Output ('Verified SHA-256: ' + $actual)" >>"%LOG%" 2>&1
exit /b %ERRORLEVEL%

:VerifyEverything
call :ValidateVenv
if errorlevel 1 exit /b 1
call :VerifyPackages
if errorlevel 1 exit /b 1
call :ValidateFfmpeg
if errorlevel 1 exit /b 1
"%VENV_PY%" -I -c "from pathlib import Path; app=Path(r'%APP_FILE%'); compile(app.read_text(encoding='utf-8'), str(app), 'exec'); print('Application source compiled successfully.')" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
call :RunConversionChecks
exit /b %ERRORLEVEL%

:RunConversionChecks
set "CHECK_DIR=%RUNTIME%\checks"
if exist "%CHECK_DIR%" rmdir /s /q "%CHECK_DIR%" >>"%LOG%" 2>&1
mkdir "%CHECK_DIR%" >>"%LOG%" 2>&1
if not exist "%CHECK_DIR%" exit /b 1
"%VENV_PY%" -I "%APP_FILE%" --self-test "%CHECK_DIR%" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
if not exist "%CHECK_DIR%\check.jpg" exit /b 1
if not exist "%CHECK_DIR%\check.webp" exit /b 1
if not exist "%CHECK_DIR%\check.bmp" exit /b 1
if not exist "%CHECK_DIR%\check.ico" exit /b 1
if not exist "%CHECK_DIR%\check.gif" exit /b 1
if not exist "%CHECK_DIR%\check.tiff" exit /b 1
if not exist "%CHECK_DIR%\check.tga" exit /b 1
if not exist "%CHECK_DIR%\check.avif" exit /b 1
if not exist "%CHECK_DIR%\check.heic" exit /b 1
if not exist "%CHECK_DIR%\animated-output.webp" exit /b 1
if not exist "%CHECK_DIR%\audio.mp3" exit /b 1
if not exist "%CHECK_DIR%\audio.flac" exit /b 1
if not exist "%CHECK_DIR%\audio-copy.m4a" exit /b 1
if not exist "%CHECK_DIR%\video.webm" exit /b 1
if not exist "%CHECK_DIR%\video.avi" exit /b 1
if not exist "%CHECK_DIR%\archive.7z" exit /b 1
if not exist "%CHECK_DIR%\archive.tar.gz" exit /b 1
if not exist "%CHECK_DIR%\archive.gz" exit /b 1
if not exist "%CHECK_DIR%\selected-items.zip" exit /b 1
if not exist "%CHECK_DIR%\selected-file.gz" exit /b 1
if not exist "%CHECK_DIR%\check.cmd" exit /b 1
if not exist "%CHECK_DIR%\check.pyw" exit /b 1
rmdir /s /q "%CHECK_DIR%" >>"%LOG%" 2>&1
if exist "%CHECK_DIR%" exit /b 1
exit /b 0

:Log
>>"%LOG%" echo [%DATE% %TIME%] %~1
exit /b 0

:PauseIfNeeded
if "%NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0
