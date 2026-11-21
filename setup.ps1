# One-time project setup on Windows. Run from the repo root:  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = 'Stop'
if (-not (Test-Path .git)) { git init }
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e "./server[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Write-Host "Done. Add your Gnani API key to .env, then see README.md to start the server."
