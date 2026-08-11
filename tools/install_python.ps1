<#
    Install Python, but only when it is actually missing.

    setup.bat calls this only if no suitable Python was found, so anyone who
    already has one is never prompted and nothing on their machine changes.

    Always asks before installing. Prefers winget (already on most Windows 11
    machines); otherwise downloads the official installer from python.org and
    shows the exact URL first. Installs for the current user only, so no admin
    prompt, and adds Python to PATH so setup.bat can carry on.
#>

$ErrorActionPreference = 'Stop'
$MinMajor, $MinMinor = 3, 10

# Pinned so the download URL is predictable and auditable. Any 3.10+ works;
# this is simply a known-good version to fetch when winget isn't available.
$Version = '3.12.8'
$Url = "https://www.python.org/ftp/python/$Version/python-$Version-amd64.exe"


function Find-Python {
    <# Returns a python.exe that meets the minimum version, or $null. #>
    foreach ($candidate in @('python', 'python3')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $v = & $cmd.Source -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
                if ($v) {
                    $maj, $min = $v.Trim().Split('.')
                    if ([int]$maj -gt $MinMajor -or ([int]$maj -eq $MinMajor -and [int]$min -ge $MinMinor)) {
                        return $cmd.Source
                    }
                }
            } catch { }
        }
    }
    # The py launcher can know about installs that aren't on PATH.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $p = & py "-$MinMajor" -c "import sys;print(sys.executable)" 2>$null
            if ($p) { return $p.Trim() }
        } catch { }
    }
    return $null
}


$existing = Find-Python
if ($existing) {
    Write-Host "  Python already present: $existing"
    exit 0
}

Write-Host ""
Write-Host "  Claude Vitals needs Python $MinMajor.$MinMinor or newer, and it isn't installed."
Write-Host ""
Write-Host "  I can install it for you. It will be installed for your user only,"
Write-Host "  so Windows won't ask for administrator rights."
Write-Host ""

$answer = Read-Host "  Install Python now? [Y/n]"
if ($answer -and $answer.Trim().ToLower() -notin @('y', 'yes')) {
    Write-Host ""
    Write-Host "  No problem. You can install it yourself from:"
    Write-Host "    https://www.python.org/downloads/"
    Write-Host "  Tick 'Add python.exe to PATH' during setup, then run setup.bat again."
    exit 1
}

# --- try winget first -----------------------------------------------------
$installed = $false
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host ""
    Write-Host "  Installing via winget..."
    try {
        winget install --id "Python.Python.3.12" --scope user --silent `
            --accept-package-agreements --accept-source-agreements
        $installed = $true
    } catch {
        Write-Host "  winget didn't work, falling back to the official installer."
    }
}

# --- otherwise download the official installer ----------------------------
if (-not $installed) {
    $target = Join-Path $env:TEMP "python-$Version-amd64.exe"
    Write-Host ""
    Write-Host "  Downloading Python $Version from:"
    Write-Host "    $Url"
    Write-Host ""
    try {
        $ProgressPreference = 'SilentlyContinue'   # the bar makes this far slower
        Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing
    } catch {
        Write-Host "  Download failed: $($_.Exception.Message)"
        Write-Host "  Install it manually from https://www.python.org/downloads/"
        exit 1
    }

    $size = (Get-Item $target).Length
    if ($size -lt 1MB) {
        Write-Host "  The download looks wrong ($size bytes). Install manually instead."
        exit 1
    }
    Write-Host ("  Downloaded {0:N0} MB. Running the installer..." -f ($size / 1MB))
    Write-Host "  (a progress window will appear for a minute or two)"

    # Per-user, no admin prompt, and on PATH so setup.bat can find it next.
    $proc = Start-Process -FilePath $target -Wait -PassThru -ArgumentList @(
        '/passive', 'InstallAllUsers=0', 'PrependPath=1',
        'Include_launcher=1', 'Include_test=0'
    )
    Remove-Item $target -Force -ErrorAction SilentlyContinue
    if ($proc.ExitCode -ne 0) {
        Write-Host "  The installer exited with code $($proc.ExitCode)."
        Write-Host "  Install manually from https://www.python.org/downloads/"
        exit 1
    }
}

# PATH changes don't reach this already-running process, so refresh it here.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path', 'User')

$found = Find-Python
if ($found) {
    Write-Host ""
    Write-Host "  Python installed: $found"
    exit 0
}

Write-Host ""
Write-Host "  Python was installed but isn't visible yet."
Write-Host "  Close this window, open a new one, and run setup.bat again."
exit 2
