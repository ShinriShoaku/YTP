# ============================================================
#  KanaePlayerLive - Hosts File Fix
# ============================================================
$hostsPath  = "$env:SystemRoot\System32\drivers\etc\hosts"
$backupPath = "$env:SystemRoot\System32\drivers\etc\hosts.bak"
$entry      = "127.0.0.1`tkanaeplayerlive.id`t# KanaePlayerLive TikTok Studio Fix"

$content = Get-Content $hostsPath -Raw

if ($content -match "kanaeplayerlive\.id") {
    Write-Host " Sudah ada, tidak ditambah ulang." -ForegroundColor Yellow
} else {
    # Backup dulu sebelum edit
    Copy-Item -Path $hostsPath -Destination $backupPath -Force
    Write-Host " Backup disimpan di: $backupPath" -ForegroundColor Cyan

    Add-Content -Path $hostsPath -Value "`n$entry"
    Write-Host " Berhasil ditambahkan!" -ForegroundColor Green
}

Write-Host ""
Read-Host "Tekan Enter untuk keluar"
