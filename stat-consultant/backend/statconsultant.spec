# PyInstaller build spec for the stat-consultant backend.
#
# Committed as a spec rather than driven by CLI flags: --add-data uses ':' on
# macOS and ';' on Windows, so a single cross-platform command line isn't
# possible, and the hidden-import list below is the kind of thing that must be
# version-controlled with a rationale rather than living in a build script.
#
#   cd stat-consultant/backend
#   pyinstaller statconsultant.spec        # -> dist/stat-consultant-backend/
#
# Build prerequisite: the frontend must already be built, because it is bundled
# here and the backend serves it (Phase 1, one port, no Node at runtime):
#   cd ../frontend && npm ci && npm run build

import os

from PyInstaller.utils.hooks import copy_metadata

BACKEND_DIR = os.path.abspath(SPECPATH)
FRONTEND_DIST = os.path.join(BACKEND_DIR, os.pardir, "frontend", "dist")

if not os.path.isfile(os.path.join(FRONTEND_DIST, "index.html")):
    raise SystemExit(
        "frontend/dist/index.html not found — run `npm run build` in "
        "stat-consultant/frontend before building the backend bundle."
    )

# app.main resolves this at runtime via sys._MEIPASS (see frontend_dist()).
datas = [(FRONTEND_DIST, "frontend_dist")]

# The SDKs read their own installed version at import time; without the
# dist-info metadata they raise PackageNotFoundError inside the bundle.
for pkg in ("anthropic", "openai", "keyring"):
    datas += copy_metadata(pkg)

hiddenimports = [
    # keyring discovers backends through entry points, which PyInstaller's
    # static analysis cannot follow. Missing these means BYOK key storage
    # fails at runtime — and it fails per-platform, so a Mac build looks fine
    # while Windows can't save a key at all.
    "keyring.backends.macOS",
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.chainer",
    "keyring.backends.fail",
    "keyring.backends.null",
    # The Windows keyring backend goes through pywin32-ctypes.
    "win32ctypes.core",
    "win32ctypes.core.cffi",
    "win32ctypes.core.ctypes",
    # run_backend.py already pins loop/http/ws so uvicorn's "auto" indirection
    # is bypassed; these stay as belt-and-braces for the concrete impls.
    "uvicorn.logging",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
]

excludes = [
    "watchfiles",  # uvicorn --reload only; never used in the shipped app
    "tkinter",
    "test",
]

a = Analysis(
    [os.path.join(BACKEND_DIR, "run_backend.py")],
    pathex=[BACKEND_DIR],  # so `from app.main import app` resolves
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# onedir, not onefile. onefile re-extracts the whole tree to %TEMP% on every
# launch (seconds of cold start with anthropic+openai+httpx), and self-extraction
# into temp is a classic heuristic trigger for institutional endpoint protection.
# onedir starts fast and lives in a stable directory an admin can whitelist.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="stat-consultant-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed binaries draw extra AV attention; not worth it
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="stat-consultant-backend",
)
