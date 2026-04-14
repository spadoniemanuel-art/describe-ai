# 🚀 INSTRUCCIONES PARA CLAUDE CODE
# Copiá esto COMPLETO en Claude Code y él hace todo solo

## PASO 1 — CUENTAS QUE NECESITÁS CREAR

1. **Groq API** → https://console.groq.com
   - ⚡ Ya tenés cuenta del Santo Grial Bot
   - Solo copiá la misma API key: gsk_...

2. **Railway** → https://railway.app
   - Crear cuenta con GitHub
   - Es donde va a vivir el servidor (gratis hasta $5/mes de uso)

3. **Gmail App Password** (para enviar emails)
   - Entrá a tu Gmail → Cuenta → Seguridad → Verificación en 2 pasos (activar)
   - Luego: Contraseñas de aplicación → Crear una → Guardala

4. **GitHub** → https://github.com (para subir el código)

---

## PASO 2 — PROMPT PARA CLAUDE CODE

Abrí Claude Code y pegá esto EXACTO:

```
Tengo estos archivos en mi carpeta actual:
- index.html (frontend del cliente)
- app.py (backend FastAPI)
- requirements.txt

Necesito que hagas lo siguiente:

1. Creá una carpeta llamada "static" y mové index.html adentro

2. Modificá index.html para que el formulario haga un POST a "/procesar" 
   con FormData que incluya: file, email, storeName, tone, lang

3. Creá un archivo Procfile con el contenido:
   web: uvicorn app:app --host 0.0.0.0 --port $PORT

4. Creá un archivo .env.example con:
   GROQ_API_KEY=tu_key_aqui
   GMAIL_USER=tu_email@gmail.com
   GMAIL_APP_PASSWORD=tu_app_password

5. Inicializá un repositorio git, hacé commit de todo y subilo a GitHub
   en un repo llamado "describe-ai"

6. Dame las instrucciones exactas para hacer deploy en Railway con 
   las variables de entorno necesarias
```

---

## PASO 3 — DEPLOY EN RAILWAY

Después que Claude Code sube a GitHub:

1. Entrá a railway.app
2. "New Project" → "Deploy from GitHub repo"
3. Seleccioná "describe-ai"
4. En Variables de entorno agregá:
   - GROQ_API_KEY = tu key (la misma del Santo Grial Bot)
   - GMAIL_USER = tu email
   - GMAIL_APP_PASSWORD = tu app password
5. Railway te da una URL tipo: describe-ai.up.railway.app
   ¡ESA es tu web de negocios!

---

## PASO 4 — PUBLICAR EN FIVERR

Título del gig:
"I will generate professional product descriptions for your store using AI"

Descripción:
"Upload your CSV file with product names and characteristics.
I will generate professional, SEO-optimized descriptions in minutes.
Powered by Claude AI. Delivered to your email automatically."

Paquetes:
- Basic: $15 → 50 products
- Standard: $35 → 200 products  
- Premium: $120/month → Unlimited

Tags: product description, ecommerce, shopify, woocommerce, AI copywriting

---

## COSTOS MENSUALES

| Servicio | Costo |
|----------|-------|
| Railway (servidor) | ~$5/mes |
| Groq API | ✅ GRATIS |
| Gmail | ✅ GRATIS |
| Fiverr (comisión 20%) | Se descuenta de cada venta |
| **TOTAL** | **~$5/mes** |

Con solo 1 pedido de $15 ya cubrís toda la infraestructura.

---

## META: $500 USD/MES

| Pedidos necesarios | Precio | Total |
|-------------------|--------|-------|
| 14 pedidos/mes | $35 (estándar) | $490 |
| = 1 pedido cada 2 días | | ✅ META CUMPLIDA |

