#!/usr/bin/env python3
"""
run_audit.py — Auditoría integral de IA para DescribeAI
==========================================================
Prueba todas las combinaciones de idioma / tono / país contra la lógica
de Groq y genera un reporte Markdown descargable.

Matriz de pruebas:
  - Inglés, Portugués, Francés × 5 tonos             = 15 combinaciones (pais="Neutro")
  - Español × 5 tonos × 3 países (AR / MX / ES)      = 15 combinaciones
  Total: 30 combinaciones × 5 productos = 150 llamadas a Groq

Uso (Windows CMD):
    set GROQ_API_KEY=gsk_tukey
    python run_audit.py

Uso (PowerShell):
    $env:GROQ_API_KEY="gsk_tukey"
    python run_audit.py
"""

import os
import sys
import time
import logging
from datetime import datetime

# ── UTF-8 en terminal Windows ──────────────────────────────────────────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# ── Verificar key antes de importar app ───────────────────────────────────────
if not os.getenv("GROQ_API_KEY"):
    print("\n❌  Falta la GROQ_API_KEY.")
    print("    CMD:        set GROQ_API_KEY=gsk_tukey")
    print("    PowerShell: $env:GROQ_API_KEY='gsk_tukey'\n")
    sys.exit(1)

# ── Silenciar logs de app.py ───────────────────────────────────────────────────
logging.disable(logging.CRITICAL)

from app import generar_descripcion

# ══════════════════════════════════════════════════════════════════════════════
# CSV base — 5 productos genéricos de e-commerce
# ══════════════════════════════════════════════════════════════════════════════
PRODUCTOS = [
    {
        "nombre":          "Martillo de Carpintero TotalMax",
        "categoria":       "Herramientas de construccion",
        "caracteristicas": "mango de fibra de vidrio cabeza de acero forjado uña curva para sacar clavos agarre ergonomico antideslizante",
    },
]

# ══════════════════════════════════════════════════════════════════════════════
# Matriz de pruebas
# ══════════════════════════════════════════════════════════════════════════════
TONOS = ["profesional", "amigable", "lujoso", "divertido", "tecnico"]

LANG_LABELS = {"es": "Español", "en": "Inglés", "pt": "Portugués", "fr": "Francés"}

COMBINACIONES = []

# No-español: 3 idiomas × 5 tonos, país ignorado → "Neutro"
for lang in ["en", "pt", "fr"]:
    for tono in TONOS:
        COMBINACIONES.append({"lang": lang, "tono": tono, "pais": "Neutro"})

# Español: 5 tonos × 3 países clave
for tono in TONOS:
    for pais in ["Argentina", "México", "España"]:
        COMBINACIONES.append({"lang": "es", "tono": tono, "pais": pais})

# ══════════════════════════════════════════════════════════════════════════════
# Ejecución
# ══════════════════════════════════════════════════════════════════════════════
total     = len(COMBINACIONES)
n_prod    = len(PRODUCTOS)
inicio_ts = datetime.now()

SEP  = "═" * 72
SEP2 = "─" * 72

print(f"\n{SEP}")
print(f"  DescribeAI — Auditoría Integral de IA")
print(f"  {total} combinaciones × {n_prod} productos = {total * n_prod} llamadas a Groq")
print(f"  Inicio: {inicio_ts.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{SEP}\n")

resultados = []

for i, combo in enumerate(COMBINACIONES, 1):
    lang  = combo["lang"]
    tono  = combo["tono"]
    pais  = combo["pais"]
    label = f"[{i:02d}/{total}] {LANG_LABELS[lang]:<10} | {tono:<12} | {pais}"

    print(f"{SEP2}")
    print(f"  🔄  {label}")

    t_inicio = time.time()
    errores  = []
    textos   = []

    for producto in PRODUCTOS:
        try:
            desc = generar_descripcion(producto, tono, lang, pais)
            if not desc or desc.startswith("Error:"):
                errores.append(f"Respuesta inválida para '{producto['nombre']}': {desc}")
            else:
                textos.append(desc)
        except Exception as exc:
            errores.append(f"'{producto['nombre']}' — {type(exc).__name__}: {exc}")

    t_total = round(time.time() - t_inicio, 1)
    ok      = len(errores) == 0
    estado  = "✅ OK" if ok else f"❌ Error ({len(errores)} fallo/s)"
    muestra = (textos[0][:90] + "...") if textos else "— sin texto generado —"

    print(f"       Estado  : {estado}")
    print(f"       Tiempo  : {t_total}s")
    print(f"       Muestra : {muestra[:80]}")
    if errores:
        for e in errores:
            print(f"       ⚠  {e}")

    resultados.append({
        "num":     i,
        "lang":    LANG_LABELS[lang],
        "tono":    tono.capitalize(),
        "pais":    pais,
        "estado":  estado,
        "ok":      ok,
        "tiempo":  t_total,
        "muestra": muestra,
        "errores": errores,
    })

# ══════════════════════════════════════════════════════════════════════════════
# Reporte Markdown
# ══════════════════════════════════════════════════════════════════════════════
fin_ts    = datetime.now()
duracion  = round((fin_ts - inicio_ts).total_seconds(), 0)
ok_count  = sum(1 for r in resultados if r["ok"])
err_count = total - ok_count

lineas = [
    "# DescribeAI — Reporte de Auditoría Integral de IA",
    "",
    f"| Campo | Valor |",
    f"|---|---|",
    f"| **Fecha** | {fin_ts.strftime('%Y-%m-%d %H:%M:%S')} |",
    f"| **Total combinaciones** | {total} |",
    f"| **Productos por combinación** | {n_prod} |",
    f"| **Total llamadas a Groq** | {total * n_prod} |",
    f"| **Resultado** | {ok_count}/{total} ✅ · {err_count} ❌ |",
    f"| **Duración total** | {int(duracion)} segundos |",
    "",
    "---",
    "",
    "## Resultados por combinación",
    "",
    "| # | Idioma | Tono | País | Estado | Tiempo (s) | Muestra del texto generado |",
    "|:--:|--------|------|------|:------:|:----------:|----------------------------|",
]

for r in resultados:
    muestra_md = r["muestra"].replace("|", "\\|").replace("\n", " ")
    lineas.append(
        f"| {r['num']} | {r['lang']} | {r['tono']} | {r['pais']} "
        f"| {r['estado']} | {r['tiempo']} | {muestra_md} |"
    )

# Errores detallados
errores_lista = [r for r in resultados if not r["ok"]]
if errores_lista:
    lineas += [
        "",
        "---",
        "",
        "## Errores detallados",
        "",
    ]
    for r in errores_lista:
        lineas.append(
            f"### #{r['num']} — {r['lang']} / {r['tono']} / {r['pais']}"
        )
        for e in r["errores"]:
            lineas.append(f"- `{e}`")
        lineas.append("")
else:
    lineas += [
        "",
        "---",
        "",
        "## ✅ Sin errores",
        "",
        "Todas las combinaciones procesaron correctamente.",
        "",
    ]

lineas += [
    "---",
    "",
    f"*Generado automáticamente por `run_audit.py` · DescribeAI © {fin_ts.year}*",
]

REPORTE = "auditoria_describeai_reporte.md"
with open(REPORTE, "w", encoding="utf-8") as f:
    f.write("\n".join(lineas))

# ── Resumen final en consola ───────────────────────────────────────────────────
print(f"\n{SEP}")
print(f"  Auditoría completada")
print(f"  Resultado : {ok_count}/{total} OK  ·  {err_count} errores")
print(f"  Duración  : {int(duracion)}s")
print(f"  Reporte   : {REPORTE}")
print(f"{SEP}\n")

sys.exit(0 if err_count == 0 else 1)
