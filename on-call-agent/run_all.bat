@echo off
setlocal

cd /d "%~dp0"

if "%HOST%"=="" set "HOST=127.0.0.1"
if "%API_GATEWAY_PORT%"=="" set "API_GATEWAY_PORT=8000"
if "%V1_PORT%"=="" set "V1_PORT=8001"
if "%V2_PORT%"=="" set "V2_PORT=8002"
if "%V3_PORT%"=="" set "V3_PORT=8003"
if "%V3_WS_PORT%"=="" set "V3_WS_PORT=8004"
if "%WEBUI_PORT%"=="" set "WEBUI_PORT=4173"
if "%DEMO_DIR%"=="" set "DEMO_DIR=..\coding-exam\question-1\data"
if "%HF_ENDPOINT%"=="" set "HF_ENDPOINT=https://huggingface.co"
if "%HF_HUB_DISABLE_XET%"=="" set "HF_HUB_DISABLE_XET=1"
if "%ON_CALL_AGENT_CHROMA_DIR%"=="" set "ON_CALL_AGENT_CHROMA_DIR=.\database\chroma"

if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

where uv >nul 2>nul
if errorlevel 1 (
  echo uv is required. Install uv first, then rerun this script.
  exit /b 1
)

echo Syncing Python environment...
uv sync
if errorlevel 1 exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=@(%API_GATEWAY_PORT%,%V1_PORT%,%V2_PORT%,%V3_PORT%,%V3_WS_PORT%,%WEBUI_PORT%); foreach($p in $ports){ $c=New-Object Net.Sockets.TcpClient; try { $iar=$c.BeginConnect('%HOST%',$p,$null,$null); if($iar.AsyncWaitHandle.WaitOne(200,$false) -and $c.Connected){ Write-Error ('Port '+$p+' is already in use on %HOST%'); exit 1 } } finally { $c.Close() } }"
if errorlevel 1 exit /b 1

echo Starting v1 on http://%HOST%:%V1_PORT%
start "on-call-agent v1" cmd /k "cd /d ""%CD%"" && uv run python v1\server.py --host %HOST% --port %V1_PORT% --import-demo --demo-dir ""%DEMO_DIR%"""

echo Starting v2 on http://%HOST%:%V2_PORT%
start "on-call-agent v2" cmd /k "cd /d ""%CD%"" && uv run python v2\server.py --host %HOST% --port %V2_PORT% --import-demo --demo-dir ""%DEMO_DIR%"""

echo Starting v3 on http://%HOST%:%V3_PORT%
start "on-call-agent v3" cmd /k "cd /d ""%CD%"" && uv run python v3\server.py --host %HOST% --port %V3_PORT% --ws-port %V3_WS_PORT% --data-dir ""%DEMO_DIR%"""

echo Starting API gateway on http://%HOST%:%API_GATEWAY_PORT%
start "on-call-agent gateway" cmd /k "cd /d ""%CD%"" && uv run python dev_gateway.py --host %HOST% --port %API_GATEWAY_PORT% --frontend-url http://%HOST%:%WEBUI_PORT%/"

echo Starting web UI on http://%HOST%:%WEBUI_PORT%
start "on-call-agent webui" cmd /k "cd /d ""%CD%"" && uv run python -m http.server %WEBUI_PORT% --bind %HOST% --directory webui"

set "FRONTEND_URL=http://%HOST%:%WEBUI_PORT%/#v1"
echo.
echo All services are starting.
echo Frontend: %FRONTEND_URL%
echo Gateway:  http://%HOST%:%API_GATEWAY_PORT%
echo.
echo Close the opened service windows to stop the services.
if not "%NO_OPEN%"=="1" start "" "%FRONTEND_URL%"

endlocal
