"""
DescribeAI - Backend con Groq API (GRATIS)
Genera descripciones de productos con Llama 3.3
Envío de emails con Resend
Sistema de códigos de acceso con SQLite
Deploy en Railway
"""

from fastapi import FastAPI, UploadFile, Form, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from groq import Groq
import pandas as pd
import io
import base64
import os
import time
import sqlite3
import uuid
import resend

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "codes.db")

# ---------- Límites por tipo de código ----------
LIMITES = {
    "basic":    50,
    "standard": 200,
    "premium":  1000,
}

PREFIJOS = {
    "basic":    "BASIC",
    "standard": "STD",
    "premium":  "PREM",
}

# ---------- Base de datos ----------
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS codes (
            code       TEXT PRIMARY KEY,
            type       TEXT NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    con.close()

init_db()


def get_code(code: str):
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT code, type, used FROM codes WHERE code = ?", (code,)).fetchone()
    con.close()
    return row  # (code, type, used) o None


def mark_used(code: str):
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE codes SET used = 1 WHERE code = ?", (code,))
    con.commit()
    con.close()


# ---------- App ----------
app = FastAPI()

# Respeta X-Forwarded-Proto de Railway para que las URLs internas usen https://
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_KEY = os.getenv("GROQ_API_KEY")
resend.api_key = os.getenv("RESEND_API_KEY")
FROM_EMAIL = "DescribeAI <onboarding@resend.dev>"


# ---------- Endpoints ----------
@app.get("/")
async def root():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))

@app.get("/admin")
async def admin():
    return FileResponse(os.path.join(BASE_DIR, "static", "admin.html"))


@app.get("/generate-code")
async def generate_code(type: str = "basic"):
    type = type.lower()
    if type not in LIMITES:
        raise HTTPException(400, detail=f"Tipo inválido. Usá: {', '.join(LIMITES.keys())}")

    prefijo = PREFIJOS[type]
    sufijo  = uuid.uuid4().hex[:6].upper()
    code    = f"{prefijo}-{sufijo}"

    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT INTO codes (code, type) VALUES (?, ?)", (code, type))
    con.commit()
    con.close()

    return {
        "code":  code,
        "type":  type,
        "limit": LIMITES[type],
    }


@app.post("/procesar")
async def procesar(
    background_tasks: BackgroundTasks,
    file:        UploadFile = None,
    email:       str = Form(...),
    storeName:   str = Form("Mi Tienda"),
    tone:        str = Form("profesional"),
    lang:        str = Form("es"),
    access_code: str = Form(...),
):
    # --- Validar código ---
    code_upper = access_code.strip().upper()
    row = get_code(code_upper)

    if row is None:
        raise HTTPException(400, detail="Código inválido. Verificá que sea correcto.")

    _, code_type, used = row

    if used:
        raise HTTPException(400, detail="Este código ya fue usado. Cada código es de un solo uso.")

    limite = LIMITES[code_type]

    # --- Validar cantidad de productos ---
    contenido = await file.read()
    df = pd.read_csv(io.BytesIO(contenido))
    df.columns = [c.lower().strip() for c in df.columns]

    if 'nombre' not in df.columns:
        raise HTTPException(400, detail="El CSV no tiene una columna 'nombre'.")

    df = df.dropna(subset=['nombre'])
    df = df[df['nombre'].str.strip() != '']

    if len(df) > limite:
        raise HTTPException(400, detail=f"Tu plan {code_type} permite hasta {limite} productos. Tu CSV tiene {len(df)}.")

    # --- Marcar como usado y procesar ---
    mark_used(code_upper)
    background_tasks.add_task(procesar_csv, contenido, email, storeName, tone, lang)
    return {"status": "ok", "message": f"Procesando {len(df)} productos. Te llega por email en minutos."}


# ---------- Lógica de procesamiento ----------
def generar_descripcion(producto: dict, tono: str, idioma: str) -> str:
    client = Groq(api_key=GROQ_KEY)
    prompt = f"""Sos un copywriter experto en eCommerce.
Genera una descripcion de producto atractiva en tono {tono}.
Idioma: {idioma}

Producto:
- Nombre: {producto.get('nombre', '')}
- Categoria: {producto.get('categoria', '')}
- Caracteristicas: {producto.get('caracteristicas', '')}

Reglas ESTRICTAS:
- Maximo 100 palabras
- Solo usa la info dada, no inventes nada
- Sin tildes, sin acentos, sin caracteres especiales
- Usa unicamente letras a-z, numeros y puntuacion basica
- Envolvé las palabras clave importantes del producto en etiquetas <b>
- Solo la descripcion, sin titulos ni explicaciones"""

    for intento in range(3):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception:
            if intento < 2:
                time.sleep(3)
    return "Error: no se pudo generar la descripcion"


def procesar_csv(contenido: bytes, email: str, tienda: str, tono: str, idioma: str):
    """Procesa el CSV completo y envía el resultado por email."""
    try:
        df = pd.read_csv(io.BytesIO(contenido))
        df.columns = [c.lower().strip() for c in df.columns]
        df = df.dropna(subset=['nombre'])
        df = df[df['nombre'].str.strip() != '']

        descripciones = []
        for _, row in df.iterrows():
            desc = generar_descripcion(row.to_dict(), tono, idioma)
            descripciones.append(desc)

        df['descripcion_generada'] = descripciones

        output = io.BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig', errors='replace')
        output.seek(0)

        enviar_csv(email, tienda, output.read())

    except Exception as e:
        enviar_error(email, str(e))


def enviar_csv(email_destino: str, tienda: str, csv_bytes: bytes):
    """Envía el CSV procesado por email usando Resend."""
    csv_base64 = base64.b64encode(csv_bytes).decode("utf-8")

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 560px; margin: 0 auto;">
      <h2>✅ Tus descripciones están listas</h2>
      <p>Hola,</p>
      <p>Adjunto encontrás el CSV con la columna <strong>descripcion_generada</strong>
      para tu tienda <strong>{tienda}</strong>.</p>
      <p>Solo copiá y pegá cada descripción en tu tienda.</p>
      <p>Gracias por usar DescribeAI 🚀</p>
    </div>
    """

    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": email_destino,
        "subject": f"✅ DescribeAI — Tus descripciones para {tienda} están listas",
        "html": html,
        "attachments": [{
            "filename": f"descripciones_{tienda}.csv",
            "content": csv_base64,
        }],
    })


def enviar_error(email_destino: str, error: str):
    """Notifica al cliente si algo falló."""
    html = f"""
    <div style="font-family: -apple-system, sans-serif;">
      <h2>❌ Hubo un problema con tu pedido</h2>
      <p>Ocurrió un error procesando tu archivo:</p>
      <pre style="background:#f5f5f5;padding:10px;border-radius:6px;">{error}</pre>
      <p>Por favor contactanos.</p>
    </div>
    """

    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": email_destino,
        "subject": "DescribeAI — Hubo un problema con tu pedido",
        "html": html,
    })
