from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import subprocess
import re
import platform
import glob

app = FastAPI(title="AKASHA Downloader API Pro", version="1.4")

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

def asegurar_directorio():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ruta_final = os.path.join(base_dir, "downloads")
    os.makedirs(ruta_final, exist_ok=True)
    return ruta_final

def ejecutar_ytdlp(req: DescargarRequest):
    progresos_descarga[req.id_video] = 1.0 
    ruta_real = asegurar_directorio()
    
    yt_dlp_path = "yt-dlp"
    
    # TRUCO 1: Nombramos el archivo SOLO con su ID para que no se pierda jamás.
    plantilla_nombre = f"{req.id_video}.%(ext)s"
    
    comando = [
        yt_dlp_path, 
        "--newline", 
        "--no-colors", 
        "-P", ruta_real, 
        "-o", plantilla_nombre
    ]
    
    # TRUCO 2 (LA SALVACIÓN): Obligamos a descargar archivos pre-ensamblados. 
    # Esto evita usar FFmpeg y evita que Render se quede sin memoria RAM y mate el archivo.
    if "Audio" in req.formato:
        comando.extend(["-f", "bestaudio", "-x", "--audio-format", "mp3"])
    else:
        comando.extend(["-f", "best[ext=mp4]/best"]) 
        
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
                if progreso >= 99.0:
                    progresos_descarga[req.id_video] = 99.0
                else:
                    progresos_descarga[req.id_video] = progreso
                
        process.wait()
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
    ruta_real = asegurar_directorio()
    # Busca exactamente el archivo con el ID
    archivos_encontrados = glob.glob(os.path.join(ruta_real, f"{id_video}.*"))
    
    if not archivos_encontrados:
        raise HTTPException(status_code=404, detail="Archivo no encontrado por limite de memoria RAM en Render.")
        
    archivo_ruta = archivos_encontrados[0]
    extension = archivo_ruta.split('.')[-1]
    nombre_limpio = f"Akasha_Media_Download.{extension}"
    
    return FileResponse(
        path=archivo_ruta, 
        filename=nombre_limpio, 
        media_type="application/octet-stream"
    )