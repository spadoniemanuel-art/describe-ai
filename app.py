"""
DescribeAI - Backend con Groq API (GRATIS)
Genera descripciones de productos con Llama 3.3
Envío de emails con Resend
Deploy en Railway
"""

from fastapi import FastAPI, UploadFile, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from groq import Groq
import pandas as pd
import io
import base64
import os
import resend

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))

GROQ_KEY = os.getenv("GROQ_API_KEY")
resend.api_key = os.getenv("RESEND_API_KEY")

FROM_EMAIL = "DescribeAI <onboarding@resend.dev>"


def generar_descripcion(producto: dict, tono: str, idioma: str) -> str:
    """Llama a Groq API para generar una descripción."""
    client = Groq(api_key=GROQ_KEY)

    prompt = f"""Sos un copywriter experto en eCommerce.
Generá UNA descripción de producto atractiva, optimizada para SEO, en tono {tono}.
Idioma: {idioma}

Producto:
- Nombre: {producto.get('nombre', '')}
- Categoría: {producto.get('categoria', '')}
- Características: {producto.get('caracteristicas', '')}

Reglas ESTRICTAS:
- Máximo 100 palabras
- Solo usá la info que te di, no inventes nada
- Incluí 2 beneficios clave
- Terminá con una frase de acción sutil
- Respondé SOLO con la descripción, sin explicaciones"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.7
    )

    texto = response.choices[0].message.content.strip()
    return texto.encode('latin-1', errors='ignore').decode('utf-8', errors='ignore')


def procesar_csv(contenido: bytes, email: str, tienda: str, tono: str, idioma: str):
    """Procesa el CSV completo y envía el resultado por email."""
    try:
        df = pd.read_csv(io.BytesIO(contenido))
        df.columns = [c.lower().strip() for c in df.columns]

        if 'nombre' not in df.columns:
            enviar_error(email, "El CSV no tiene una columna 'nombre'")
            return

        descripciones = []
        for _, row in df.iterrows():
            desc = generar_descripcion(row.to_dict(), tono, idioma)
            descripciones.append(desc)

        df['descripcion_generada'] = descripciones

        # Guardar CSV resultado
        output = io.BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig', errors='replace')
        output.seek(0)

        # Enviar por email
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


@app.post("/procesar")
async def procesar(
    background_tasks: BackgroundTasks,
    file:      UploadFile = None,
    email:     str = Form(...),
    storeName: str = Form("Mi Tienda"),
    tone:      str = Form("profesional"),
    lang:      str = Form("es")
):
    contenido = await file.read()
    background_tasks.add_task(procesar_csv, contenido, email, storeName, tone, lang)
    return {"status": "ok", "message": "Procesando, te llega por email en minutos"}
