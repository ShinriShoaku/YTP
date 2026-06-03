# ============================================================
#  KanaePlayerLive - Restore Hosts File
#  Jalankan sebagai Administrator di PowerShell:
#  powershell -ExecutionPolicy Bypass -File restore-hosts.ps1
# ============================================================

$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"

$content    = Get-Content $hostsPath
$newContent = $content | Where-Object { $_ -notmatch "kanaeplayerlive\.id" }

if ($content.Count -ne $newContent.Count) {
    Set-Content -Path $hostsPath -Value $newContent
    Write-Host " Berhasil dihapus / di-restore!" -ForegroundColor Green
} else {
    Write-Host " Entry tidak ditemukan, tidak ada yang dihapus." -ForegroundColor Yellow
}
