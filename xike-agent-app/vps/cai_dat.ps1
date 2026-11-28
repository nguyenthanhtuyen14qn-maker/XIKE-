# Cai cau noi XIKE tren VPS Windows. Chay trong PowerShell (Admin):
#   iwr -useb https://raw.githubusercontent.com/nguyenthanhtuyen14qn-maker/XIKE-/claude/new-session-seevus/xike-agent-app/vps/cai_dat.ps1 | iex
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = 'Tls12'
$dir = 'C:\xike'
$vps = "$dir\vps"
$py = 'C:\Program Files\Python311\python.exe'
$zip = 'https://github.com/nguyenthanhtuyen14qn-maker/XIKE-/archive/refs/heads/claude/new-session-seevus.zip'
New-Item -ItemType Directory -Force $dir, $vps | Out-Null
Set-Location $dir

if (-not (Test-Path $py)) {
  Write-Host '[1/4] Dang tai va cai Python 3.11 (1-3 phut)...' -ForegroundColor Cyan
  Invoke-WebRequest https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe -OutFile "$dir\py.exe" -UseBasicParsing
  Start-Process "$dir\py.exe" -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1' -Wait
  if (-not (Test-Path $py)) { throw 'Cai Python khong thanh cong. Chup man hinh gui lai.' }
} else { Write-Host '[1/4] Da co Python.' -ForegroundColor Green }

# Giu lai token va ma vang cu (neu da cai truoc do)
$oldTok = ''; $oldSym = ''
if (Test-Path "$vps\chay.bat") {
  $old = Get-Content "$vps\chay.bat" -Raw
  if ($old -match '(?m)^set XIKE_TOKEN=(.+)$' -and $Matches[1] -notmatch 'DOI-CHUOI') { $oldTok = $Matches[1].Trim() }
  if ($old -match '(?m)^set XIKE_SYMBOLS=(.+)$') { $oldSym = $Matches[1].Trim() }
}

Write-Host '[2/4] Dang tai cau noi XIKE...' -ForegroundColor Cyan
Invoke-WebRequest $zip -OutFile "$dir\xike.zip" -UseBasicParsing
Expand-Archive "$dir\xike.zip" $dir -Force
Copy-Item "$dir\XIKE--claude-new-session-seevus\xike-agent-app\vps\*" $vps -Recurse -Force

Write-Host '[3/4] Dang cai thu vien Python...' -ForegroundColor Cyan
& $py -m pip install -q --disable-pip-version-check -r "$vps\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw 'pip install loi. Chup man hinh gui lai.' }

$tok = if ($oldTok) { $oldTok } else { (& $py -c "import secrets; print(secrets.token_urlsafe(32))").Trim() }
$sym = Read-Host ("Ten ma vang trong MT5 (Enter = " + $(if ($oldSym) { $oldSym } else { 'XAUUSDm' }) + ")")
if (-not $sym) { $sym = if ($oldSym) { $oldSym } else { 'XAUUSDm' } }
$bat = Get-Content "$vps\chay.bat" -Raw
$bat = $bat -replace '(?m)^set XIKE_TOKEN=.*$', "set XIKE_TOKEN=$tok"
$bat = $bat -replace '(?m)^set XIKE_SYMBOLS=.*$', "set XIKE_SYMBOLS=$sym"
$bat = $bat -replace '(?m)^python server\.py', "`"$py`" server.py"
Set-Content "$vps\chay.bat" $bat -Encoding Ascii
Set-Content "$dir\TOKEN.txt" $tok -Encoding Ascii

# Loi tat tren man hinh Desktop
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\XIKE Bridge.lnk")
$lnk.TargetPath = "$vps\chay.bat"; $lnk.WorkingDirectory = $vps; $lnk.Save()

if (-not (Test-Path 'C:\Program Files\MetaTrader 5\terminal64.exe')) {
  Write-Host '[4/4] Dang tai MT5, cua so cai dat se hien ra: bam Next den Finish.' -ForegroundColor Cyan
  Invoke-WebRequest https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe -OutFile "$dir\mt5setup.exe" -UseBasicParsing
  Start-Process "$dir\mt5setup.exe"
} else { Write-Host '[4/4] Da co MT5.' -ForegroundColor Green }

Write-Host ''
Write-Host 'XONG. Token da luu o C:\xike\TOKEN.txt (nhap vao app, KHONG gui cho ai).' -ForegroundColor Green
Write-Host "Ma vang: $sym. Tren Desktop co loi tat 'XIKE Bridge': bam dup de chay cau noi." -ForegroundColor Green
