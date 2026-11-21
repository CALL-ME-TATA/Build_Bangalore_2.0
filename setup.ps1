# One-time project setup on Windows. Run from the repo root:  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = 'Stop'
if (-not (Test-Path .git)) { git init }
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e "./server[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location frontend
    npm ci
    npm run build
    Pop-Location
} else {
    Write-Host "Node was not found. The server will serve the earlier client in web/. For the main web app, install Node and run 'npm ci' and 'npm run build' in frontend/."
}
Write-Host "Done. Add your Gnani API key to .env, then see README.md to start the server."
