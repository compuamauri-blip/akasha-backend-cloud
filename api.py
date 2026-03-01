from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import subprocess
import re
import platform
import glob

app = FastAPI(title="AKASHA Downloader API Pro", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

progresos_descarga = {}
procesos_activos = {}

class DescargarRequest(BaseModel):
    url: str
    id_video: str
    formato: str
    ruta_base: str
    limite_velocidad: str
    subtitulos: bool
    calidad: str

class DatosCarpeta(BaseModel):
    ruta: str

def asegurar_directorio(ruta_pedida: str) -> str:
    sistema_actual = platform.system()
    if sistema_actual != "Windows":
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ruta_final = os.path.join(base_dir, "downloads")
    else:
        ruta_final = ruta_pedida.replace("/", "\\")

    try:
        os.makedirs(ruta_final, exist_ok=True)
        return ruta_final
    except Exception:
        fallback = os.path.join(os.getcwd(), "downloads")
        os.makedirs(fallback, exist_ok=True)
        return fallback

def ejecutar_ytdlp(req: DescargarRequest):
    progresos_descarga[req.id_video] = 1.0 
    ruta_real = asegurar_directorio(req.ruta_base)
    
    yt_dlp_path = "yt-dlp"
    if platform.system() == "Windows" and os.path.exists("yt-dlp.exe"):
        yt_dlp_path = os.path.abspath("yt-dlp.exe")
    
    plantilla_nombre = f"%(title)s_{req.id_video}.%(ext)s"
    
    comando = [
        yt_dlp_path, 
        "--newline", 
        "--no-colors", 
        "-P", ruta_real, 
        "-o", plantilla_nombre
    ]
    
    if "1080p" in req.calidad:
        comando.extend(["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"])
    elif "720p" in req.calidad:
        comando.extend(["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]"])
        
    if "Audio" in req.formato:
        ext = "mp3" if "MP3" in req.formato else "wav"
        comando.extend(["-x", "--audio-format", ext])
    elif "Original" not in req.formato:
        if "MP4" in req.formato: comando.extend(["--merge-output-format", "mp4"])
        if "MKV" in req.formato: comando.extend(["--merge-output-format", "mkv"])
        
    if "MB/s" in req.limite_velocidad:
        vel = req.limite_velocidad.replace(" ", "")
        comando.extend(["--limit-rate", vel])
        
    if req.subtitulos:
        comando.extend(["--write-subs", "--embed-subs"])
        
    comando.append(req.url)
    
    try:
        process = subprocess.Popen(
            comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, encoding='utf-8', errors='ignore'
        )
        procesos_activos[req.id_video] = process
        
        for line in process.stdout:
            match = re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%', line)
            if match:
                progreso = float(match.group(1))
                # LA MAGIA Y SOLUCIÓN: Congelamos el progreso máximo en 99%
                # El usuario verá 99% mientras el servidor "pega" el video y el audio.
                if progreso >= 99.0:
                    progresos_descarga[req.id_video] = 99.0
                elif progreso > progresos_descarga.get(req.id_video, 0):
                    progresos_descarga[req.id_video] = progreso
                
        process.wait()
        
        # AHORA SÍ: El proceso terminó totalmente. El archivo físico 100% real existe.
        # Le enviamos el 100% a la aplicación web.
        progresos_descarga[req.id_video] = 100.0 if process.returncode == 0 else -1.0
            
    except Exception:
        progresos_descarga[req.id_video] = -1.0
    finally:
        if req.id_video in procesos_activos:
            del procesos_activos[req.id_video]

@app.post("/api/descargar")
async def iniciar_descarga(req: DescargarRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(ejecutar_ytdlp, req)
    return {"mensaje": "Descarga iniciada", "id": req.id_video}

@app.get("/api/progreso/{id_video}")
async def obtener_progreso(id_video: str):
    return {"progreso": progresos_descarga.get(id_video, 0)}

@app.get("/api/cancelar/{id_video}")
async def cancelar_descarga(id_video: str):
    process = procesos_activos.get(id_video)
    if process: process.kill()
    return {"estado": "cancelado"}

@app.get("/api/obtener_archivo/{id_video}")
def obtener_archivo(id_video: str):
    ruta_real = asegurar_directorio("")
    archivos_encontrados = glob.glob(os.path.join(ruta_real, f"*_{id_video}.*"))
    
    if not archivos_encontrados:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
        
    archivo_ruta = archivos_encontrados[0]
    nombre_original = os.path.basename(archivo_ruta)
    nombre_limpio = nombre_original.replace(f"_{id_video}", "")
    
    return FileResponse(
        path=archivo_ruta, 
        filename=nombre_limpio, 
        media_type="application/octet-stream"
    )

@app.get("/api/explorar")
def explorar_carpeta():
    if platform.system() != "Windows":
        return {"ruta": "Almacenamiento Interno (Nube)"}
    return {"ruta": "C:\\Downloads\\AKASHA"}

@app.post("/api/abrir_carpeta")
def abrir_carpeta(datos: DatosCarpeta):
    if platform.system() == "Windows":
        os.startfile(asegurar_directorio(datos.ruta))
        return {"status": "ok"}
    raise HTTPException(status_code=400, detail="Mobile")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)