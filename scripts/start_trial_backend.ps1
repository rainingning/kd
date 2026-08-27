$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
$backend = Join-Path $repo 'backend'

$dbUrl = & $python -c "import sys; sys.path.insert(0, r'$backend'); from app.config import settings; from sqlalchemy.engine import make_url; print(make_url(settings.database_url).set(database='fortran_platform_trial').render_as_string(hide_password=False))"
if ($LASTEXITCODE -ne 0) { throw 'Unable to derive trial database URL' }

$env:DATABASE_URL = $dbUrl.Trim()
$env:EXECUTION_MODE = 'mock'
$env:STORAGE_ROOT = Join-Path $repo 'storage\trial-instance'
$env:RESULT_ZIP_CACHE_ROOT = Join-Path $repo 'storage\trial-instance\.zip-cache'
$env:FORTRAN_PROGRAM_TEMPLATE_DIR = Join-Path $repo 'program_template'
$env:APP_BASE_URL = 'http://127.0.0.1:8000'

Set-Location $backend
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
