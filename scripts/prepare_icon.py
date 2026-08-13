from __future__ import annotations
import io, shutil, time, urllib.request
from pathlib import Path
from PIL import Image
ICON_URL="https://i.ibb.co/nMzmgBR7/AI.png"
ROOT=Path(__file__).resolve().parents[1]; ASSETS=ROOT/"assets"; WEB=ROOT/"src"/"shifan_host_share"/"web"
def download_with_retry()->Image.Image:
    last=None
    for attempt in range(1,5):
        try:
            req=urllib.request.Request(ICON_URL,headers={"User-Agent":"Mozilla/5.0 ShifanAI-HostShare/0.2 Builder","Accept":"image/avif,image/webp,image/png,image/*,*/*;q=0.8"})
            with urllib.request.urlopen(req,timeout=120) as response: data=response.read()
            img=Image.open(io.BytesIO(data)).convert("RGBA")
            if img.width<64 or img.height<64: raise ValueError(f"图标尺寸异常 {img.size}")
            return img
        except Exception as exc:
            last=exc; print(f"Icon download attempt {attempt}/4 failed: {exc}"); time.sleep(attempt*3)
    raise RuntimeError(f"无法下载用户指定图标 {ICON_URL}: {last}")
def main()->None:
    ASSETS.mkdir(exist_ok=True); img=download_with_retry(); print(f"Using exact user icon: {ICON_URL} ({img.width}x{img.height})")
    square=Image.new("RGBA",(1024,1024),(0,0,0,0)); copy=img.copy(); copy.thumbnail((1024,1024),Image.Resampling.LANCZOS); square.alpha_composite(copy,((1024-copy.width)//2,(1024-copy.height)//2))
    square.save(ASSETS/"AI.png"); square.save(ASSETS/"AI.ico",format="ICO",sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]); square.save(ASSETS/"AI.icns",format="ICNS"); shutil.copy2(ASSETS/"AI.png",WEB/"AI.png")
if __name__=="__main__": main()
