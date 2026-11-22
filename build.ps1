$ErrorActionPreference = 'Stop'
$env:PATH = (($env:PATH -split ';') | Where-Object { $_ -notmatch 'poppler' }) -join ';'
python -m PyInstaller --clean --noconfirm --onefile --windowed --name pet_lwt --icon icon.ico --add-data 'icon.ico;.' pet_qt.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Built dist\pet_lwt.exe. Keep pets next to the executable.'
