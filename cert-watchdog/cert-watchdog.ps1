# cert-watchdog.ps1 — Monitors Downloads for certificate PDFs and moves them to organized folders
# Usage: powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "cert-watchdog.ps1"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigPath = Join-Path $ScriptDir "cert-watchdog.json"

if (-not (Test-Path $ConfigPath)) {
    Write-Error "Config not found: $ConfigPath"
    exit 1
}

$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$WatchDir = $Config.watch_dir
$DestDir = $Config.dest_dir

if (-not (Test-Path $WatchDir)) {
    Write-Error "Watch directory not found: $WatchDir"
    exit 1
}

# Known products sorted longest-first (so Chegina_K40GLOL matches before Chegina_K40GL)
$Products = @(
    "Chegina K40GLOL HQ",
    "Chegina K40GLOL",
    "Chegina K40GLOS",
    "Chegina K40GLO",
    "Chegina K40GL",
    "Chegina K7GLO",
    "Chegina K7B",
    "Chegina K7",
    "Chegina KK",
    "Chegina CCR",
    "Chegina CC",
    "Chegina L9",
    "Chegina",
    "Cheminox K35",
    "Cheminox LA",
    "Cheminox K",
    "Chemipol ML",
    "Chemipol OL",
    "Monamid KO Revada",
    "Monamid KO",
    "Monamid K",
    "Monamid L",
    "Monamid S",
    "Dister E",
    "Monester O",
    "Monester S",
    "Alkinol B",
    "Alkinol",
    "Alstermid K",
    "Alstermid",
    "Chemal CS3070",
    "Chemal EO20",
    "Chemal SE12",
    "Chemal PC",
    "Polcet A",
    "Chelamid DK",
    "Glikoster P",
    "Citrowax",
    "Kwas stearynowy",
    "Perlico 45",
    "SLES",
    "HSH CS3070"
)

function Get-MatchedProduct($FileName) {
    $BaseName = [System.IO.Path]::GetFileNameWithoutExtension($FileName)
    foreach ($p in $Products) {
        if ($BaseName.StartsWith($p)) {
            return $p
        }
    }
    return $null
}

function Move-Certificate($FilePath) {
    $FileName = [System.IO.Path]::GetFileName($FilePath)

    # Wait for file to be fully written (browser may still be writing)
    Start-Sleep -Seconds 2

    $Product = Get-MatchedProduct $FileName
    if (-not $Product) { return }

    $Year = (Get-Date).Year.ToString()
    $TargetDir = Join-Path $DestDir (Join-Path $Year $Product)
    $TargetPath = Join-Path $TargetDir $FileName

    # Create target directory
    if (-not (Test-Path $TargetDir)) {
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    }

    # Archive existing file if it would be overwritten
    if (Test-Path $TargetPath) {
        $ArchiveDir = Join-Path $TargetDir "_archiwum"
        if (-not (Test-Path $ArchiveDir)) {
            New-Item -ItemType Directory -Path $ArchiveDir -Force | Out-Null
        }
        $ArchivePath = Join-Path $ArchiveDir $FileName
        # If archive also has this file, add timestamp
        if (Test-Path $ArchivePath) {
            $Stem = [System.IO.Path]::GetFileNameWithoutExtension($FileName)
            $Ts = (Get-Date).ToString("yyyy-MM-dd HH-mm")
            $ArchivePath = Join-Path $ArchiveDir "$Stem ($Ts).pdf"
        }
        Move-Item -Path $TargetPath -Destination $ArchivePath -Force
    }

    Move-Item -Path $FilePath -Destination $TargetPath -Force
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $FileName -> $Year\$Product\"
}

# Set up FileSystemWatcher
$Watcher = New-Object System.IO.FileSystemWatcher
$Watcher.Path = $WatchDir
$Watcher.Filter = "*.pdf"
$Watcher.EnableRaisingEvents = $true

$Action = {
    $path = $Event.SourceEventArgs.FullPath
    Move-Certificate $path
}

Register-ObjectEvent $Watcher "Created" -Action $Action | Out-Null

Write-Host "Cert Watchdog started"
Write-Host "  Watch: $WatchDir"
Write-Host "  Dest:  $DestDir"
Write-Host "  Products: $($Products.Count)"

# Keep alive
while ($true) { Start-Sleep -Seconds 60 }
