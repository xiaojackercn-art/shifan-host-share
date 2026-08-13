from __future__ import annotations
import shutil, subprocess, sys
from pathlib import Path
src=Path(sys.argv[1]); dst=Path(sys.argv[2]); found=list(src.rglob("deskflow-core.exe"))
if not found: raise SystemExit("deskflow-core.exe not found in downloaded Deskflow package")
core=found[0]; root=core.parent
if dst.exists(): shutil.rmtree(dst)
shutil.copytree(root,dst); print("Deskflow engine root:",root); print("Files:",len(list(dst.rglob('*'))))
res=subprocess.run([str(dst/'deskflow-core.exe'),'--version'],capture_output=True,text=True,timeout=20); print("deskflow-core --version:",res.stdout,res.stderr)
if res.returncode!=0: raise SystemExit(f"deskflow-core version check failed: {res.returncode}")
