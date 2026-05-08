@echo off
chcp 65001 >nul

echo ==========================================
echo Starting NATS Exporter, Prometheus, Grafana
echo ==========================================

set PROM_CONFIG=C:\Users\yuhaoran\Desktop\prometheus-3.11.3.windows-amd64\prometheus.yml
set GRAFANA_HOME=C:\Users\yuhaoran\Desktop\grafana-13.0.1
set GRAFANA_CONFIG=C:\Users\yuhaoran\Desktop\grafana-13.0.1\conf\custom.ini

echo.
echo [0/5] Checking remote NATS monitoring...
call :WAIT_PORT 10.169.109.132 8222 "Remote NATS monitoring" 60

echo.
echo [1/5] Starting prometheus-nats-exporter for remote server...
start "NATS Server Exporter" cmd /k "prometheus-nats-exporter -port 7777 -varz -jsz=all http://10.169.109.132:8222"

call :WAIT_PORT 127.0.0.1 7777 "NATS Server Exporter" 60

echo.
echo [2/5] Checking local leaf node monitoring...
call :WAIT_PORT 192.168.198.128 8222 "Local Leaf Node monitoring" 60

echo.
echo [2/5] Starting prometheus-nats-exporter for local leaf node...
start "NATS Leaf Node Exporter" cmd /k "prometheus-nats-exporter -port 7778 -varz -jsz=all http://192.168.198.128:8222"

call :WAIT_PORT 127.0.0.1 7778 "NATS Leaf Node Exporter" 60

echo.
echo [3/5] Starting Prometheus...
start "Prometheus" cmd /k "prometheus --config.file=""%PROM_CONFIG%"""

call :WAIT_PORT 127.0.0.1 9090 "Prometheus" 60

echo.
echo [4/5] Starting Grafana...
start "Grafana" cmd /k "grafana server --config=""%GRAFANA_CONFIG%"" --homepath=""%GRAFANA_HOME%"""

call :WAIT_PORT 127.0.0.1 3000 "Grafana" 90

echo.
echo [5/5] Opening Grafana in browser...
start "" "http://localhost:3000"

echo.
echo All commands have been started.
exit /b 0


:WAIT_PORT
set WAIT_HOST=%~1
set WAIT_PORT=%~2
set WAIT_NAME=%~3
set WAIT_RETRY=%~4

echo Waiting for %WAIT_NAME% on %WAIT_HOST%:%WAIT_PORT% ...

for /l %%i in (1,1,%WAIT_RETRY%) do (
    powershell -NoProfile -Command "if ((Test-NetConnection -ComputerName '%WAIT_HOST%' -Port %WAIT_PORT% -InformationLevel Quiet)) { exit 0 } else { exit 1 }" >nul 2>nul

    if not errorlevel 1 (
        echo %WAIT_NAME% is ready.
        exit /b 0
    )

    echo Waiting for %WAIT_NAME% ... %%i/%WAIT_RETRY%
    timeout /t 2 /nobreak >nul
)

echo WARNING: %WAIT_NAME% is not ready after waiting.
exit /b 1
