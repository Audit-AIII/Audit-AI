# Local helper (do not commit): starts the database, the backend (port 18000) and the website.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
docker start inkloom-pg | Out-Null
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\services\api'; py -m uvicorn inkloom_api.main:app --port 18000"
Start-Sleep -Seconds 6
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\audit-ai-final\frontend'; npm run dev"
Write-Host "Started. Open http://localhost:3000/app/draft in about 20 seconds."
