@echo off
setlocal EnableExtensions

rem =====================================================================
rem  Mousetrack environment setup
rem
rem  Usage:   setup_mousetrack.bat [env_name] [/nopause]
rem             env_name  conda environment to create/update (default: mousetrack)
rem             /nopause  do not wait for a key press at the end
rem
rem  Safe to run again: an existing environment is updated, not recreated,
rem  and steps that are already done are skipped.
rem
rem  Needs: Anaconda / Miniconda, internet access for PyPI, and the FLIR
rem  Spinnaker Python wheel (spinnaker_python-*-cp312-*-win_amd64.whl).
rem  The wheel is not on PyPI. It is looked for, in this order, at:
rem     1. the path in the SPINNAKER_WHEEL environment variable
rem     2. the PySpin folder next to this script, then this folder
rem     3. %USERPROFILE%\PySpin
rem     4. the Spinnaker SDK install folder (Teledyne / FLIR Systems)
rem =====================================================================

cd /d "%~dp0"

set "ENV_NAME=mousetrack"
set "NOPAUSE="

for %%A in (%*) do call :parse_arg "%%~A"

set "RUN=conda run -n %ENV_NAME% --no-capture-output"
set "STATUS=0"

echo =====================================
echo  Mousetrack setup  [environment: %ENV_NAME%]
echo =====================================

rem ---------------------------------------------------------------------
rem  1. conda
rem ---------------------------------------------------------------------

where conda >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: conda was not found on PATH.
    echo Open "Anaconda Prompt" and run this script from there, or install
    echo Miniconda and tick "Add to PATH".
    set "STATUS=1"
    goto :finish
)

rem ---------------------------------------------------------------------
rem  2. environment
rem ---------------------------------------------------------------------

echo.
echo [1/4] Conda environment

conda env list | findstr /b /i /c:"%ENV_NAME% " >nul
if errorlevel 1 (
    echo Creating environment %ENV_NAME% with Python 3.12 ...
    call conda create -n %ENV_NAME% python=3.12 -y
    if errorlevel 1 (
        echo ERROR: could not create the environment.
        set "STATUS=1"
        goto :finish
    )
) else (
    echo Environment %ENV_NAME% already exists - updating it.
)

rem ---------------------------------------------------------------------
rem  3. packages from PyPI
rem ---------------------------------------------------------------------

echo.
echo [2/4] Packages from requirements.txt

if not exist "%~dp0requirements.txt" (
    echo ERROR: requirements.txt not found next to this script.
    set "STATUS=1"
    goto :finish
)

call %RUN% python -m pip install --upgrade pip
call %RUN% python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo ERROR: package installation failed.
    set "STATUS=1"
    goto :finish
)

rem ---------------------------------------------------------------------
rem  4. FLIR PySpin (local wheel)
rem ---------------------------------------------------------------------

echo.
echo [3/4] FLIR PySpin

call %RUN% python -c "import PySpin" >nul 2>&1
if not errorlevel 1 (
    echo PySpin is already installed.
    goto :verify
)

set "WHEEL="

if defined SPINNAKER_WHEEL if exist "%SPINNAKER_WHEEL%" set "WHEEL=%SPINNAKER_WHEEL%"

if not defined WHEEL for %%D in (
    "%~dp0PySpin"
    "%~dp0."
    "%USERPROFILE%\PySpin"
    "%ProgramFiles%\Teledyne\Spinnaker\python"
    "%ProgramFiles%\FLIR Systems\Spinnaker\python"
) do (
    if not defined WHEEL for %%F in ("%%~D\spinnaker_python-*-cp312-*-win_amd64.whl") do set "WHEEL=%%~fF"
)

if not defined WHEEL goto :no_wheel

echo Installing %WHEEL%
call %RUN% python -m pip install "%WHEEL%"
if errorlevel 1 (
    echo ERROR: the Spinnaker wheel failed to install.
    set "STATUS=1"
)
goto :verify

:no_wheel
echo.
echo WARNING: the Spinnaker Python wheel was not found, so PySpin is NOT installed.
echo   1. Download the Spinnaker SDK for Windows from Teledyne FLIR
echo      (the Python package for Python 3.12, file name
echo      spinnaker_python-...-cp312-cp312-win_amd64.whl).
echo   2. Put the .whl in %USERPROFILE%\PySpin, or in the PySpin folder here,
echo      or set SPINNAKER_WHEEL to its full path.
echo   3. Run this script again.
set "STATUS=1"

rem ---------------------------------------------------------------------
rem  5. verify
rem ---------------------------------------------------------------------

:verify
echo.
echo [4/4] Verifying the installation
call %RUN% python "%~dp0check_install.py"
if errorlevel 1 set "STATUS=1"

:finish
echo.
if "%STATUS%"=="0" (
    echo =====================================
    echo  Setup finished successfully.
    echo =====================================
    echo.
    echo Start the app with:
    echo.
    echo     conda activate %ENV_NAME%
    echo     python main.py
) else (
    echo =====================================
    echo  Setup did NOT complete - see the messages above.
    echo =====================================
)
echo.

if not defined NOPAUSE pause
exit /b %STATUS%

:parse_arg
if /i "%~1"=="/nopause" (
    set "NOPAUSE=1"
) else (
    set "ENV_NAME=%~1"
)
exit /b 0
