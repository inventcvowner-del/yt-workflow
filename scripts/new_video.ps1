param([Parameter(Mandatory = $true)][string]$Topic)

$root = Join-Path "D:\youtube\long videos" $Topic
foreach ($d in "", "voices", "video_clips") {
    New-Item -ItemType Directory (Join-Path $root $d) -Force | Out-Null
}
$script = Join-Path $root "script.txt"
if (-not (Test-Path $script)) { New-Item -ItemType File $script | Out-Null }
Write-Host "Created $root"
