# ============================================================
#  KanaePlayerLive - Hosts File Fix
#  Jalankan sebagai Administrator di PowerShell:
#  powershell -ExecutionPolicy Bypass -File setup-hosts.ps1
# ============================================================

$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
$entry     = "127.0.0.1`tkanaeplayerlive.id`t# KanaePlayerLive TikTok Studio Fix"

$content = Get-Content $hostsPath -Raw

if ($content -match "kanaeplayerlive\.id") {
    Write-Host " Sudah ada, tidak ditambah ulang." -ForegroundColor Yellow
} else {
    Add-Content -Path $hostsPath -Value "`n$entry"
    Write-Host " Berhasil ditambahkan!" -ForegroundColor Green
}
