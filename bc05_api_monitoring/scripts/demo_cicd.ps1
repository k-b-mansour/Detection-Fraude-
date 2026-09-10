# BC05 — Démo CI/CD locale (équivalent du pipeline GitHub Actions)
#
# Usage (depuis la racine du dépôt) :
#   powershell -ExecutionPolicy Bypass -File bc05_api_monitoring\scripts\demo_cicd.ps1
#
# Étapes :
#   1. pytest (job "test")
#   2. docker build + run + /health (job "build-image")
#   3. laisse l'API sur http://localhost:8001 (Swagger : /docs)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  BC05 — Demo CI/CD locale" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Racine : $Root"
Write-Host ""

# --- Prérequis ---
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python introuvable dans le PATH."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker introuvable. Demarre Docker Desktop puis relance."
}

$Model = Join-Path $Root "bc03_modeles_supervises\models\modele_lightgbm.joblib"
if (-not (Test-Path $Model)) {
    throw "Modele manquant : $Model (executer d'abord le notebook BC03)."
}

# --- Job 1 : tests (comme GitHub Actions) ---
Write-Host "[1/3] Tests pytest (job CI 'test')..." -ForegroundColor Yellow
python -m pip install -q -r bc05_api_monitoring\requirements-api.txt
python -m pip install -q pytest==9.1.1 httpx==0.28.1
python -m pytest bc05_api_monitoring\tests\ -v
if ($LASTEXITCODE -ne 0) {
    throw "Tests echoues — arret (comme needs: test dans le workflow)."
}
Write-Host "OK — tests verts." -ForegroundColor Green
Write-Host ""

# --- Job 2 : image Docker ---
$Image = "fraud-api:demo"
$Container = "fraud-api-demo"

Write-Host "[2/3] Build Docker (job CI 'build-image')..." -ForegroundColor Yellow
docker rm -f $Container 2>$null | Out-Null
docker build -f bc05_api_monitoring\Dockerfile -t $Image .
if ($LASTEXITCODE -ne 0) {
    throw "docker build a echoue."
}
Write-Host "OK — image construite : $Image" -ForegroundColor Green
Write-Host ""

# --- Job 3 : demarrage + /health ---
Write-Host "[3/3] Demarrage conteneur + verification /health..." -ForegroundColor Yellow
docker run -d --name $Container -p 8001:8000 $Image | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "docker run a echoue."
}

$ok = $false
for ($i = 1; $i -le 20; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8001/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) {
            Write-Host "OK — /health repond :" -ForegroundColor Green
            Write-Host $r.Content
            $ok = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ok) {
    Write-Host "Logs du conteneur :" -ForegroundColor Red
    docker logs $Container
    throw "L'API n'a pas repondu sur /health."
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Demo prete" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sante   : http://localhost:8001/health"
Write-Host "  Swagger : http://localhost:8001/docs"
Write-Host "  Stop    : docker rm -f $Container"
Write-Host ""
