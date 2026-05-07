@echo off
chcp 65001 >nul

echo ==========================================
echo Starting NATS Exporter, Prometheus, Grafana
echo ==========================================

echo.
echo [1/4] Starting prometheus-nats-exporter...
start "NATS Exporter" cmd /k "prometheus-nats-exporter -varz -jsz=all http://10.169.109.132:8222"

timeout /t 2 /nobreak >nul

echo.
echo [2/4] Starting Prometheus...
start "Prometheus" cmd /k "prometheus --config.file=C:\Users\yuhaoran\Desktop\prometheus-3.11.3.windows-amd64\prometheus.yml"

timeout /t 3 /nobreak >nul

echo.
echo [3/4] Starting Grafana...
start "Grafana" cmd /k "grafana server --config=C:\Users\yuhaoran\Desktop\grafana-13.0.1\conf\custom.ini --homepath=C:\Users\yuhaoran\Desktop\grafana-13.0.1"

timeout /t 5 /nobreak >nul

echo.
echo [4/4] Opening Grafana in browser...
start "" "http://localhost:3000"

echo.
echo All commands have been started.
exit
