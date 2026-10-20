@echo off
rem Launcher for Picture Postcard Manager on Windows (Refs #67).
rem
rem Runs the documented "docker run" command for the published container
rem image with the persistent "postcard-data" volume mounted at /data, waits
rem until the application's health endpoint answers, and then opens the
rem browser. Running it again reuses the existing container and volume; no
rem data is ever deleted.
rem
rem Configuration (environment variables, all optional):
rem   PPM_PORT          Host port to publish on 127.0.0.1 (default: 8000)
rem   PPM_IMAGE_TAG     Image tag to run (default: latest)
rem   PPM_WAIT_SECONDS  Health-endpoint timeout in seconds (default: 90)

setlocal EnableExtensions

set "CONTAINER=picture-postcard-manager"
set "VOLUME=postcard-data"
if not defined PPM_IMAGE_TAG set "PPM_IMAGE_TAG=latest"
set "IMAGE=ghcr.io/schmidt-software/picture-postcard-manager:%PPM_IMAGE_TAG%"
if not defined PPM_PORT set "PPM_PORT=8000"
if not defined PPM_WAIT_SECONDS set "PPM_WAIT_SECONDS=90"
set "URL=http://127.0.0.1:%PPM_PORT%"

where docker >nul 2>&1
if errorlevel 1 (
    echo Error: Docker is not installed or not on PATH. Install Docker Desktop and try again.>&2
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo Error: the Docker daemon is not running. Start Docker Desktop and try again.>&2
    exit /b 1
)

rem The data volume holds the SQLite database (/data/postcards.db) and the
rem uploaded images (/data/images/). Creating it explicitly makes reruns
rem obviously safe: an existing volume and its contents are never touched.
docker volume create "%VOLUME%" >nul
if errorlevel 1 (
    echo Error: cannot create the Docker volume: %VOLUME%>&2
    exit /b 1
)

set "STATE=missing"
for /f "usebackq delims=" %%S in (`docker container inspect --format "{{.State.Running}}" "%CONTAINER%" 2^>nul`) do set "STATE=%%S"

if "%STATE%"=="true" (
    echo Container %CONTAINER% is already running; reusing it.
    goto :wait_healthy
)
if "%STATE%"=="false" (
    echo Starting the existing container %CONTAINER% ^(all data is kept^).
    docker start "%CONTAINER%" >nul
    if errorlevel 1 (
        echo Error: could not start the existing container. Check: docker logs %CONTAINER%>&2
        exit /b 1
    )
    goto :wait_healthy
)

echo Creating container %CONTAINER% from %IMAGE%.
docker run -d --name "%CONTAINER%" -p "127.0.0.1:%PPM_PORT%:8000" -v "%VOLUME%:/data" "%IMAGE%" >nul
if errorlevel 1 (
    echo Error: docker run failed; see the Docker message above.>&2
    exit /b 1
)

:wait_healthy
echo Waiting up to %PPM_WAIT_SECONDS% seconds for %URL%/api/health ...
set /a ELAPSED=0

:health_loop
rem curl.exe ships with Windows 10 1803+ and Windows 11.
curl.exe -fsS --max-time 2 "%URL%/api/health" >nul 2>&1
if not errorlevel 1 goto :ready

set "RUNNING=false"
for /f "usebackq delims=" %%S in (`docker container inspect --format "{{.State.Running}}" "%CONTAINER%" 2^>nul`) do set "RUNNING=%%S"
if not "%RUNNING%"=="true" (
    echo Error: the container stopped unexpectedly. Check: docker logs %CONTAINER%>&2
    exit /b 1
)
if %ELAPSED% geq %PPM_WAIT_SECONDS% (
    echo Error: the application did not become healthy within %PPM_WAIT_SECONDS% seconds.>&2
    echo If you changed PPM_PORT after the container was created, the old container>&2
    echo still publishes the old port. Stop and remove the container ^(the data>&2
    echo volume is kept^), then run this script again. Check: docker logs %CONTAINER%>&2
    exit /b 1
)
rem "timeout" needs an interactive console; ping works everywhere and waits ~1s.
ping -n 2 127.0.0.1 >nul
set /a ELAPSED+=1
goto :health_loop

:ready
echo The application is ready: %URL%
start "" "%URL%"
endlocal
exit /b 0
