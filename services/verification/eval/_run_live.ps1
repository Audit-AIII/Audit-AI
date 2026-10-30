# Throwaway helper (do not commit). Usage: .\eval\_run_live.ps1 smoke | run1 | run2 | run3
param([Parameter(Mandatory=$true)][ValidateSet("smoke","run1","run2","run3")][string]$Step)
$ErrorActionPreference = "Continue"
if (-not $env:OPENROUTER_API_KEY -or $env:OPENROUTER_API_KEY.Length -lt 60) { Write-Host "KEY NOT SET in this window. Set it first."; exit 1 }
$env:INKLOOM_LLM_MODELS = "openai/gpt-4o-mini"
$env:INKLOOM_LLM_MIN_INTERVAL_SECONDS = "0"
$env:INKLOOM_LLM_MAX_RETRIES = "3"
$py = ".\.venv\Scripts\python"
$log = Join-Path $env:TEMP "live-$Step.txt"
if ($Step -eq "smoke") { $extra = @("--dataset","eval\dev_only.jsonl") }
else { New-Item -ItemType Directory -Force eval\cassettes | Out-Null; $extra = @("--record","eval\cassettes\final-$Step.jsonl") }
Write-Host "Running $Step with $env:INKLOOM_LLM_MODELS ... (a few minutes, do not close)"
& $py eval\run_eval.py --verdicts openrouter --pipeline full @extra 2>&1 | Tee-Object -FilePath $log | Select-Object -Last 15
Write-Host "---- newest reports ----"
Get-ChildItem eval\reports -Filter *.summary.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1 Name, LastWriteTime | Format-List
Write-Host "Done. Tell Claude: finished $Step"
