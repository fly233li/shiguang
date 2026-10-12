"""Package the verified folder build and its editable application source."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from timelight import __version__
bundle = ROOT / "dist" / __version__ / "Shiguang"
assert (bundle / "Shiguang.exe").is_file(), "Run build.ps1 first"
source = bundle / "source"
source.mkdir(exist_ok=True)
for name in ["main.py", "README.md", "VALIDATION.md", "AGENTS.md", "requirements.txt", "requirements-dev.txt", "build.ps1", "THIRD_PARTY_NOTICES.md"]:
    shutil.copy2(ROOT / name, source / name)
for name in ["timelight", "tests", "tools", "assets", "licenses"]:
    shutil.copytree(ROOT/name,source/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns(
        "__pycache__","*.pyc","*.sqlite*","*.db","*.db-wal","*.db-shm","backups"))
# Never ship a usage database that a future overwrite could put over user data.
# Fail instead of deleting suspicious files from a developer's bundle.
files = sorted(p for p in bundle.rglob("*") if p.is_file())
unsafe = [p.relative_to(bundle).as_posix() for p in files
          if any(part.casefold() == "backups" for part in p.relative_to(bundle).parts)
          or ".sqlite" in p.name.casefold()
          or p.name.casefold().endswith((".db", ".db-wal", ".db-shm"))]
if unsafe:
    raise RuntimeError("发布目录包含数据库或备份，已取消打包：" + ", ".join(unsafe))
release = ROOT / "release"
release.mkdir(exist_ok=True)
archive = release / f"时光计-{__version__}-Windows-x64.zip"
with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in files:
        z.write(p, p.relative_to(bundle.parent))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
(release/"SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n",encoding="utf-8")
print(json.dumps({"archive":str(archive),"bytes":archive.stat().st_size,"sha256":digest},ensure_ascii=False))
