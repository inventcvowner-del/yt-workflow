param([Parameter(Mandatory = $true)][string]$Topic)

# Topic folders are numbered in order ("3. hepatitis virus"). An existing topic is found by its name, with or without the
# number; a new topic gets the next number.
$base = "D:\youtube\long videos"
$number = '^\s*(\d+)\.\s+'
$plain = $Topic -replace $number, ''
$existing = Get-ChildItem -LiteralPath $base -Directory | Where-Object { ($_.Name -replace $number, '') -ieq $plain } | Select-Object -First 1
if ($existing) {
    $root = $existing.FullName
} else {
    $last = Get-ChildItem -LiteralPath $base -Directory | ForEach-Object { if ($_.Name -match $number) { [int]$Matches[1] } } | Measure-Object -Maximum
    $root = Join-Path $base ("{0}. {1}" -f ([int]$last.Maximum + 1), $plain)
}
foreach ($d in "", "voices", "video_clips") {
    New-Item -ItemType Directory (Join-Path $root $d) -Force | Out-Null
}
$script = Join-Path $root "script.txt"
if (-not (Test-Path $script)) { New-Item -ItemType File $script | Out-Null }
Write-Host "Created $root"
