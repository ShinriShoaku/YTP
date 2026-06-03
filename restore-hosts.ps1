# ============================================================
#  KanaePlayerLive - Restore Hosts File
# ============================================================
$hostsPath  = "$env:SystemRoot\System32\drivers\etc\hosts"
$backupPath = "$env:SystemRoot\System32\drivers\etc\hosts.bak"

if (Test-Path $backupPath) {
    Copy-Item -Path $backupPath -Destination $hostsPath -Force
    Remove-Item -Path $backupPath -Force
    Write-Host " Berhasil di-restore dari backup!" -ForegroundColor Green
    Write-Host " File hosts.bak sudah dihapus." -ForegroundColor Cyan
} else {
    Write-Host " Backup tidak ditemukan ($backupPath)" -ForegroundColor Red
    Write-Host " Jalankan setup-hosts.bat dulu untuk membuat backup." -ForegroundColor Yellow
}

Write-Host ""
Read-Host "Tekan Enter untuk keluar"
