# Turnkey training for the Sensei-Compressor (Windows / RTX 4080).
#
#   ./run.ps1            # full run: venv + deps + data + train (3 epochs)
#   ./run.ps1 -Smoke     # fast end-to-end check (small data, 1 epoch)
#   ./run.ps1 -SkipInstall
#
# Keeps the HF cache + checkpoints on the G: SSD. Install the CUDA build of
# torch from https://pytorch.org if `torch.cuda.is_available()` is False.
param(
    [switch]$Smoke,
    [switch]$SkipInstall
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$env:HF_HOME = "G:/Projects/Sensei/.hf-cache"
$venv = "G:/Projects/Sensei/training/.venv-train"

if (-not (Test-Path "$venv/Scripts/python.exe")) {
    Write-Host "Creating training venv at $venv ..."
    python -m venv $venv
}
$py = "$venv/Scripts/python.exe"

if (-not $SkipInstall) {
    Write-Host "Installing training deps (this pulls torch — large) ..."
    & $py -m pip install --upgrade pip | Out-Null
    & $py -m pip install -r requirements.txt
}

& $py -c "import torch; print('CUDA available:', torch.cuda.is_available(), '| device:', (torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'))"

$cfg = "config.yaml"
if ($Smoke) {
    Write-Host "SMOKE mode: tiny dataset, 1 epoch."
    $cfg = "config.smoke.yaml"
    (Get-Content config.yaml) `
        -replace 'num_synthetic: .*', 'num_synthetic: 200' `
        -replace 'epochs: .*', 'epochs: 1' `
        -replace 'sensei-compressor', 'sensei-compressor-smoke' |
        Set-Content $cfg -Encoding utf8
}

$env:PYTHONPATH = "../../backend"
Write-Host "`n[1/2] Building dataset ..."
& $py prepare_data.py --config $cfg
Write-Host "`n[2/2] Training ..."
& $py train.py --config $cfg

Write-Host "`nDone. Try it:"
Write-Host "  `$env:PYTHONPATH='../../backend'; & '$py' infer.py --config $cfg --text 'Basically, in order to actually get started you will need to install everything.'"
