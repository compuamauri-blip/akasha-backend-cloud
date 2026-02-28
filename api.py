from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import subprocess
import re

# ==============================================================================
# INICIALIZACIÓN DE LA APLICACIÓN (VERSIÓN NUBE/MÓVIL)
# ==============================================================================
app = FastAPI(title="AKASHA Downloader Cloud API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Memoria temporal para el seguimiento de descargas en el servidor
progresos_descarga = {}
procesos_activos = {}

# ==============================================================================
# MODELOS DE DATOS (Pydantic)
# ==============================================================================
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

# ==============================================================================
# FUNCIONES AUXILIARES Y LÓGICA CORE PARA LA NUBE
# ==============================================================================
def resolver_ruta_nube() -> str:
    """
    En la nube no hay disco C:. Todo se descarga temporalmente en una 
    carpeta 'downloads' dentro del mismo servidor Linux antes de ir al celular.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ruta_descargas = os.path.join(base_dir, "downloads")
    os.makedirs(ruta_descargas, exist_ok=True)
    return ruta_descargas

def ejecutar_ytdlp(req: DescargarRequest):
    """
    Motor principal de descarga. Ejecuta yt-dlp en el servidor Linux.
    """
    progresos_descarga[req.id_video] = 1.0 
    ruta_real = resolver_ruta_nube()
    
    # Búsqueda dinámica del ejecutable (En Linux suele llamarse yt-dlp sin .exe)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    posibles_rutas = [
        os.path.join(base_dir, "yt-dlp"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "yt-dlp"),
        "yt-dlp"
    ]
    
    yt_dlp_path = "yt-dlp"
    for r in posibles_rutas:
        if os.path.exists(r):
            yt_dlp_path = r
            break
            
    # Construcción del comando base
    comando = [
        yt_dlp_path, 
        "--newline", 
        "--no-colors", 
        "-P", ruta_real, 
        "-o", "%(title)s.%(ext)s"
    ]
    
    # Configuración de Calidad
    if "1080p" in req.calidad:
        comando.extend(["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"])
    elif "720p" in req.calidad:
        comando.extend(["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]"])
        
    # Configuración de Formato
    if "Audio" in req.formato:
        ext = req.formato.split("(")[-1].replace(")", "").lower()
        comando.extend(["-x", "--audio-format", ext])
    elif "Original" not in req.formato:
        ext = req.formato.split("(")[-1].replace(")", "").lower()
        comando.extend(["--merge-output-format", ext])
        
    # Límite de Velocidad
    if "MB/s" in req.limite_velocidad:
        vel = req.limite_velocidad.replace(" ", "")
        comando.extend(["--limit-rate", vel])
        
    # Subtítulos
    if req.subtitulos:
        comando.extend(["--write-subs", "--embed-subs"])
        
    comando.append(req.url)
    
    # Ejecución y Monitoreo del Subproceso
    try:
        process = subprocess.Popen(
            comando, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True, 
            encoding='utf-8', 
            errors='ignore'
        )
        procesos_activos[req.id_video] = process
        
        for line in process.stdout:
            match = re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%', line)
            if match:
                progreso = float(match.group(1))
                if progreso > progresos_descarga.get(req.id_video, 0):
                    progresos_descarga[req.id_video] = progreso
                
        process.wait()
        
        if process.returncode == 0:
            progresos_descarga[req.id_video] = 100.0
        else:
            progresos_descarga[req.id_video] = -1.0  # Error en yt-dlp
            
    except Exception:
        progresos_descarga[req.id_video] = -1.0
    finally:
        if req.id_video in procesos_activos:
            del procesos_activos[req.id_video]

# ==============================================================================
# ENDPOINTS (RUTAS DE LA API)
# ==============================================================================
@app.post("/api/descargar")
async def iniciar_descarga(req: DescargarRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(ejecutar_ytdlp, req)
    return {"mensaje": "Descarga en servidor iniciada", "id": req.id_video}

@app.get("/api/progreso/{id_video}")
async def obtener_progreso(id_video: str):
    progreso = progresos_descarga.get(id_video, 0)
    return {"progreso": progreso}

@app.get("/api/cancelar/{id_video}")
async def cancelar_descarga(id_video: str):
    process = procesos_activos.get(id_video)
    if process and process.poll() is None:
        process.kill()
        process.wait() 
    return {"estado": "cancelado"}

@app.get("/api/explorar")
def explorar_carpeta():
    """Adaptación para la nube: Devuelve una ruta virtual estática."""
    return {"ruta": "Almacenamiento Interno (Nube)"}

@app.post("/api/abrir_carpeta")
def abrir_carpeta(datos: DatosCarpeta):
    """Adaptación para la nube: En el celular no se pueden abrir carpetas de Windows."""
    raise HTTPException(status_code=400, detail="En la versión móvil, los archivos se descargan directo a tu celular.")