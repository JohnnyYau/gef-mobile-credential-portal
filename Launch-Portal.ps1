# Launch-Portal.ps1 - double-click launcher for the P14 booth demo.
# Wraps verification-portal\start_showcase.ps1 (server + tunnel + pretest) in a
# small window with three status lights, so nobody has to read a console.

param([switch]$AutoStart)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$portal = Join-Path $here "verification-portal"
$boot = Join-Path $portal "start_showcase.ps1"
$urlFile = Join-Path $portal "showcase-url.txt"
$logOut = Join-Path $env:TEMP "p14-launcher.out"
$logErr = Join-Path $env:TEMP "p14-launcher.err"
$logCheck = Join-Path $env:TEMP "p14-preflight.out"

function Start-Preflight {
    if ($script:checkProc -and -not $script:checkProc.HasExited) { return }
    Remove-Item $logCheck -ErrorAction SilentlyContinue
    $py = Join-Path $portal ".venv\Scripts\python.exe"
    $pf = Join-Path $portal "scripts\preflight.py"
    $url = ""
    if (Test-Path $urlFile) { $url = (Get-Content $urlFile -Raw).Trim() }
    $inner = "`$env:PUBLIC_BASE_URL='$url'; `$env:PYTHONIOENCODING='utf-8'; " +
             "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; & '$py' '$pf'"
    $exe = (Get-Command powershell.exe -ErrorAction SilentlyContinue).Source
    $script:checkProc = Start-Process -FilePath $exe -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $inner
    ) -RedirectStandardOutput $logCheck -WindowStyle Hidden -PassThru
}

$script:bootProc = $null
$script:publicUrl = ""
$script:started = $false
$script:checkProc = $null
$script:retriedCheck = $false

$INK   = [System.Drawing.Color]::FromArgb(26, 22, 17)
$PAPER = [System.Drawing.Color]::FromArgb(250, 247, 240)
$CARD  = [System.Drawing.Color]::FromArgb(253, 251, 246)
$MUTED = [System.Drawing.Color]::FromArgb(93, 85, 75)
$GREY  = [System.Drawing.Color]::FromArgb(160, 152, 138)
$GREEN = [System.Drawing.Color]::FromArgb(47, 107, 70)
$RED   = [System.Drawing.Color]::FromArgb(168, 69, 47)
$AMBER = [System.Drawing.Color]::FromArgb(176, 138, 62)

function Get-Health {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:8013/healthz" -TimeoutSec 2 -UseBasicParsing
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Start-Portal {
    if ($script:bootProc -and -not $script:bootProc.HasExited) { return }
    if (-not (Test-Path $boot)) {
        [System.Windows.Forms.MessageBox]::Show("start_showcase.ps1 not found inside verification-portal\.", "P14 launcher")
        return
    }

    $script:started = $true
    $script:publicUrl = ""
    $script:retriedCheck = $false
    Remove-Item $logOut, $logErr, $urlFile, $logCheck -ErrorAction SilentlyContinue

    $urlLabel.Text = "waiting for Cloudflare..."
    $urlLabel.ForeColor = $MUTED
    $clipBtn.Enabled = $false
    $recheckBtn.Enabled = $false
    $startBtn.Enabled = $false
    $stopBtn.Enabled = $true
    $logBox.Text = "starting server, tunnel, pretest..."

    $exe = (Get-Command powershell.exe -ErrorAction SilentlyContinue).Source
    # decode the child's python output as UTF-8, otherwise preflight's Chinese
    # lines arrive as mojibake in the box below
    $inner = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " +
             "& '$boot' -NoBrowser"
    $script:bootProc = Start-Process -FilePath $exe -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $inner
    ) -RedirectStandardOutput $logOut -RedirectStandardError $logErr -WindowStyle Hidden -PassThru
}

function Stop-Portal {
    Get-NetTCPConnection -LocalPort 8013 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if ($script:bootProc -and -not $script:bootProc.HasExited) {
        Stop-Process -Id $script:bootProc.Id -Force -ErrorAction SilentlyContinue
    }
    $script:bootProc = $null
    $script:started = $false
    $script:publicUrl = ""
    $script:retriedCheck = $false
    $startBtn.Enabled = $true
    $stopBtn.Enabled = $false
    $clipBtn.Enabled = $false
    $recheckBtn.Enabled = $false
    $urlLabel.Text = "no public address yet"
    $urlLabel.ForeColor = $MUTED
}

# ------------------------------------------------------------------ form -----
$form = New-Object System.Windows.Forms.Form
$form.Text = "P14 - Mobile Credential Verification Portal"
$form.ClientSize = New-Object System.Drawing.Size(660, 506)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox = $false
$form.BackColor = $PAPER
$form.Font = New-Object System.Drawing.Font("Segoe UI", 10)

$kicker = New-Object System.Windows.Forms.Label
$kicker.Text = "GEF MOBILE   /   P14   /   BOOTH LAUNCHER"
$kicker.Font = New-Object System.Drawing.Font("Segoe UI", 7.5)
$kicker.ForeColor = $GREY
$kicker.Location = New-Object System.Drawing.Point(26, 18)
$kicker.Size = New-Object System.Drawing.Size(420, 16)
$form.Controls.Add($kicker)

$title = New-Object System.Windows.Forms.Label
$title.Text = "Credential Verification Portal"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 17)
$title.ForeColor = $INK
$title.Location = New-Object System.Drawing.Point(22, 36)
$title.Size = New-Object System.Drawing.Size(560, 34)
$form.Controls.Add($title)

$sub = New-Object System.Windows.Forms.Label
$sub.Text = "One press: server, public tunnel, pretest. Then open the stage and start talking."
$sub.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
$sub.ForeColor = $MUTED
$sub.Location = New-Object System.Drawing.Point(26, 72)
$sub.Size = New-Object System.Drawing.Size(600, 18)
$form.Controls.Add($sub)

function New-Light([int]$y, [string]$name) {
    $dot = New-Object System.Windows.Forms.Panel
    $dot.Location = New-Object System.Drawing.Point(26, ($y + 5))
    $dot.Size = New-Object System.Drawing.Size(12, 12)
    $dot.Tag = $GREY
    $dot.BackColor = $PAPER
    $dot.Add_Paint({ param($s, $e)
        $e.Graphics.SmoothingMode = "AntiAlias"
        $brush = New-Object System.Drawing.SolidBrush($s.Tag)
        $e.Graphics.FillEllipse($brush, 0, 0, 11, 11)
        $brush.Dispose()
    })
    $form.Controls.Add($dot)

    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = $name
    $lbl.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
    $lbl.ForeColor = $GREY
    $lbl.Location = New-Object System.Drawing.Point(48, $y)
    $lbl.Size = New-Object System.Drawing.Size(86, 20)
    $form.Controls.Add($lbl)

    $txt = New-Object System.Windows.Forms.Label
    $txt.Text = "not started"
    $txt.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $txt.ForeColor = $MUTED
    $txt.Location = New-Object System.Drawing.Point(136, $y)
    $txt.Size = New-Object System.Drawing.Size(500, 20)
    $form.Controls.Add($txt)

    return @($dot, $txt)
}

$r1 = New-Light 100 "SERVER"
$dotPortal = $r1[0]; $txtPortal = $r1[1]
$r2 = New-Light 124 "TUNNEL"
$dotTunnel = $r2[0]; $txtTunnel = $r2[1]
$r3 = New-Light 148 "PRETEST"
$dotCheck = $r3[0]; $txtCheck = $r3[1]

function Set-Row($dot, $txt, $color, $message) {
    $dot.Tag = $color
    $dot.Invalidate()
    $txt.Text = $message
}

$urlCap = New-Object System.Windows.Forms.Label
$urlCap.Text = "PUBLIC ADDRESS"
$urlCap.Font = New-Object System.Drawing.Font("Segoe UI", 7.5)
$urlCap.ForeColor = $GREY
$urlCap.Location = New-Object System.Drawing.Point(26, 180)
$urlCap.Size = New-Object System.Drawing.Size(220, 14)
$form.Controls.Add($urlCap)

$urlLabel = New-Object System.Windows.Forms.Label
$urlLabel.Text = "no public address yet"
$urlLabel.Font = New-Object System.Drawing.Font("Consolas", 9.5)
$urlLabel.ForeColor = $MUTED
$urlLabel.Location = New-Object System.Drawing.Point(26, 196)
$urlLabel.Size = New-Object System.Drawing.Size(600, 20)
$form.Controls.Add($urlLabel)

function New-Button([string]$text, [int]$x, [int]$y, [int]$w, [int]$h, [bool]$primary) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text
    $b.Location = New-Object System.Drawing.Point($x, $y)
    $b.Size = New-Object System.Drawing.Size($w, $h)
    $b.FlatStyle = "Flat"
    $b.Font = New-Object System.Drawing.Font("Segoe UI", 9.5)
    $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    if ($primary) {
        $b.BackColor = $INK
        $b.ForeColor = $PAPER
        $b.FlatAppearance.BorderColor = $INK
    } else {
        $b.BackColor = $CARD
        $b.ForeColor = $INK
        $b.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(205, 191, 165)
    }
    $form.Controls.Add($b)
    return $b
}

$startBtn = New-Button "START THE DEMO" 26 228 188 40 $true
$stageBtn = New-Button "Open stage" 222 228 132 40 $false
$verifyBtn = New-Button "Open verify" 362 228 132 40 $false
$stopBtn = New-Button "Stop" 502 228 132 40 $false
$stopBtn.Enabled = $false
$clipBtn = New-Button "Copy public address" 26 274 188 28 $false
$clipBtn.Enabled = $false
$recheckBtn = New-Button "Re-check" 222 274 132 28 $false
$recheckBtn.Enabled = $false

$logCap = New-Object System.Windows.Forms.Label
$logCap.Text = "LAUNCHER OUTPUT"
$logCap.Font = New-Object System.Drawing.Font("Segoe UI", 7.5)
$logCap.ForeColor = $GREY
$logCap.Location = New-Object System.Drawing.Point(26, 314)
$logCap.Size = New-Object System.Drawing.Size(220, 14)
$form.Controls.Add($logCap)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Multiline = $true
$logBox.ReadOnly = $true
$logBox.ScrollBars = "Vertical"
$logBox.Font = New-Object System.Drawing.Font("Consolas", 8)
$logBox.Location = New-Object System.Drawing.Point(26, 330)
$logBox.Size = New-Object System.Drawing.Size(608, 130)
$logBox.BackColor = $CARD
$logBox.ForeColor = $MUTED
$logBox.BorderStyle = "FixedSingle"
$form.Controls.Add($logBox)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = "This window can stay open all day. Closing it leaves the demo running; Stop shuts it down."
$hint.Font = New-Object System.Drawing.Font("Segoe UI", 7.5)
$hint.ForeColor = $GREY
$hint.Location = New-Object System.Drawing.Point(26, 470)
$hint.Size = New-Object System.Drawing.Size(608, 16)
$form.Controls.Add($hint)

# ----------------------------------------------------------------- wiring ----
$startBtn.Add_Click({ Start-Portal })
$stopBtn.Add_Click({ Stop-Portal })
$stageBtn.Add_Click({ Start-Process "http://127.0.0.1:8013/showtime?token=demo-staff-token" })
$verifyBtn.Add_Click({ Start-Process "http://127.0.0.1:8013/verify" })
$clipBtn.Add_Click({
    if ($script:publicUrl) { [System.Windows.Forms.Clipboard]::SetText($script:publicUrl) }
})
$recheckBtn.Add_Click({ Start-Preflight })

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1500
$timer.Add_Tick({
    $text = ""
    if (Test-Path $logOut) { $text = (Get-Content $logOut -Tail 60 -Encoding UTF8 -ErrorAction SilentlyContinue) -join "`r`n" }
    if (Test-Path $logErr) {
        $e = (Get-Content $logErr -Tail 14 -Encoding UTF8 -ErrorAction SilentlyContinue) -join "`r`n"
        if ($e.Trim()) { $text += "`r`n" + $e }
    }
    $check = ""
    if (Test-Path $logCheck) { $check = (Get-Content $logCheck -Encoding UTF8 -ErrorAction SilentlyContinue) -join "`r`n" }
    if ($check -and $logBox.Text -ne $check) {
        $logBox.Text = $check
        $logBox.SelectionStart = $logBox.Text.Length
        $logBox.ScrollToCaret()
    }

    $up = Get-Health
    if ($up) {
        if ($script:started) { Set-Row $dotPortal $txtPortal $GREEN "up on 127.0.0.1:8013" }
        else { Set-Row $dotPortal $txtPortal $AMBER "a server is already running (Start restarts it)" }
    } elseif ($script:started -and $script:bootProc -and -not $script:bootProc.HasExited) {
        Set-Row $dotPortal $txtPortal $AMBER "starting..."
    } else {
        Set-Row $dotPortal $txtPortal $GREY "not running"
    }

    if ($script:started -and -not $script:publicUrl -and (Test-Path $urlFile)) {
        $u = (Get-Content $urlFile -Raw).Trim()
        if ($u -match '^https://') {
            $script:publicUrl = $u
            $urlLabel.Text = $u
            $urlLabel.ForeColor = $INK
            $clipBtn.Enabled = $true
        }
    }
    if ($script:publicUrl) {
        if ($up) { Set-Row $dotTunnel $txtTunnel $GREEN "live - phones can scan the stage QR" }
        else { Set-Row $dotTunnel $txtTunnel $AMBER "address known, server not answering" }
    } elseif ($script:started) {
        Set-Row $dotTunnel $txtTunnel $AMBER "waiting for Cloudflare (it retries by itself)"
    }

    if ($script:started) {
        $verdictText = $check
        if (-not $verdictText) { $verdictText = $text }
        if ($verdictText -match "checks passed") {
            Set-Row $dotCheck $txtCheck $GREEN "passed - safe to open the booth"
            $recheckBtn.Enabled = $false
        } elseif ($verdictText -match "preflight failed" -or $verdictText -match "Traceback") {
            $recheckBtn.Enabled = $true
            if ($verdictText -match "public tunnel" -and -not $script:retriedCheck) {
                # a brand-new quick tunnel needs a few seconds of DNS before it
                # answers from outside; retry once rather than show a false red
                $script:retriedCheck = $true
                Set-Row $dotCheck $txtCheck $AMBER "public address not live yet - retrying once"
                Start-Preflight
            } else {
                Set-Row $dotCheck $txtCheck $RED "a check failed - press Re-check, or read the output"
            }
        } elseif ($check) {
            Set-Row $dotCheck $txtCheck $AMBER "checking..."
        } elseif ($up) {
            Set-Row $dotCheck $txtCheck $AMBER "running the 11 checks..."
        }
    }

    if ($script:bootProc -and $script:bootProc.HasExited) {
        $script:bootProc = $null
        $startBtn.Enabled = $true
        $stopBtn.Enabled = ($null -ne (Get-NetTCPConnection -LocalPort 8013 -State Listen -ErrorAction SilentlyContinue))
    }
})
$timer.Start()

if ($AutoStart) { $form.Add_Shown({ Start-Portal }) }

[void]$form.ShowDialog()
