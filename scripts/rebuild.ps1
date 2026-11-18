# Rebuild data and models from the public sources, then load MySQL.
# Run from the project root in PowerShell with the virtual environment active:
#   .\scripts\rebuild.ps1           full rebuild (download, process, tune, train, index)
#   .\scripts\rebuild.ps1 -NoTune   reuse reports\best_params.json instead of running Optuna
param([switch]$NoTune)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Step($label, [string[]]$cmd) {
    Write-Host "==> $label"
    & python @cmd
    if ($LASTEXITCODE -ne 0) { throw "$label failed" }
}

Step "download raw data" @("scripts/download_data.py")
Step "ingest" @("-m", "ml.ingest")
Step "preprocess" @("-m", "ml.preprocess")
Step "split" @("-m", "ml.split")
if (-not $NoTune) { Step "tune (Optuna)" @("-m", "ml.tune") }
Step "evaluate" @("-m", "ml.evaluate")
Step "train" @("-m", "ml.train")
Step "build FAISS index" @("-m", "ml.build_index")
Step "load catalogue into MySQL" @("-m", "backend.scripts.load_catalogue")
Step "seed demo accounts" @("-m", "backend.scripts.seed_demo")
Write-Host "Rebuild finished. Start the API with: uvicorn backend.app.main:app --port 8000"
