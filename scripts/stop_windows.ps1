# Stop and remove the FinAlly container. The data volume is kept.
$existing = docker ps -a --format '{{.Names}}' | Where-Object { $_ -eq 'finally' }
if ($existing) {
    docker rm -f finally | Out-Null
    Write-Host 'FinAlly stopped (volume finally-data preserved).'
} else {
    Write-Host 'FinAlly is not running.'
}
