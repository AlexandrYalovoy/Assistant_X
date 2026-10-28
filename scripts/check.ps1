# Assistant X: every check in one command, the future CI. Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1 [-Fast] [-Log FOLDER] [pytest options...]
# ruff (errors of names and imports, and the format: ruff format --check), then the tests at a low priority (-Fast:
# without the slow tests). -Log FOLDER: a full record of the run there (every test with -rA -v, the 30 slowest, junit
# xml, the output in pytest.out.log). Any other argument goes to pytest (-k NAME, --durations=10, -x...).
# The exit code is 0 only when everything passed.
param([switch]$Fast, [string]$Log = "", [Parameter(ValueFromRemainingArguments = $true)][string[]]$PytestArgs = @())
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
$q = { param($a) if ($a -match '\s') { '"' + $a + '"' } else { $a } }
$pa = @("-m", "pytest", "-q", "-p", "no:cacheprovider", (& $q (Join-Path $root "tests")))
if ($Fast) { $pa += @("-m", '"not slow"') }
$redirect = @{}
if ($Log) {
    New-Item -ItemType Directory -Force $Log | Out-Null
    $pa += @("-rA", "-v", "--durations=30", ("--junitxml=" + (& $q (Join-Path $Log "junit.xml"))))
    $redirect = @{ RedirectStandardOutput = (Join-Path $Log "pytest.out.log"); RedirectStandardError = (Join-Path $Log "pytest.err.log") }
    Write-Host "the record of the run: $Log"
}
$pa += @($PytestArgs | ForEach-Object { & $q $_ })
$p = Start-Process -FilePath $py -ArgumentList $pa -WorkingDirectory $root -NoNewWindow -PassThru @redirect
$null = $p.Handle  # keeps the handle: without it ExitCode stays empty
try { $p.PriorityClass = "BelowNormal" } catch {}
$p.WaitForExit()
if ($Log) { Get-Content (Join-Path $Log "pytest.out.log") -Tail 1 }
if ($p.ExitCode -ne 0) { Write-Host "check: the tests failed"; exit 1 }
Write-Host "check: everything passed"
exit 0
