"""
DescribeAI - Backend con Groq API (GRATIS)
Genera descripciones de productos con Llama 3.3
Deploy en Railway
"""

from fastapi import FastAPI, UploadFile, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from groq import Groq
import pandas as pd
import io
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/", StaticFiles(directory="static", html=True), name="static")

GROQ_KEY   = os.getenv("GROQ_API_KEY")       # Ya tenés esta key del bot!
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")


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

    return response.choices[0].message.content.strip()


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
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)

        # Enviar por email
        enviar_csv(email, tienda, output.read())

    except Exception as e:
        enviar_error(email, str(e))


def enviar_csv(email_destino: str, tienda: str, csv_bytes: bytes):
    """Envía el CSV procesado por email."""
    msg = MIMEMultipart()
    msg['From']    = GMAIL_USER
    msg['To']      = email_destino
    msg['Subject'] = f"✅ DescribeAI — Tus descripciones para {tienda} están listas"

    body = MIMEText(f"""
Hola,

Tus descripciones están listas. Encontrás el CSV adjunto con la columna 'descripcion_generada'.

Solo copiá y pegá cada descripción en tu tienda.

Gracias por usar DescribeAI 🚀
    """, 'plain')
    msg.attach(body)

    adjunto = MIMEBase('application', 'octet-stream')
    adjunto.set_payload(csv_bytes)
    encoders.encode_base64(adjunto)
    adjunto.add_header('Content-Disposition', f'attachment; filename="descripciones_{tienda}.csv"')
    msg.attach(adjunto)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, email_destino, msg.as_string())


def enviar_error(email_destino: str, error: str):
    """Notifica al cliente si algo falló."""
    msg = MIMEMultipart()
    msg['From']    = GMAIL_USER
    msg['To']      = email_destino
    msg['Subject'] = "DescribeAI — Hubo un problema con tu pedido"
    body = MIMEText(f"Ocurrió un error: {error}\nPor favor contactanos.", 'plain')
    msg.attach(body)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, email_destino, msg.as_string())


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
