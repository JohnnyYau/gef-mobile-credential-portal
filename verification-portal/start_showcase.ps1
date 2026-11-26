# start_showcase.ps1 — one command for demo day (U26)
#
# Boots the portal, opens a public Cloudflare quick tunnel, points the portal
# at that public URL, and opens the stage screen in the default browser.
#
# Why this exists: on demo day the three things that go wrong are (1) the
# portal is not running, (2) the tunnel URL changed and PUBLIC_BASE_URL still
# says 127.0.0.1 (so the QR on screen is unscannable), (3) the token is not
# configured, so the stage can issue nothing. This script fixes all three
# in the only order that works.

param(
    [string]$AdminToken = "demo-staff-token",
    [string]$IssuerToken = "demo-issuer-token",
    [string]$CapabilitySecret = "showcase-capability-secret-2026",
    [int]$Port = 8013,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$py = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv not found: $py" }
$cf = Join-Path $env:LOCALAPPDATA "cloudflared\cloudflared.exe"
if (-not (Test-Path $cf)) { throw "cloudflared not found: $cf (download it first)" }

# ---- 1. free the port -----------------------------------------------------
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# ---- 2. public URL (retry: quick tunnels are rate limited) -----------------
$url = $null
for ($attempt = 1; $attempt -le 6; $attempt++) {
    $out = Join-Path $env:TEMP "showcase-cf.out"
    $err = Join-Path $env:TEMP "showcase-cf.err"
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    Start-Process -FilePath $cf -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate" `
        -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        $text = (Get-Content $out, $err -ErrorAction SilentlyContinue) -join "`n"
        $m = [regex]::Match($text, 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($m.Success) { $url = $m.Value; break }
        if ($text -match "status 429") { break }
    }
    if ($url) { break }
    Write-Host "tunnel attempt $attempt blocked, waiting 30s..." -ForegroundColor Yellow
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 30
}
if (-not $url) { throw "could not get a public URL (Cloudflare quick tunnel rate limited). Try again in a few minutes." }

# ---- 3. portal pointed at that URL ---------------------------------------
$env:ADMIN_TOKEN = $AdminToken
$env:ISSUER_TOKEN = $IssuerToken
$env:CAPABILITY_SECRET = $CapabilitySecret
$env:PUBLIC_BASE_URL = $url
$env:PUBLIC_MODE = "0"
$env:DEMO_OPEN = "1"
# cloudflared connects from 127.0.0.1, so that peer is the trusted proxy: the
# limiter then keys on the real visitor address instead of one shared bucket.
$env:TRUSTED_PROXIES = "127.0.0.1"
Remove-Item Env:\CHAIN_DIR -ErrorAction SilentlyContinue

$log = Join-Path $env:TEMP "showcase-portal.out"
$errlog = Join-Path $env:TEMP "showcase-portal.err"
Start-Process -FilePath $py `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port", "--no-proxy-headers" `
    -RedirectStandardOutput $log -RedirectStandardError $errlog -WindowStyle Hidden

$ready = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$Port/healthz" -TimeoutSec 4 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
if (-not $ready) { throw "portal did not become ready; see $errlog" }

# ---- 4. prove it from the outside, then open the stage --------------------
try {
    $pub = Invoke-WebRequest "$url/healthz" -TimeoutSec 25 -UseBasicParsing
    Write-Host "public healthz: $($pub.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "public check failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

# WriteAllText, not Set-Content -Encoding UTF8: under Windows PowerShell 5.1
# that switch prepends a BOM, and every later reader of this file then carries a
# zero-width character in front of the URL.
[IO.File]::WriteAllText((Join-Path $here "showcase-url.txt"), $url)

Write-Host ""
Write-Host "  PUBLIC  $url" -ForegroundColor Cyan
Write-Host "  LOCAL   http://127.0.0.1:$Port/showtime?token=$AdminToken" -ForegroundColor Cyan
Write-Host "  QR on the stage points at the PUBLIC address." -ForegroundColor DarkGray
Write-Host "  Keep this window's processes alive: closing the laptop lid kills the tunnel." -ForegroundColor DarkGray

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$Port/showtime?token=$AdminToken"
}

# ---- 6. say whether the show is actually ready ------------------------------
# Nine things that break silently (dead tunnel, drifted demo hashes, a QR that
# points at the wrong video, a preview file where the print file should be).
# Green here means the booth is safe; red names the one thing to fix.
Write-Host ""
& $py (Join-Path $here "scripts\preflight.py")
if ($LASTEXITCODE -ne 0) {
    Write-Host "  preflight failed - fix the lines above before opening the booth." -ForegroundColor Yellow
}
