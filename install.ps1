# Sensei installer for Windows.
#
#   irm https://raw.githubusercontent.com/SenseiIssei/Sensei/main/install.ps1 | iex
#
# Downloads the installer from the latest GitHub release, checks it against the
# release's SHA256SUMS, and runs it per-user: no administrator prompt, a Start
# menu entry, Sensei in the tray at sign-in, and the AI tools on this machine
# connected (each one backed up first; the uninstaller puts them back).
#
# Settings, as environment variables (set before piping into iex):
#   $env:SENSEI_VERSION = "0.2.0"     a specific release instead of the latest
#   $env:SENSEI_AUTOSTART = "no"      do not start at sign-in
#   $env:SENSEI_SETUP_TOOLS = "no"    do not connect AI tools, now or later
#                                     (remembered; `sensei connect` changes it)
#
# From a clone, `.\install.ps1 -FromSource` builds and installs from the
# checkout instead (Python 3.11+ required, Node.js optional for the web UI).

param([switch]$FromSource, [switch]$Run, [switch]$SkipTools)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is 10x slower with it
$repo = "SenseiIssei/Sensei"

function Say($text) { Write-Host "  $text" }
function Ok($text) { Write-Host "  + $text" -ForegroundColor Green }

if ($FromSource -or $env:SENSEI_FROM_SOURCE -eq "1") {
    $root = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (-not $root -or -not (Test-Path (Join-Path $root "backend"))) {
        throw "-FromSource needs a clone: git clone https://github.com/$repo; cd Sensei; .\install.ps1 -FromSource"
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw "Python 3.11+ is required and was not found on PATH." }
    $venv = Join-Path $root ".venv"
    if (-not (Test-Path $venv)) { & python -m venv $venv }
    $vpy = Join-Path $venv "Scripts\python.exe"
    & $vpy -m pip install --upgrade pip -q
    & $vpy -m pip install -e "$(Join-Path $root 'backend')[mcp,tray]" -q
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Push-Location (Join-Path $root "frontend")
        & npm ci --no-audit --no-fund --loglevel=error
        & npm run build
        Pop-Location
    } else {
        Say "Node.js not found - skipping the web UI build (gateway and API still work)."
    }
    if ($SkipTools -or $env:SENSEI_SETUP_TOOLS -eq "no") {
        & $vpy -m sensei.cli setup-tools --auto off
    } else {
        & $vpy -m sensei.cli setup-tools --from-installer
    }
    Ok "Installed from source. Start it with: $vpy -m sensei.cli tray"
    if ($Run) { & $vpy -m sensei.cli up }
    return
}

Write-Host ""
Write-Host "  Sensei - fewer tokens for the AI tools you already use" -ForegroundColor White
Write-Host ""

$headers = @{ "User-Agent" = "sensei-installer" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
if ($env:SENSEI_VERSION) {
    # A pinned version needs no API call: the release workflow fixes the asset
    # names. The API allows 60 unauthenticated requests an hour per IP, and a
    # shared NAT or CI runner can use that up before this script ever runs.
    $ver = $env:SENSEI_VERSION.TrimStart("v")
    $tagName = "v$ver"
    $base = "https://github.com/$repo/releases/download/$tagName"
    $setupName = "sensei-setup-$ver.exe"
    $setupUrl = "$base/$setupName"
    $sumsUrl = "$base/SHA256SUMS"
} else {
    $release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers $headers
    $setup = $release.assets | Where-Object { $_.name -like "sensei-setup-*.exe" } | Select-Object -First 1
    $sums = $release.assets | Where-Object { $_.name -eq "SHA256SUMS" } | Select-Object -First 1
    if (-not $setup -or -not $sums) { throw "Release $tagName has no Windows installer." }
    $tagName = $release.tag_name
    $setupName = $setup.name
    $setupUrl = $setup.browser_download_url
    $sumsUrl = $sums.browser_download_url
}

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("sensei-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $exe = Join-Path $tmp $setupName
    Say "Downloading $($setupName)"
    Invoke-WebRequest $setupUrl -OutFile $exe -UseBasicParsing
    $sumsText = (Invoke-WebRequest $sumsUrl -UseBasicParsing).Content
    if ($sumsText -is [byte[]]) { $sumsText = [Text.Encoding]::UTF8.GetString($sumsText) }

    $line = ($sumsText -split "`n") | Where-Object { $_.Trim().EndsWith($setupName) } | Select-Object -First 1
    if (-not $line) { throw "SHA256SUMS does not list $($setupName) - refusing to install." }
    $expected = ($line.Trim() -split "\s+")[0].ToLower()
    $actual = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) { throw "Checksum mismatch for $($setupName): expected $expected, got $actual" }
    Ok "Checksum verified"

    $tasks = @()
    if ($env:SENSEI_AUTOSTART -ne "no") { $tasks += "startup" }
    if ($env:SENSEI_SETUP_TOOLS -ne "no" -and -not $SkipTools) { $tasks += "wiretools" }
    $taskArg = if ($tasks.Count) { "/TASKS=`"$($tasks -join ',')`"" } else { "/TASKS=`"`"" }

    Say "Installing (per-user, no administrator rights needed)"
    # Not `Start-Process -Wait`: that waits for every process the installer
    # starts, and a silent install ends by starting the tray, which runs until
    # sign-out. On a real desktop the script then hung forever. WaitForExit()
    # waits for the installer itself and nothing else.
    $proc = Start-Process -FilePath $exe -ArgumentList "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", $taskArg -PassThru
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) { throw "The installer exited with code $($proc.ExitCode)." }
    Ok "Installed Sensei $tagName"
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

$app = Join-Path $env:LOCALAPPDATA "Programs\Sensei\senseiw.exe"
$cli = Join-Path $env:LOCALAPPDATA "Programs\Sensei\sensei.exe"
if (($env:SENSEI_SETUP_TOOLS -eq "no" -or $SkipTools) -and (Test-Path $cli)) {
    # An explicit "no" from whoever runs this script, so it overrides an
    # earlier "yes". install.ps1 runs the installer silently,
    # and a silent run only records "no" if nothing was chosen before; this
    # makes the answer stick. A pinned older release rejects the flag harmlessly.
    try { & $cli setup-tools --auto off *> $null } catch { }
}
# A silent install already starts the tray. A second one cannot bind the port
# and would sit in the notification area doing nothing, so start one only if
# none is running (the tray itself also checks, for older installers).
$running = Get-Process -Name "senseiw" -ErrorAction SilentlyContinue
if ((Test-Path $app) -and -not $env:CI -and -not $running) {
    Start-Process $app -ArgumentList "tray", "--no-browser"
}
if ($env:SENSEI_SETUP_TOOLS -eq "no" -or $SkipTools) {
    Say "AI tools were left alone, and new ones will not be connected automatically."
    Say "Connect them later:  sensei connect   (or the tray menu)"
} else {
    Say "See what was connected:  sensei setup-tools --status"
}

Write-Host ""
Ok "Done. Sensei is in the tray; dashboard: http://localhost:7000/app/"
Say "Check it:      sensei doctor"
Say "Update later:  sensei update   (or the tray menu)"
Say "Uninstall:     Settings > Apps > Sensei"
Write-Host ""
