#!/usr/bin/env python3
"""
run_combinatory_test.py — Test combinatorio de localización e idiomas
======================================================================
Verifica la capacidad del sistema de adaptar descripciones a distintos
idiomas, países y modismos locales. Producto fijo: JBL Charge 4.

Matriz: 12 combinaciones (6 países × 2 tonos cada uno)
Concurrencia: 3 hilos en paralelo
Salida: reporte_jbl_combinatorio.md

Uso (CMD):
    set OPENROUTER_API_KEY=sk-or-xxxx
    python run_combinatory_test.py

Uso (PowerShell):
    $env:OPENROUTER_API_KEY="sk-or-xxxx"
    python run_combinatory_test.py
"""

import os
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from openai import OpenAI

# ── API Key ───────────────────────────────────────────────────────────────────
OPENROUTER_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_KEY:
    print("\n❌  Falta la API key.")
    print("    CMD:        set OPENROUTER_API_KEY=sk-or-xxxx")
    print("    PowerShell: $env:OPENROUTER_API_KEY='sk-or-xxxx'\n")
    sys.exit(1)

AI_MODEL    = "meta-llama/llama-3.3-70b-instruct"
MAX_WORKERS = 3

# ── Producto base ─────────────────────────────────────────────────────────────
PRODUCTO = {
    "nombre":          "Parlante Bluetooth JBL Charge 4",
    "categoria":       "Electrónica / Audio",
    "caracteristicas": "batería 20 horas de autonomía · resistente al agua IPX7 · sonido potente con bass reforzado · portátil · compatible iOS y Android",
}

# ── Localizaciones con modismos ───────────────────────────────────────────────
LOCALIZACIONES = {
    "Argentina": {
        "lang_name": "Español (Argentina)",
        "instruccion": (
            "Escribí en español argentino con voseo natural (llevalo, tirás, es)."
            " Usá estos términos y modismos: 'parlante', 'batería zarpada',"
            " 'ideal para el asado o la previa'. El tono debe sonar como una tienda local argentina."
        ),
    },
    "México": {
        "lang_name": "Español (México)",
        "instruccion": (
            "Escribí en español mexicano con tuteo (llevar, tirar, está)."
            " Usá estos términos y modismos: 'bocina', 'batería perrona', 'chido',"
            " 'ideal para la peda'. El tono debe sonar como una tienda local mexicana."
        ),
    },
    "Colombia": {
        "lang_name": "Español (Colombia)",
        "instruccion": (
            "Escribí en español colombiano con tuteo natural."
            " Usá estos términos y modismos: 'parlante', 'bacano', 'chévere',"
            " 'una chimba de sonido'. El tono debe sonar como una tienda local colombiana."
        ),
    },
    "España": {
        "lang_name": "Español (España)",
        "instruccion": (
            "Escribí en español peninsular con tuteo."
            " Usá estos términos y modismos: 'altavoz', 'mola', 'batería flipante', 'qué guapo'."
            " El tono debe sonar como una tienda local española."
        ),
    },
    "Estados Unidos": {
        "lang_name": "English (USA)",
        "instruccion": (
            "Write in American English."
            " Use terms like: 'speaker', 'awesome bass', 'perfect for parties', 'take it anywhere'."
            " Sound like a native US e-commerce store — energetic and direct."
        ),
    },
    "Brasil": {
        "lang_name": "Português (Brasil)",
        "instruccion": (
            "Escreva em português brasileiro."
            " Use termos como: 'caixa de som bluetooth', 'graves potentes', 'leve pra qualquer lugar'."
            " O tom deve soar como uma loja brasileira — entusiasmado e próximo."
        ),
    },
}

# ── Tonos ─────────────────────────────────────────────────────────────────────
TONOS_ES = {
    "tecnico":   "técnico y detallado (enfocado en especificaciones y datos concretos)",
    "comercial": "comercial y persuasivo (orientado a la venta, destacando beneficios)",
    "informal":  "informal y cercano (como si le hablaras a un amigo)",
}
TONOS_EN = {
    "tecnico":   "technical and detailed (focused on specs and concrete data)",
    "comercial": "commercial and persuasive (sales-oriented, highlighting benefits)",
    "informal":  "informal and friendly (like talking to a friend)",
}
TONOS_PT = {
    "tecnico":   "técnico e detalhado (focado em especificações e dados concretos)",
    "comercial": "comercial e persuasivo (orientado à venda, destacando benefícios)",
    "informal":  "informal e próximo (como se estivesse falando com um amigo)",
}
TONO_LABELS = {
    "tecnico":   "Técnico/Profesional",
    "comercial": "Comercial/Persuasivo",
    "informal":  "Informal/Cercano",
}

# ── Matriz de 12 combinaciones ────────────────────────────────────────────────
COMBINACIONES = [
    {"pais": "Argentina",      "tono": "tecnico"},
    {"pais": "Argentina",      "tono": "informal"},
    {"pais": "México",         "tono": "comercial"},
    {"pais": "México",         "tono": "informal"},
    {"pais": "Colombia",       "tono": "informal"},
    {"pais": "Colombia",       "tono": "tecnico"},
    {"pais": "España",         "tono": "comercial"},
    {"pais": "España",         "tono": "informal"},
    {"pais": "Estados Unidos", "tono": "comercial"},
    {"pais": "Estados Unidos", "tono": "informal"},
    {"pais": "Brasil",         "tono": "comercial"},
    {"pais": "Brasil",         "tono": "tecnico"},
]


# ── Construcción de prompts ───────────────────────────────────────────────────
def construir_prompts(pais: str, tono_key: str) -> tuple[str, str]:
    loc  = LOCALIZACIONES[pais]
    inst = loc["instruccion"]
    nom  = PRODUCTO["nombre"]
    cat  = PRODUCTO["categoria"]
    car  = PRODUCTO["caracteristicas"]

    # Detectar idioma por país
    if pais == "Estados Unidos":
        tono_desc = TONOS_EN[tono_key]
        system = (
            f"You are an expert e-commerce copywriter for the US market.\n"
            f"Your task: write ONE persuasive product description in American English.\n\n"
            f"TONE: {tono_desc}\n\n"
            f"LOCALIZATION RULES:\n{inst}\n\n"
            f"FORMAT:\n"
            f"- Maximum 100 words\n"
            f"- Use only the provided information, do not invent data\n"
            f"- Wrap key terms in <b> tags\n"
            f"- Output: ONLY the description, no titles or extra text"
        )
        user = (
            f"Write the product description.\n\n"
            f"Product:\n"
            f"- Name: {nom}\n"
            f"- Category: {cat}\n"
            f"- Features: {car}"
        )

    elif pais == "Brasil":
        tono_desc = TONOS_PT[tono_key]
        system = (
            f"Você é um especialista em copywriting para e-commerce no mercado brasileiro.\n"
            f"Sua tarefa: escrever UMA descrição de produto persuasiva em português brasileiro.\n\n"
            f"TOM: {tono_desc}\n\n"
            f"REGRAS DE LOCALIZAÇÃO:\n{inst}\n\n"
            f"FORMATO:\n"
            f"- Máximo 100 palavras\n"
            f"- Use apenas as informações fornecidas, não invente dados\n"
            f"- Destaque termos importantes com etiquetas <b>\n"
            f"- Saída: APENAS a descrição, sem títulos ou texto extra"
        )
        user = (
            f"Escreva a descrição do produto.\n\n"
            f"Produto:\n"
            f"- Nome: {nom}\n"
            f"- Categoria: {cat}\n"
            f"- Características: {car}"
        )

    else:
        # Español: Argentina, México, Colombia, España
        tono_desc = TONOS_ES[tono_key]
        system = (
            f"Sos un experto copywriter de e-commerce especializado en el mercado de {pais}.\n"
            f"Tu tarea: redactar UNA descripción de producto persuasiva en español nativo de {pais}.\n\n"
            f"TONO: {tono_desc}\n\n"
            f"REGLAS DE LOCALIZACIÓN:\n{inst}\n\n"
            f"FORMATO:\n"
            f"- Máximo 100 palabras\n"
            f"- Usá solo la información dada, no inventes datos\n"
            f"- Envolvé los términos clave en etiquetas <b>\n"
            f"- Salida: SOLO la descripción, sin títulos ni texto extra"
        )
        user = (
            f"Generá la descripción del producto.\n\n"
            f"Producto:\n"
            f"- Nombre: {nom}\n"
            f"- Categoría: {cat}\n"
            f"- Características: {car}"
        )

    return system, user


# ── Generador individual ──────────────────────────────────────────────────────
def generar(combo: dict, idx: int, total: int) -> dict:
    pais      = combo["pais"]
    tono_key  = combo["tono"]
    tono_lbl  = TONO_LABELS[tono_key]
    lang_name = LOCALIZACIONES[pais]["lang_name"]

    print(f"  🔄  [{idx:02d}/{total}] {pais:<18} | {tono_lbl}")

    system_prompt, user_prompt = construir_prompts(pais, tono_key)

    t0 = time.time()
    for intento in range(3):
        try:
            client = OpenAI(
                api_key=OPENROUTER_KEY,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "https://describeai.store",
                    "X-Title":      "DescribeAI",
                },
            )
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=250,
                temperature=0.7,
            )
            descripcion = response.choices[0].message.content.strip()
            elapsed     = round(time.time() - t0, 1)
            print(f"         ✅ OK · {elapsed}s")
            return {
                "pais": pais, "idioma": lang_name, "tono": tono_lbl,
                "descripcion": descripcion, "ok": True, "error": "", "tiempo": elapsed,
            }
        except Exception as exc:
            if intento < 2:
                time.sleep(3 * (intento + 1))
            else:
                elapsed = round(time.time() - t0, 1)
                print(f"         ❌ Error · {elapsed}s")
                return {
                    "pais": pais, "idioma": lang_name, "tono": tono_lbl,
                    "descripcion": f"Error: {exc}", "ok": False,
                    "error": str(exc), "tiempo": elapsed,
                }


# ══════════════════════════════════════════════════════════════════════════════
# Ejecución
# ══════════════════════════════════════════════════════════════════════════════
total  = len(COMBINACIONES)
inicio = datetime.now()
SEP    = "═" * 68

print(f"\n{SEP}")
print(f"  DescribeAI — Test Combinatorio de Localización e Idiomas")
print(f"  Producto: {PRODUCTO['nombre']}")
print(f"  {total} combinaciones · {MAX_WORKERS} hilos en paralelo")
print(f"  Inicio: {inicio.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{SEP}\n")

resultados = []
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {
        executor.submit(generar, combo, i + 1, total): i
        for i, combo in enumerate(COMBINACIONES)
    }
    for future in as_completed(futures):
        try:
            resultados.append(future.result())
        except Exception as exc:
            print(f"  ⚠  Error inesperado: {exc}")

# Ordenar por orden original de la matriz
orden = {(c["pais"], c["tono"]): i for i, c in enumerate(COMBINACIONES)}
resultados.sort(key=lambda r: orden.get(
    (r["pais"], TONO_LABELS.get(r["tono"], r["tono"])), 999
))

# ── Reporte Markdown ──────────────────────────────────────────────────────────
fin      = datetime.now()
duracion = round((fin - inicio).total_seconds(), 1)
ok_count  = sum(1 for r in resultados if r["ok"])
err_count = total - ok_count

lineas = [
    "# DescribeAI — Reporte de Test Combinatorio de Localización",
    "",
    "## Producto base",
    "",
    "| Campo | Valor |",
    "|---|---|",
    f"| **Nombre** | {PRODUCTO['nombre']} |",
    f"| **Categoría** | {PRODUCTO['categoria']} |",
    f"| **Características** | {PRODUCTO['caracteristicas']} |",
    "",
    "## Resumen de ejecución",
    "",
    "| Campo | Valor |",
    "|---|---|",
    f"| **Fecha** | {fin.strftime('%Y-%m-%d %H:%M:%S')} |",
    f"| **Combinaciones** | {total} |",
    f"| **Resultado** | {ok_count}/{total} ✅  ·  {err_count} ❌ |",
    f"| **Duración total** | {duracion}s |",
    "",
    "---",
    "",
    "## Descripciones generadas",
    "",
    "| País | Idioma | Tono | Descripción HTML Generada |",
    "|------|--------|------|--------------------------|",
]

for r in resultados:
    icono    = "✅" if r["ok"] else "❌"
    desc_md  = r["descripcion"].replace("|", "\\|").replace("\n", " ")
    lineas.append(
        f"| {icono} **{r['pais']}** | {r['idioma']} | {r['tono']} | {desc_md} |"
    )

if err_count > 0:
    lineas += ["", "---", "", "## Errores detallados", ""]
    for r in resultados:
        if not r["ok"]:
            lineas.append(f"- **{r['pais']} / {r['tono']}**: `{r['error']}`")

lineas += [
    "",
    "---",
    "",
    f"*Generado por `run_combinatory_test.py` · DescribeAI © {fin.year}*",
]

REPORTE = "reporte_jbl_combinatorio.md"
with open(REPORTE, "w", encoding="utf-8") as f:
    f.write("\n".join(lineas))

print(f"\n{SEP}")
print(f"  Test completado")
print(f"  Resultado : {ok_count}/{total} OK  ·  {err_count} errores")
print(f"  Duración  : {duracion}s")
print(f"  Reporte   : {REPORTE}")
print(f"{SEP}\n")

sys.exit(0 if err_count == 0 else 1)
