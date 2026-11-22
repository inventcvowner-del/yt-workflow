param([Parameter(Mandatory = $true)][string]$Topic)

# Splits script.txt into one text file per section (sections are separated by a line of dashes).
$root = Join-Path "D:\youtube\long videos" $Topic
$out = Join-Path $root "sections"
New-Item -ItemType Directory $out -Force | Out-Null

$text = Get-Content (Join-Path $root "script.txt") -Raw -Encoding UTF8
# Drop video-clip markers like "6 scirtps brake here" / "6 scripts break here" so they are never narrated.
$text = $text -replace '(?im)^[ \t]*\d+[ \t]+s\w*[ \t]+br\w*[ \t]+here\b[^\r\n]*\r?$', ''
$parts = $text -split '(?m)^\s*-{5,}\s*$' | ForEach-Object { $_.Trim() } | Where-Object { $_ }

$i = 1
foreach ($p in $parts) {
    $file = Join-Path $out ("{0:D2}.txt" -f $i)
    [System.IO.File]::WriteAllText($file, $p, (New-Object System.Text.UTF8Encoding($true)))
    $i++
}
Write-Host "Created $($parts.Count) sections in $out"
