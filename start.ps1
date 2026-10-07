# Windows: ein Befehl bis zum laufenden Dashboard.
#   powershell -ExecutionPolicy Bypass -File start.ps1
# Legt .env mit einem zufälligen Dashboard-Passwort an (falls sie fehlt), baut den Container und startet ihn. Braucht Docker Desktop (siehe SERVER_ANLEITUNG.md, Abschnitt Windows 10).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker fehlt. Installiere Docker Desktop (docker.com), starte es einmal und führe dieses Skript erneut aus."
    exit 1
}
if (-not (Test-Path ".env")) {
    $pw = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    $text = [IO.File]::ReadAllText((Join-Path $PWD ".env.example"), [Text.Encoding]::UTF8) -replace '(?m)^DASHBOARD_PASSWORD=.*$', "DASHBOARD_PASSWORD=$pw"
    [IO.File]::WriteAllText((Join-Path $PWD ".env"), $text, (New-Object Text.UTF8Encoding $false))   # UTF-8 ohne BOM
    Write-Host "Dashboard-Passwort erzeugt und in .env gespeichert:  $pw"
} else {
    Write-Host ".env vorhanden, das Passwort bleibt wie es ist."
}
New-Item -ItemType Directory -Force state, data, logs | Out-Null
try { git log -1 --format='%h %s (%cd)' --date=short | Out-File -Encoding utf8 state/version.txt } catch {}   # Stand der Software für den Statusbericht im Dashboard
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Write-Host "Docker meldet einen Fehler. Läuft Docker Desktop (Wal-Symbol unten rechts)?"; exit 1 }
Write-Host ""
Write-Host "Fertig. Das Dashboard läuft auf http://localhost:8080 (vom Handy: Tailscale, siehe SERVER_ANLEITUNG.md)."
Write-Host "Weiter im Dashboard, Tab Einstellungen: Claude-Token, Planspiel-Login, dann Tab Steuerung: Wertpapierliste laden, Selbsttest, Start."
