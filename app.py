"""
DescribeAI SaaS — Backend
OpenRouter (Llama 3.3 70B) + MercadoPago Checkout Pro + Resend + SQLite
Deploy en Railway
"""

from fastapi import FastAPI, UploadFile, Form, BackgroundTasks, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from openai import OpenAI, RateLimitError as OpenAIRateLimitError
import mercadopago
import pandas as pd
import io
import base64
import os
import time
import sqlite3
import hashlib
import hmac
import uuid
import secrets
import re
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import resend

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("describeai")

# ── Concurrencia — Modo Fórmula 1 (OpenRouter, plan pago) ────────────────────
AI_SEMAPHORE   = threading.Semaphore(10)   # 10 llamadas simultáneas máximo
AI_MAX_WORKERS = 10                         # hilos por job de CSV
AI_MODEL       = "meta-llama/llama-3.3-70b-instruct"

# ── Pre-traducción de nombres de producto (evita confusión en el LLM) ─────────
_TRAD_PT = {
    "Taladro Inalámbrico": "Furadeira sem fio",
    "Taladro":             "Furadeira",
    "Martillo de Carpintero": "Martelo de carpinteiro",
    "Martillo":            "Martelo",
    "Cinta Métrica":       "Trena",
    "Llave Inglesa Ajustable": "Chave inglesa ajustável",
    "Llave Inglesa":       "Chave inglesa",
    "Nivel de Burbuja":    "Nível de bolha",
    "Parlante":            "Caixa de som",
    "Bocina":              "Alto-falante",
}
_TRAD_FR = {
    "Taladro Inalámbrico": "Perceuse sans fil",
    "Taladro":             "Perceuse",
    "Martillo de Carpintero": "Marteau de charpentier",
    "Martillo":            "Marteau",
    "Cinta Métrica":       "Mètre ruban",
    "Llave Inglesa Ajustable": "Clé à molette ajustable",
    "Llave Inglesa":       "Clé à molette",
    "Nivel de Burbuja":    "Niveau à bulle",
    "Parlante":            "Haut-parleur",
    "Bocina":              "Haut-parleur",
}
_TRAD_EN = {
    "Taladro Inalámbrico": "Cordless Drill",
    "Taladro":             "Drill",
    "Martillo de Carpintero": "Carpenter's Hammer",
    "Martillo":            "Hammer",
    "Cinta Métrica":       "Tape Measure",
    "Llave Inglesa Ajustable": "Adjustable Wrench",
    "Llave Inglesa":       "Wrench",
    "Nivel de Burbuja":    "Spirit Level",
    "Parlante":            "Speaker",
    "Bocina":              "Speaker",
}
_TRAD_MAP = {"pt": _TRAD_PT, "fr": _TRAD_FR, "en": _TRAD_EN}

def _traducir_nombre(nombre: str, idioma: str) -> str:
    """Pre-traduce el nombre del producto antes de enviarlo al LLM."""
    for es, trad in _TRAD_MAP.get(idioma, {}).items():
        nombre = nombre.replace(es, trad)
    return nombre

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# En Railway: configurar variable de entorno DATABASE_PATH=/data/codes.db
# y montar un volumen en /data para persistencia entre deploys.
# Si no se configura, usa el directorio local (modo desarrollo).
DB_PATH = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "codes.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
OPENROUTER_KEY  = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD", "admin123")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
SITE_URL        = os.getenv("SITE_URL", "https://describeai.store")
resend.api_key  = os.getenv("RESEND_API_KEY")
FROM_EMAIL      = "DescribeAI <soporte@describeai.store>"
REPLY_TO        = "spadoni.emanuel@gmail.com"

def get_sdk():
    token = os.getenv("MP_ACCESS_TOKEN", "")
    if not token:
        raise HTTPException(500, detail="MP_ACCESS_TOKEN no configurado en Railway")
    return mercadopago.SDK(token)

# ── Planes ─────────────────────────────────────────────────────────────────────
PLANES = {
    "basic":    {"nombre": "Inicial",     "productos": 50,   "precio": 5000,  "code_type": "basic"},
    "standard": {"nombre": "Crecimiento", "productos": 200,  "precio": 15000, "code_type": "standard"},
    "premium":  {"nombre": "Corporativo", "productos": 1000, "precio": 35000, "code_type": "premium"},
}
LIMITES  = {"basic": 50, "standard": 200, "premium": 1000}
PREFIJOS = {"basic": "BASIC", "standard": "STD", "premium": "PREM"}

# ── Base de datos ──────────────────────────────────────────────────────────────
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
    con.execute("""
        CREATE TABLE IF NOT EXISTS free_trials (
            ip         TEXT PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            reference_id TEXT PRIMARY KEY,
            plan         TEXT NOT NULL,
            payment_id   TEXT,
            code         TEXT,
            buyer_email  TEXT,
            status       TEXT NOT NULL DEFAULT 'pending',
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Migración segura: agrega buyer_email si ya existía la tabla sin esa columna
    try:
        con.execute("ALTER TABLE payments ADD COLUMN buyer_email TEXT")
    except sqlite3.OperationalError:
        pass  # ya existe, ignorar
    con.commit()
    con.close()

init_db()


def get_code(code: str):
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT code, type, used FROM codes WHERE code = ?", (code,)).fetchone()
    con.close()
    return row


def mark_used(code: str):
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE codes SET used = 1 WHERE code = ?", (code,))
    con.commit()
    con.close()


def create_access_code(plan: str) -> str:
    code_type = PLANES[plan]["code_type"]
    code = f"{PREFIJOS[code_type]}-{uuid.uuid4().hex[:6].upper()}"
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT INTO codes (code, type) VALUES (?, ?)", (code, code_type))
    con.commit()
    con.close()
    return code


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BACKUP_ADMIN_PASSWORD = "describeai2026"

def make_admin_token() -> str:
    """Token determinístico — no necesita memoria compartida entre instancias."""
    secret = (ADMIN_PASSWORD + BACKUP_ADMIN_PASSWORD).encode()
    return hmac.new(secret, b"admin-session", hashlib.sha256).hexdigest()

def valid_admin_cookie(token: str) -> bool:
    return token == make_admin_token()


# ── Páginas estáticas ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.get("/success")
async def success_page():
    return FileResponse(os.path.join(BASE_DIR, "static", "success.html"))



@app.get("/admin")
async def admin(request: Request):
    token = request.cookies.get("admin_session")
    if token and valid_admin_cookie(token):
        return FileResponse(os.path.join(BASE_DIR, "static", "admin.html"))
    return FileResponse(os.path.join(BASE_DIR, "static", "login.html"))


@app.post("/admin/login")
async def admin_login(response: Response, request: Request):
    try:
        body = await request.json()
        password = body.get("password", "")
    except Exception:
        password = ""
    if password != ADMIN_PASSWORD and password != BACKUP_ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    token = make_admin_token()
    response.set_cookie(key="admin_session", value=token, httponly=True, samesite="lax", max_age=60*60*24*7)
    return {"status": "ok"}


@app.post("/admin/logout")
async def admin_logout(response: Response):
    response.delete_cookie("admin_session")
    return RedirectResponse("/admin", status_code=302)


@app.get("/admin/stats")
async def admin_stats(key: str = ""):
    """Endpoint de estadísticas. Requiere ?key=ADMIN_PASSWORD"""
    if key != ADMIN_PASSWORD:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    con = sqlite3.connect(DB_PATH)
    try:
        # Pruebas gratis
        trials = con.execute(
            "SELECT ip, created_at FROM free_trials ORDER BY rowid DESC"
        ).fetchall()

        # Códigos por plan
        codes_summary = con.execute("""
            SELECT plan,
                   COUNT(*) as total,
                   SUM(CASE WHEN used=1 THEN 1 ELSE 0 END) as usados
            FROM codes
            GROUP BY plan
        """).fetchall()

        # Últimos 10 usos de códigos
        recent_uses = con.execute("""
            SELECT code, plan, used_at
            FROM codes
            WHERE used=1
            ORDER BY used_at DESC
            LIMIT 10
        """).fetchall()

    finally:
        con.close()

    return {
        "pruebas_gratis": {
            "total": len(trials),
            "ips": [{"ip": r[0], "fecha": r[1]} for r in trials],
        },
        "codigos": [
            {"plan": r[0], "total": r[1], "usados": r[2], "disponibles": r[1] - r[2]}
            for r in codes_summary
        ],
        "ultimos_usos": [
            {"codigo": r[0], "plan": r[1], "fecha": r[2]}
            for r in recent_uses
        ],
    }


# ── MercadoPago ────────────────────────────────────────────────────────────────
@app.post("/create-preference")
async def create_preference(plan: str = Form(...)):
    if plan not in PLANES:
        raise HTTPException(400, detail="Plan inválido")

    sdk = get_sdk()
    p   = PLANES[plan]
    ref = str(uuid.uuid4())

    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT INTO payments (reference_id, plan) VALUES (?, ?)", (ref, plan))
    con.commit()
    con.close()

    result = sdk.preference().create({
        "items": [{
            "title":       f"DescribeAI — Plan {p['nombre']} ({p['productos']} productos)",
            "quantity":    1,
            "unit_price":  float(p["precio"]),
            "currency_id": "ARS",
        }],
        "external_reference": ref,
        "back_urls": {
            "success": f"{SITE_URL}/success?ref={ref}",
            "failure": f"{SITE_URL}/?error=1",
            "pending": f"{SITE_URL}/success?ref={ref}",
        },
        "auto_return":          "approved",
        "notification_url":     f"{SITE_URL}/webhook",
        "statement_descriptor": "DESCRIBEAI",
    })

    logger.info(f"[MP] status={result['status']} response={result['response']}")

    if result["status"] != 201:
        mp_error = result.get("response", {})
        raise HTTPException(500, detail=f"MP error {result['status']}: {mp_error}")

    resp = result["response"]
    return {
        "init_point":        resp["init_point"],
        "mobile_init_point": resp.get("mobile_init_point", resp["init_point"]),
        "reference":         ref,
    }


@app.post("/webhook")
async def webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    payment_id = (body.get("data") or {}).get("id") or request.query_params.get("id")
    topic      = body.get("type") or request.query_params.get("topic") or request.query_params.get("type")

    if topic not in ("payment",) and str(topic) != "payment":
        return {"status": "ignored", "topic": topic}

    if not payment_id:
        return {"status": "no_payment_id"}

    info = get_sdk().payment().get(payment_id)
    if info["status"] != 200:
        return {"status": "error_fetching_payment"}

    payment  = info["response"]
    p_status = payment.get("status")
    ref      = payment.get("external_reference")

    if p_status != "approved" or not ref:
        return {"status": "not_approved", "payment_status": p_status}

    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT status, plan FROM payments WHERE reference_id = ?", (ref,)).fetchone()

    if not row:
        con.close()
        return {"status": "reference_not_found"}

    if row[0] == "approved":
        con.close()
        return {"status": "already_processed"}

    plan        = row[1]
    buyer_email = (payment.get("payer") or {}).get("email", "")
    code        = create_access_code(plan)

    con.execute(
        "UPDATE payments SET status='approved', payment_id=?, code=?, buyer_email=? WHERE reference_id=?",
        (str(payment_id), code, buyer_email, ref)
    )
    con.commit()
    con.close()

    # Enviar código por email al comprador como backup
    if buyer_email:
        plan_label = {"basic": "Inicial (50 prod)", "standard": "Crecimiento (200 prod)", "premium": "Corporativo (1000 prod)"}.get(plan, plan)
        try:
            resend.Emails.send({
                "from":     FROM_EMAIL,
                "to":       buyer_email,
                "reply_to": REPLY_TO,
                "subject":  "✅ DescribeAI — Tu código de acceso",
                "html": f"""
                <div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto;background:#07071a;color:#e0e0e0;padding:40px;border-radius:16px;">
                  <h2 style="color:#fff;">¡Tu pago fue exitoso! 🎉</h2>
                  <p>Gracias por comprar DescribeAI — <strong>{plan_label}</strong>.</p>
                  <p style="margin-top:20px;">Tu código de acceso es:</p>
                  <div style="background:#1a1a2e;border:2px solid #4f8ef7;border-radius:12px;padding:24px;margin:20px 0;text-align:center;">
                    <span style="font-family:monospace;font-size:2rem;font-weight:900;letter-spacing:4px;color:#4f8ef7;">{code}</span>
                  </div>
                  <p style="color:#aaa;font-size:0.85rem;">Guardá este email. Si perdés el código, respondé este email y te ayudamos.</p>
                  <a href="{SITE_URL}/#usar" style="display:inline-block;margin-top:24px;background:#4f8ef7;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-weight:700;">
                    Ir al formulario →
                  </a>
                </div>""",
            })
        except Exception as e:
            logger.error(f"[EMAIL] Error enviando código a {buyer_email}: {e}")

    logger.info(f"[WEBHOOK] Pago aprobado ref={ref} plan={plan} email={buyer_email} code={code}")
    return {"status": "ok", "code": code}


@app.get("/api/check-payment")
async def check_payment(ref: str):
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT status, code, plan FROM payments WHERE reference_id=?", (ref,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(404, detail="Referencia no encontrada")
    status, code, plan = row
    return {"status": status, "code": code, "plan": plan}


# ── Código manual (admin) ──────────────────────────────────────────────────────
@app.get("/generate-code")
async def generate_code(type: str = "basic"):
    type = type.lower()
    if type not in LIMITES:
        raise HTTPException(400, detail=f"Tipo inválido. Usá: {', '.join(LIMITES.keys())}")
    prefijo = PREFIJOS[type]
    code    = f"{prefijo}-{uuid.uuid4().hex[:6].upper()}"
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT INTO codes (code, type) VALUES (?, ?)", (code, type))
    con.commit()
    con.close()
    return {"code": code, "type": type, "limit": LIMITES[type]}


# ── Validación de CSV ──────────────────────────────────────────────────────────
# Aliases aceptados para la columna principal (se normalizan a 'nombre')
ALIAS_NOMBRE = {"nombre", "nombre_producto", "product", "product_name", "name", "producto", "titulo", "title"}
COLUMNAS_OPCIONALES_ALIAS = {
    "categoria":       {"categoria", "category", "tipo", "type"},
    "caracteristicas": {"caracteristicas", "caracteristica", "features", "descripcion", "description", "detalles", "details"},
}
MAX_BYTES = 5 * 1024 * 1024   # 5 MB
EXTENSIONES_VALIDAS = {".csv", ".txt"}


def validar_csv(contenido: bytes, filename: str, limite: int, email: str) -> pd.DataFrame:
    """
    Valida y normaliza el CSV. Lanza HTTPException 400 con mensaje amigable ante cualquier problema.
    Retorna el DataFrame limpio listo para procesar.
    """
    # 1 — Extensión del archivo
    ext = os.path.splitext(filename or "")[-1].lower()
    if ext not in EXTENSIONES_VALIDAS:
        logger.warning(f"[VALIDAR] {email} subió archivo con extensión inválida: '{ext}'")
        raise HTTPException(
            400,
            detail=f"Tipo de archivo no permitido ('{ext}'). Solo se aceptan archivos .csv."
        )

    # 2 — Tamaño
    if len(contenido) == 0:
        logger.warning(f"[VALIDAR] {email} subió un archivo vacío.")
        raise HTTPException(400, detail="El archivo está vacío. Por favor subí un CSV con productos.")

    if len(contenido) > MAX_BYTES:
        mb = len(contenido) / 1024 / 1024
        logger.warning(f"[VALIDAR] {email} superó el límite de tamaño: {mb:.1f} MB")
        raise HTTPException(400, detail=f"El archivo pesa {mb:.1f} MB. El máximo permitido es 5 MB.")

    # 3 — Parseo
    try:
        df = pd.read_csv(io.BytesIO(contenido))
    except Exception as exc:
        logger.warning(f"[VALIDAR] {email} subió un CSV que no se pudo parsear: {exc}")
        raise HTTPException(
            400,
            detail="No se pudo leer el archivo. Asegurate de que sea un CSV válido exportado desde Excel o Google Sheets."
        )

    if df.empty or len(df.columns) == 0:
        logger.warning(f"[VALIDAR] {email} subió un CSV sin columnas detectables.")
        raise HTTPException(400, detail="El CSV no tiene columnas reconocibles. Revisá que el archivo no esté vacío o mal formateado.")

    # 4 — Normalizar nombres de columnas
    df.columns = [c.lower().strip() for c in df.columns]
    columnas_originales = set(df.columns)

    # 5 — Resolver alias de columna 'nombre'
    col_nombre = next((c for c in df.columns if c in ALIAS_NOMBRE), None)
    if col_nombre is None:
        logger.warning(
            f"[VALIDAR] {email} — columna 'nombre' no encontrada. "
            f"Columnas recibidas: {sorted(columnas_originales)}"
        )
        raise HTTPException(
            400,
            detail=(
                f"Formato de archivo incorrecto. No se encontró la columna de nombre del producto. "
                f"Columnas detectadas: {', '.join(sorted(columnas_originales))}. "
                f"Renombrá la columna principal a 'nombre' (o 'nombre_producto', 'product_name')."
            )
        )

    if col_nombre != "nombre":
        df = df.rename(columns={col_nombre: "nombre"})
        logger.info(f"[VALIDAR] {email} — alias '{col_nombre}' → 'nombre' aplicado.")

    # 6 — Resolver aliases de columnas opcionales
    for col_destino, aliases in COLUMNAS_OPCIONALES_ALIAS.items():
        if col_destino not in df.columns:
            alias_encontrado = next((c for c in df.columns if c in aliases), None)
            if alias_encontrado:
                df = df.rename(columns={alias_encontrado: col_destino})
                logger.info(f"[VALIDAR] {email} — alias '{alias_encontrado}' → '{col_destino}' aplicado.")

    # 7 — Limpiar filas sin nombre
    df = df.dropna(subset=["nombre"])
    df = df[df["nombre"].astype(str).str.strip() != ""]

    # 8 — Mínimo de filas válidas
    if len(df) == 0:
        logger.warning(f"[VALIDAR] {email} — CSV sin filas válidas después de limpiar.")
        raise HTTPException(
            400,
            detail="El CSV no tiene productos válidos. Revisá que la columna 'nombre' no esté vacía."
        )

    # 9 — Límite del plan
    if len(df) > limite:
        logger.warning(
            f"[VALIDAR] {email} — excedió límite del plan: subió {len(df)} productos, límite={limite}."
        )
        raise HTTPException(
            400,
            detail=(
                f"Tu plan permite procesar hasta {limite} productos por archivo. "
                f"Tu CSV contiene {len(df)} productos válidos. "
                f"Por favor reducí el archivo o adquirí un plan superior."
            )
        )

    logger.info(f"[VALIDAR] {email} — CSV válido: {len(df)} productos, columnas={sorted(df.columns.tolist())}")
    return df


# ── Prueba Gratuita ────────────────────────────────────────────────────────────
def get_client_ip(request: Request) -> str:
    """Extrae la IP real del cliente respetando el proxy de Railway."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host or "unknown"


@app.post("/prueba-gratis")
async def prueba_gratis(
    request: Request,
    file: UploadFile = None,
    lang: str = Form("es"),
    tone: str = Form("profesional"),
    pais: str = Form("Neutro"),
):
    ip = get_client_ip(request)
    logger.info(f"[TRIAL] Solicitud desde IP={ip}")

    # — Control de abuso por IP —
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT ip FROM free_trials WHERE ip = ?", (ip,)).fetchone()
    con.close()
    if row:
        raise HTTPException(
            403,
            detail="Ya utilizaste tu prueba gratuita. ¡Te esperamos en nuestros planes pagos!"
        )

    if file is None:
        raise HTTPException(400, detail="No se recibió ningún archivo.")

    # — Validar extensión y tamaño —
    ext = os.path.splitext(file.filename or "")[-1].lower()
    if ext not in {".csv", ".txt"}:
        raise HTTPException(400, detail="Solo se aceptan archivos .csv.")

    contenido = await file.read()
    if len(contenido) == 0:
        raise HTTPException(400, detail="El archivo está vacío.")

    # — Parsear CSV —
    try:
        df = pd.read_csv(io.BytesIO(contenido))
    except Exception:
        raise HTTPException(400, detail="No se pudo leer el CSV. Verificá el formato.")

    df.columns = [c.lower().strip() for c in df.columns]

    # — Resolver alias de columna nombre —
    col_nombre = next((c for c in df.columns if c in ALIAS_NOMBRE), None)
    if col_nombre is None:
        raise HTTPException(
            400,
            detail=f"No se encontró columna de nombre. Columnas detectadas: {', '.join(df.columns)}. "
                   f"Renombrá la columna principal a 'nombre'."
        )
    if col_nombre != "nombre":
        df = df.rename(columns={col_nombre: "nombre"})

    df = df.dropna(subset=["nombre"])
    df = df[df["nombre"].astype(str).str.strip() != ""]

    if len(df) == 0:
        raise HTTPException(400, detail="El CSV no tiene productos válidos.")

    # — Validar límite de 5 productos —
    if len(df) > 5:
        raise HTTPException(
            400,
            detail=f"La prueba gratuita admite un máximo de 5 productos. "
                   f"Tu CSV tiene {len(df)} productos válidos. "
                   f"Para procesar más, elegí un plan pago."
        )

    # — Procesar con IA (sincrónico para devolver descarga) —
    pais_limpio = pais.strip() or "Neutro"
    logger.info(f"[TRIAL] Procesando {len(df)} productos para IP={ip} | tone={tone} | lang={lang} | pais={pais_limpio}")
    rows = [row.to_dict() for _, row in df.iterrows()]
    descripciones = []
    try:
        for producto in rows:
            desc = generar_descripcion(producto, tone, lang, pais_limpio)
            descripciones.append(desc)
    except Exception as exc:
        logger.error(f"[TRIAL] Error generando descripciones para IP={ip}: {exc}")
        raise HTTPException(500, detail=f"Error al generar descripciones. Intentá de nuevo en unos minutos.")
    df["descripcion_generada"] = descripciones

    # — Registrar IP como usada —
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT OR IGNORE INTO free_trials (ip) VALUES (?)", (ip,))
    con.commit()
    con.close()
    logger.info(f"[TRIAL] Completado para IP={ip}")

    # — Devolver CSV como descarga —
    csv_str = df.to_csv(index=False)
    output = io.BytesIO(b'\xef\xbb\xbf' + csv_str.encode('utf-8'))
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=prueba_gratis_describeai.csv"}
    )


# ── Procesar CSV ───────────────────────────────────────────────────────────────
@app.post("/procesar")
async def procesar(
    background_tasks: BackgroundTasks,
    file:          UploadFile = None,
    email:         str = Form(...),
    storeName:     str = Form("Mi Tienda"),
    tone:          str = Form("profesional"),
    lang:          str = Form("es"),
    access_code:   str = Form(...),
    pais_destino:  str = Form("Neutro"),   # opcional — default "Neutro"
):
    # — Validar código de acceso —
    code_upper = access_code.strip().upper()
    row = get_code(code_upper)

    if row is None:
        raise HTTPException(400, detail="Código inválido. Verificá que sea correcto.")

    _, code_type, used = row
    if used:
        raise HTTPException(400, detail="Este código ya fue usado. Cada código es de un solo uso.")

    # — Leer y validar CSV —
    contenido = await file.read()
    limite    = LIMITES[code_type]
    df        = validar_csv(contenido, file.filename, limite, email)

    pais_limpio = pais_destino.strip() or "Neutro"
    logger.info(f"[PROCESAR] {email} | pais_destino='{pais_limpio}' | tone='{tone}' | lang='{lang}'")

    # — Todo OK: marcar código y encolar procesamiento —
    mark_used(code_upper)
    background_tasks.add_task(procesar_csv, contenido, email, storeName, tone, lang, pais_limpio)
    return {"status": "ok", "message": f"Procesando {len(df)} productos. Te llega por email en minutos."}


# ── Generación con OpenRouter ─────────────────────────────────────────────────
def generar_descripcion(producto: dict, tono: str, idioma: str,
                        pais_destino: str = "Neutro") -> str:
    """
    Llama a OpenRouter (Llama 3.3 70B) con semáforo global.
    Sin sleeps en el camino feliz — máxima velocidad con plan pago.
    Backoff solo ante 429 real: 3s → 6s → 12s (3 intentos).
    """
    nombre = producto.get('nombre', '(sin nombre)')

    if idioma == "es":
        # Español: localización regional completa
        system_prompt = f"""Sos un redactor profesional de e-commerce nativo de {pais_destino}.
Escribí en español con vocabulario natural de esa región
(ej: 'bocina' en México, 'parlante' en Argentina, 'altavoz' en España).

Reglas estrictas:
- TODO el texto debe estar en español, sin mezclar palabras de otros idiomas
- Tono {tono}: si es Profesional/Técnico, NUNCA usar jerga callejera ni modismos exagerados
- Los tags HTML <b> deben estar bien formados, nunca <b-
- Máximo 100 palabras
- Incluir keywords en <b>negrita</b>"""

        user_prompt = f"""Genera UNA descripcion de producto en tono {tono} para el mercado de {pais_destino}.
Idioma: espanol (unicamente)

Producto:
- Nombre: {producto.get('nombre', '')}
- Categoria: {producto.get('categoria', '')}
- Caracteristicas: {producto.get('caracteristicas', '')}

Reglas de formato:
- Maximo 100 palabras
- Solo usa la informacion dada, no inventes datos
- Envuelve las palabras clave importantes en etiquetas <b>
- Solo la descripcion, sin titulos ni explicaciones adicionales"""

    else:
        # Otros idiomas: solo tono + traducción, sin localización regional
        lang_names = {"en": "English", "pt": "Portuguese", "fr": "French"}
        lang_name  = lang_names.get(idioma, idioma)
        tone_map   = {
            "profesional": "professional", "amigable": "friendly",
            "lujoso": "luxurious", "divertido": "fun and playful", "tecnico": "technical"
        }
        tone_name = tone_map.get(tono, tono)

        lang_extra = ""
        if idioma == "pt":
            lang_extra = """

PORTUGUESE TRANSLATION — APPLY SILENTLY:
Translate all Spanish words in the input to Brazilian Portuguese.
Do NOT mention, explain or reference the translation — just write the description directly.
Apply these translations automatically:
  'portabrocas' → 'mandril'        |   'maletín' → 'estojo'
  'freno automático' → 'trava automática'
  'gancho magnético' → 'presilha magnética'
  'herramientas de medición' → 'ferramentas de medição'
  'herramientas de mano' → 'ferramentas manuais'
  'longitud' → 'comprimento'       |   'aluminio' → 'alumínio'
  'mango' → 'cabo'                 |   'antideslizante' → 'antiderrapante'
  'clavos' → 'pregos'              |   'uña' → 'garra'
  'resistente al agua' → 'resistente à água'
  'sonido' → 'som'                 |   'batería' → 'bateria'
  'acero' → 'aço'                  |   'acabado' → 'acabamento'
  'litio' → 'lítio'                |   'Profesional' → 'Profissional'
ZERO palavras em espanhol na saída."""

        if idioma == "fr":
            lang_extra = """

FRENCH TRANSLATION — APPLY SILENTLY:
Translate all Spanish words in the input to French.
Do NOT mention, explain or reference the translation — just write the description directly.
Apply these translations automatically:
  'portabrocas' → 'mandrin'         |   'maletín' → 'mallette'
  'freno automático' → 'frein automatique'
  'gancho magnético' → 'crochet magnétique'  |  'gancho' → 'crochet'
  'herramientas de medición' → 'outils de mesure'
  'herramientas de mano' → 'outils à main'
  'longitud' → 'longueur'           |   'aluminio' → 'aluminium'
  'mango' → 'manche'                |   'antideslizante' → 'antidérapant'
  'clavos' → 'clous'                |   'uña curva' → 'griffe courbée'
  'burbuja' → 'bulle'               |   'resistente al agua' → 'résistant à l\'eau'
  'peso' → 'poids'                  |   'cinta' → 'ruban'
  'motor' → 'moteur'                |   'cromado' → 'chromé'
  'acabado' → 'finition'            |   'litio' → 'lithium'
  'metros' → 'mètres'               |   'Profesional' → 'Professionnel'
  'velocidad variable' → 'vitesse variable'
  'resistente a las caídas' → 'résistant aux chutes'
ZERO mots en espagnol dans la sortie.

FRENCH GRAMMAR — GENDER AGREEMENT:
Every noun, adjective and article must agree in gender and number.
Examples: 'une tête en acier forgé' (fém.), 'un manche en fibre de verre' (masc.).
Never write 'un tête' or 'une manche'."""

        # País de referencia para idiomas sin localización regional
        pais_map_intl = {"en": "Estados Unidos", "pt": "Brasil", "fr": "Francia"}
        pais_ref = pais_destino if pais_destino not in ("Neutro", "") else pais_map_intl.get(idioma, idioma)

        system_prompt = f"""Sos un redactor profesional de e-commerce nativo de {pais_ref}.
Escribí en {lang_name} con vocabulario natural de esa región
(ej: 'bocina' en México, 'parlante' en Argentina, 'alto-falante' en Brasil).

Reglas estrictas:
- TODO el texto debe estar en {lang_name}, sin mezclar palabras de otros idiomas
- Traducir también el nombre del producto al {lang_name}
- Tono {tone_name}: si es Profesional/Técnico, NUNCA usar jerga callejera ni modismos exagerados
- Los tags HTML <b> deben estar bien formados, nunca <b-
- Máximo 100 palabras
- Incluir keywords en <b>negrita</b>{lang_extra}"""

        nombre_traducido = _traducir_nombre(producto.get('nombre', ''), idioma)
        user_prompt = f"""Write ONE product description in {lang_name} with a {tone_name} tone.

Product:
- Name: {nombre_traducido}
- Category: {producto.get('categoria', '')}
- Features: {producto.get('caracteristicas', '')}

Format rules:
- Maximum 100 words
- Only use the provided information, do not invent data
- Wrap important keywords in <b> tags
- Only the description, no titles or additional explanations
- The entire output MUST be written exclusively in {lang_name}"""

    MAX_INTENTOS = 3

    for intento in range(MAX_INTENTOS):
        try:
            client = OpenAI(
                api_key=OPENROUTER_KEY,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "https://describeai.store",
                    "X-Title":      "DescribeAI",
                },
            )
            with AI_SEMAPHORE:
                logger.info(f"[AI] Llamando OpenRouter para '{nombre}' (intento {intento + 1}/{MAX_INTENTOS})")
                response = client.chat.completions.create(
                    model=AI_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    max_tokens=300,
                    temperature=0.7,
                )
            result = response.choices[0].message.content.strip()
            # Fix tags HTML rotos: <b-Palabra → <b>Palabra
            result = re.sub(r'<b-', '<b>', result)

            # ── Post-procesamiento: elimina palabras españolas residuales ──────
            if idioma == "pt":
                for _es, _pt in [
                    ("mango",       "cabo"),
                    ("acero",       "aço"),
                    ("acabado",     "acabamento"),
                    ("batería",     "bateria"),
                    ("litio",       "lítio"),
                    ("eléctricas",  "elétricas"),
                    ("Profesional", "Profissional"),
                    ("profesional", "profissional"),
                ]:
                    result = result.replace(_es, _pt)
            elif idioma == "fr":
                result = re.sub(r'\blithiu\b', 'lithium', result)  # typo del modelo
                result = re.sub(r'ergon[oó]mico', 'ergonomique', result, flags=re.IGNORECASE)
                result = re.sub(
                    r'[Rr]esistente? [aà] las ca[ií]das', 'résistant aux chutes', result
                )
                for _es, _fr in [
                    ("peso",        "poids"),
                    ("cinta",       "ruban"),
                    ("gancho",      "crochet"),
                    ("mango",       "manche"),
                    ("motor",       "moteur"),
                    ("vélocité",    "vitesse"),
                    ("cromado",     "chromé"),
                    ("acabado",     "finition"),
                    ("litio",       "lithium"),
                    ("maletín",     "mallette"),
                    ("metros",      "mètres"),
                    ("Profesional", "Professionnel"),
                    ("profesional", "professionnel"),
                ]:
                    result = result.replace(_es, _fr)
            # ──────────────────────────────────────────────────────────────────

            logger.info(f"[AI] OK '{nombre}' en intento {intento + 1}")
            return result

        except OpenAIRateLimitError:
            wait = 3 * (2 ** intento)   # 3s → 6s → 12s
            logger.warning(f"[AI] 429 para '{nombre}' — esperando {wait}s (intento {intento + 1}/{MAX_INTENTOS})")
            if intento < MAX_INTENTOS - 1:
                time.sleep(wait)

        except Exception as exc:
            wait = 2 * (intento + 1)    # 2s → 4s → 6s
            logger.warning(f"[AI] Error para '{nombre}': {exc} — reintentando en {wait}s")
            if intento < MAX_INTENTOS - 1:
                time.sleep(wait)

    logger.error(f"[AI] Fallo tras {MAX_INTENTOS} intentos para '{nombre}'.")
    return "Error: no se pudo generar la descripcion"


def procesar_csv(contenido: bytes, email: str, tienda: str, tono: str, idioma: str,
                 pais_destino: str = "Neutro"):
    """
    Procesa el CSV con sistema de fallback automático en dos modos:
      - Modo Rápido   : ThreadPoolExecutor con GROQ_MAX_WORKERS hilos (concurrente).
      - Modo Económico: 1 hilo + 2s de delay entre llamadas (se activa al detectar
                        2 errores consecutivos por rate limit o cuota agotada).
    La transición es automática y transparente para el usuario final.
    """
    try:
        df = pd.read_csv(io.BytesIO(contenido))
        df.columns = [c.lower().strip() for c in df.columns]
        df = df.dropna(subset=['nombre'])
        df = df[df['nombre'].str.strip() != '']

        total = len(df)
        logger.info(
            f"[CSV] Iniciando procesamiento de {total} productos para {email} "
            f"| tienda={tienda} | pais_destino='{pais_destino}' | modo=Rapido"
        )

        rows          = [row.to_dict() for _, row in df.iterrows()]
        descripciones = [None] * total
        completados   = 0

        # ── Estado del fallback (local por job, thread-safe) ──────────────────
        fallback_mode   = threading.Event()   # activo = modo económico
        api_lock        = threading.Lock()    # garantiza 1 llamada a la vez en modo económico
        errores_consec  = {"n": 0}            # contador de errores consecutivos
        UMBRAL_FALLBACK = 2                   # errores para activar fallback

        def _procesar_fila(args: tuple) -> tuple:
            idx, producto = args

            if fallback_mode.is_set():
                # ── Modo Económico: secuencial con delay ──────────────────────
                with api_lock:
                    time.sleep(2)
                    desc = generar_descripcion(producto, tono, idioma, pais_destino)
            else:
                # ── Modo Rápido: concurrente ──────────────────────────────────
                desc = generar_descripcion(producto, tono, idioma, pais_destino)

                with api_lock:
                    if desc.startswith("Error:"):
                        errores_consec["n"] += 1
                        if errores_consec["n"] >= UMBRAL_FALLBACK and not fallback_mode.is_set():
                            fallback_mode.set()
                            logger.warning(
                                f"[FALLBACK] ⚠ Modo Económico activado para {email} "
                                f"tras {UMBRAL_FALLBACK} errores — cambiando a 1 hilo + 2s delay"
                            )
                        # Reintentar este producto ya en modo económico
                        if fallback_mode.is_set():
                            time.sleep(5)
                            desc = generar_descripcion(producto, tono, idioma, pais_destino)
                    else:
                        errores_consec["n"] = 0   # éxito → resetear contador

            return idx, desc

        with ThreadPoolExecutor(max_workers=AI_MAX_WORKERS) as executor:
            futures = {
                executor.submit(_procesar_fila, (i, row)): i
                for i, row in enumerate(rows)
            }
            for future in as_completed(futures):
                try:
                    idx, desc = future.result()
                    descripciones[idx] = desc
                    completados += 1
                    modo = "ECO" if fallback_mode.is_set() else "RAPID"
                    logger.info(f"[CSV][{modo}] Progreso: {completados}/{total} para {email}")
                except Exception as exc:
                    logger.error(f"[CSV] Error en fila {futures[future]}: {exc}")
                    descripciones[futures[future]] = "Error: no se pudo generar la descripcion"
                    completados += 1

        if fallback_mode.is_set():
            logger.info(f"[CSV] Job completado en Modo Económico para {email}")
        else:
            logger.info(f"[CSV] Job completado en Modo Rápido para {email}")

        df['descripcion_generada'] = descripciones

        csv_str = df.to_csv(index=False)
        csv_bytes = b'\xef\xbb\xbf' + csv_str.encode('utf-8')
        output = io.BytesIO(csv_bytes)
        output.seek(0)
        enviar_csv(email, tienda, output.read())
        logger.info(f"[CSV] Email enviado a {email} con {total} descripciones completadas")

    except Exception as e:
        logger.error(f"[CSV] Error crítico procesando CSV para {email}: {e}")
        enviar_error(email, str(e))


def enviar_csv(email_destino: str, tienda: str, csv_bytes: bytes):
    csv_base64 = base64.b64encode(csv_bytes).decode("utf-8")
    resend.Emails.send({
        "from":     FROM_EMAIL,
        "to":       email_destino,
        "reply_to": REPLY_TO,
        "subject":  f"✅ DescribeAI — Tus descripciones para {tienda} están listas",
        "html": f"""
        <div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto;">
          <h2>✅ Tus descripciones están listas</h2>
          <p>Adjunto encontrás el CSV con la columna <strong>descripcion_generada</strong>
          para tu tienda <strong>{tienda}</strong>.</p>
          <p>Solo copiá y pegá cada descripción en tu tienda.</p>
          <p>Gracias por usar DescribeAI 🚀</p>
        </div>""",
        "attachments": [{"filename": f"descripciones_{tienda}.csv", "content": csv_base64}],
    })


def enviar_error(email_destino: str, error: str):
    resend.Emails.send({
        "from":     FROM_EMAIL,
        "to":       email_destino,
        "reply_to": REPLY_TO,
        "subject":  "DescribeAI — Hubo un problema con tu pedido",
        "html": f"""
        <div style="font-family:-apple-system,sans-serif;">
          <h2>❌ Hubo un problema con tu pedido</h2>
          <pre style="background:#f5f5f5;padding:10px;border-radius:6px;">{error}</pre>
          <p>Por favor contactanos.</p>
        </div>""",
    })
