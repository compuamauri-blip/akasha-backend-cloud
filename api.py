from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import subprocess
import re
import platform
import glob

# =========================================================================
# ESCUDO ANTI-BLOQUEOS: Auto-actualiza el motor cada vez que el servidor despierta
# para evadir la seguridad diaria de YouTube e Instagram.
# =========================================================================
print("Actualizando yt-dlp para evadir bloqueos...")
os.system("python -m pip install -U yt-dlp")

app = FastAPI(title="AKASHA Downloader API Pro", version="1.5")

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
    plantilla_nombre = f"{req.id_video}.%(ext)s"
    
    comando = [
        yt_dlp_path, 
        "--newline", 
        "--no-colors", 
        "--no-warnings",
        "--force-ipv4", # TRUCO VITAL: Fuerza la conexión como un usuario normal para evitar que la IP de Render sea congelada.
        "-P", ruta_real, 
        "-o", plantilla_nombre
    ]
    
    # Se descargan formatos pre-ensamblados para que la memoria RAM de Render no colapse
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
                
        # Le damos un tiempo máximo de 10 minutos para evitar que el servidor se quede trabado para siempre
        process.wait(timeout=600)
        progresos_descarga[req.id_video] = 100.0 if process.returncode == 0 else -1.0
            
    except Exception as e:
        print(f"Error fatal: {str(e)}")
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
    if process: 
        process.kill()
    progresos_descarga[id_video] = -1.0
    return {"estado": "cancelado"}

@app.get("/api/obtener_archivo/{id_video}")
def obtener_archivo(id_video: str):
    ruta_real = asegurar_directorio()
    archivos_encontrados = glob.glob(os.path.join(ruta_real, f"{id_video}.*"))
    
    if not archivos_encontrados:
        raise HTTPException(status_code=404, detail="Archivo no encontrado en el servidor.")
        
    archivo_ruta = archivos_encontrados[0]
    extension = archivo_ruta.split('.')[-1]
    nombre_limpio = f"Akasha_Media_Download.{extension}"
    
    return FileResponse(
        path=archivo_ruta, 
        filename=nombre_limpio, 
        media_type="application/octet-stream"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)