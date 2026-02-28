from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import subprocess
import re
import tkinter as tk
from tkinter import filedialog
import ctypes

# ==============================================================================
# INICIALIZACIÓN DE LA APLICACIÓN
# ==============================================================================
app = FastAPI(title="AKASHA Downloader API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Memoria temporal para el seguimiento local de descargas
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
# FUNCIONES AUXILIARES Y LÓGICA CORE
# ==============================================================================
def resolver_ruta(ruta: str) -> str:
    """
    Limpia la ruta y aplica un parche salvavidas si detecta la ruta 
    genérica de Windows, enrutándola a la carpeta oficial de AKASHA.
    """
    ruta_limpia = ruta.replace("/", "\\")
    
    rutas_prohibidas = ["C:\\Users\\Downloads", "C:\\Users\\Downloads\\AKASHA"]
    if any(rp in ruta_limpia for rp in rutas_prohibidas):
        ruta_limpia = os.path.join(os.path.expanduser('~'), 'Downloads', 'AKASHA')
        
    return ruta_limpia

def ejecutar_ytdlp(req: DescargarRequest):
    """
    Motor principal de descarga. Ejecuta yt-dlp como un subproceso,
    lee la consola en tiempo real y actualiza el diccionario de progresos.
    """
    progresos_descarga[req.id_video] = 1.0 
    ruta_real = resolver_ruta(req.ruta_base)
    
    # Intentar crear el directorio de destino
    try:
        os.makedirs(ruta_real, exist_ok=True)
    except Exception:
        progresos_descarga[req.id_video] = -1.0  # Arroja error en la web
        return
    
    # Búsqueda dinámica del ejecutable del motor (yt-dlp)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    posibles_rutas = [
        os.path.join(base_dir, "yt-dlp.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "yt-dlp.exe"),
        "yt-dlp.exe",
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
        
        # Leer la salida de consola línea por línea para extraer el porcentaje
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
            progresos_descarga[req.id_video] = -1.0  # Error nativo en yt-dlp
            
    except Exception:
        progresos_descarga[req.id_video] = -1.0
    finally:
        # Limpieza de memoria
        if req.id_video in procesos_activos:
            del procesos_activos[req.id_video]

# ==============================================================================
# ENDPOINTS (RUTAS DE LA API)
# ==============================================================================
@app.post("/api/descargar")
async def iniciar_descarga(req: DescargarRequest, background_tasks: BackgroundTasks):
    """Encola la petición de descarga en un hilo secundario para no bloquear el servidor."""
    background_tasks.add_task(ejecutar_ytdlp, req)
    return {"mensaje": "Descarga iniciada", "id": req.id_video}

@app.get("/api/progreso/{id_video}")
async def obtener_progreso(id_video: str):
    """Retorna el progreso actual (0 a 100, o -1 si hubo error) de una descarga."""
    progreso = progresos_descarga.get(id_video, 0)
    return {"progreso": progreso}

@app.get("/api/cancelar/{id_video}")
async def cancelar_descarga(id_video: str):
    """Mata el subproceso de yt-dlp de forma forzada si el usuario cancela o pausa."""
    process = procesos_activos.get(id_video)
    if process and process.poll() is None:
        process.kill()
        process.wait() # Asegura que el sistema operativo libere los recursos
    return {"estado": "cancelado"}

@app.get("/api/explorar")
def explorar_carpeta():
    """Abre el explorador de archivos nativo de Windows usando Tkinter."""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        ruta = filedialog.askdirectory(title="Selecciona la carpeta de destino de AKASHA")
        root.destroy()
        
        if ruta:
            return {"ruta": ruta.replace("/", "\\")}
        return {"ruta": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/abrir_carpeta")
def abrir_carpeta(datos: DatosCarpeta):
    """Abre la ruta en el explorador de Windows y la trae al frente."""
    try:
        ruta_real = resolver_ruta(datos.ruta)
        os.makedirs(ruta_real, exist_ok=True)
        
        # TRUCO NINJA PARA WINDOWS: Simulamos presionar y soltar la tecla ALT (0x12)
        # Esto engaña a Windows haciéndole creer que estamos interactuando,
        # lo que desactiva el bloqueo y fuerza a la carpeta a saltar al frente.
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0) # Presiona ALT
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0) # Suelta ALT
        
        os.startfile(ruta_real) 
        return {"estado": "exito"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))