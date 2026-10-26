# Assistant X: every check in one command, the future CI. Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1 [-Fast]
# ruff (errors of names and imports, and the format: ruff format --check), then the tests at a low priority (-Fast:
# without the slow tests).
# The exit code is 0 only when everything passed.
param([switch]$Fast)
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "No environment .venv: run Setup.bat first"; exit 1 }
$env:PYTHONUTF8 = "1"
$env:AX_NO_OPEN = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
Write-Host "ruff..."
& $py -m ruff check $root
if ($LASTEXITCODE -ne 0) { Write-Host "check: ruff found errors"; exit 1 }
& $py -m ruff format --check $root
if ($LASTEXITCODE -ne 0) { Write-Host "check: files not formatted: python -m ruff format ."; exit 1 }
Write-Host "tests..."
# Start-Process joins the arguments with spaces: the ones with a space are quoted here
$pa = @("-m", "pytest", "-q", "-p", "no:cacheprovider", ('"' + (Join-Path $root "tests") + '"'))
if ($Fast) { $pa += @("-m", '"not slow"') }
$p = Start-Process -FilePath $py -ArgumentList $pa -WorkingDirectory $root -NoNewWindow -PassThru
$null = $p.Handle  # keeps the handle: without it ExitCode stays empty
try { $p.PriorityClass = "BelowNormal" } catch {}
$p.WaitForExit()
if ($p.ExitCode -ne 0) { Write-Host "check: the tests failed"; exit 1 }
Write-Host "check: everything passed"
exit 0
