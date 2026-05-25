#!/usr/bin/env python3
"""
run_stress_test.py — Stress Test de procesamiento masivo para DescribeAI
=========================================================================
Procesa 999 productos de librería usando la lógica real del backend (Groq +
GROQ_SEMAPHORE + exponential backoff). Mide tasa de éxito, errores 429 y
tiempo total. Genera auditoria_stress_libreria.md al finalizar.

Configuración fija:
    Idioma : Español
    Tono   : Técnico
    País   : Colombia

Uso (CMD):
    set GROQ_API_KEY=gsk_tukey
    python run_stress_test.py

Uso (PowerShell):
    $env:GROQ_API_KEY="gsk_tukey"
    python run_stress_test.py
"""

import os
import sys
import time
import random
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── UTF-8 en terminal Windows ──────────────────────────────────────────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# ── Verificar key ──────────────────────────────────────────────────────────────
if not os.getenv("GROQ_API_KEY"):
    print("\n❌  Falta la GROQ_API_KEY.")
    print("    CMD:        set GROQ_API_KEY=gsk_tukey")
    print("    PowerShell: $env:GROQ_API_KEY='gsk_tukey'\n")
    sys.exit(1)

# ── Test rápido de conexión ────────────────────────────────────────────────────
from groq import Groq as _Groq
try:
    _Groq(api_key=os.getenv("GROQ_API_KEY")).chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Say OK"}],
        max_tokens=5,
    )
    print("✅  Conexión Groq OK\n")
except Exception as _e:
    print(f"\n❌  Error Groq: {type(_e).__name__}: {_e}")
    print("    Verificá que la GROQ_API_KEY sea válida.\n")
    sys.exit(1)

# ── Silenciar logs de app.py ───────────────────────────────────────────────────
logging.disable(logging.CRITICAL)

from app import generar_descripcion
from groq import RateLimitError as _RateLimitError

# ── Rate limiter para stress test (independiente del backend) ─────────────────
STRESS_MAX_WORKERS = 5      # 5 hilos simultáneos
STRESS_DELAY       = 0.2    # pausa mínima entre envíos
STRESS_MAX_RETRIES = 3      # intentos propios del stress test (adicionales al backoff interno)
_submit_lock       = __import__("threading").Lock()

# ══════════════════════════════════════════════════════════════════════════════
# Generador de 999 productos de librería
# ══════════════════════════════════════════════════════════════════════════════

LIBROS_TECNICOS = [
    ("Programacion en Python para Ciencia de Datos",        "Libro tecnico",       "pandas numpy matplotlib aprendizaje automatico 450 paginas"),
    ("Arquitectura de Software con Microservicios",          "Libro tecnico",       "Docker Kubernetes API REST patrones de diseno 380 paginas"),
    ("Fundamentos de Redes y Telecomunicaciones",            "Libro tecnico",       "TCP/IP protocolos OSI fibra optica redes LAN WAN 420 paginas"),
    ("Electronica Digital y Sistemas Embebidos",             "Libro tecnico",       "Arduino Raspberry Pi circuitos logicos programacion ensamblador 500 paginas"),
    ("Calculo Diferencial e Integral Avanzado",              "Libro academico",     "funciones vectoriales series de Taylor integrales multiples 600 paginas"),
    ("Resistencia de Materiales para Ingenieria Civil",      "Libro tecnico",       "vigas columnas esfuerzos deformaciones con ejercicios resueltos 520 paginas"),
    ("Manual de Contabilidad Financiera NIIF",               "Libro tecnico",       "normas internacionales estados financieros auditoría 480 paginas"),
    ("Quimica Organica con Enfoque Biologico",               "Libro academico",     "reacciones enzimaticas metabolismo lipidos proteinas 560 paginas"),
    ("Diseno de Bases de Datos Relacionales",                "Libro tecnico",       "SQL normalizacion modelado entidad-relacion PostgreSQL 340 paginas"),
    ("Estadistica Aplicada a la Investigacion",              "Libro academico",     "hipotesis ANOVA regresion multiple SPSS tablas estadisticas 400 paginas"),
    ("Inteligencia Artificial: Teoria y Practica",           "Libro tecnico",       "redes neuronales deep learning algoritmos geneticos 550 paginas"),
    ("Diseno Grafico y Tipografia Profesional",              "Libro de arte",       "composicion visual Pantone Illustrator InDesign 300 paginas full color"),
    ("Gestion de Proyectos con Metodologias Agiles",         "Libro tecnico",       "Scrum Kanban Lean sprints roles PMBOK certificacion 360 paginas"),
    ("Seguridad Informatica y Ciberseguridad",               "Libro tecnico",       "hacking etico penetration testing criptografia OWASP 430 paginas"),
    ("Marketing Digital y E-commerce",                       "Libro de negocios",   "SEO SEM redes sociales conversion funnel analytics 320 paginas"),
    ("Derecho Comercial y Contratos Mercantiles",            "Libro juridico",      "sociedades anonimas contratos clausulas arbitraje legislacion 490 paginas"),
    ("Anatomia Humana para Estudiantes de Medicina",         "Libro academico",     "sistemas oseo muscular nervioso laminas anatomicas 700 paginas"),
    ("Fisica Cuantica: Introduccion Matematica",             "Libro academico",     "mecanica ondulatoria principio de incertidumbre ecuacion de Schrodinger 480 paginas"),
    ("Cocina Molecular: Ciencia y Gastronomia",              "Libro tecnico",       "esferificacion gelificacion emulsiones tecnicas de vanguardia 280 paginas"),
    ("Administracion Financiera Corporativa",                "Libro de negocios",   "valoracion de empresas apalancamiento VPN TIR flujos de caja 440 paginas"),
]

PAPELERIA = [
    ("Cuaderno Universitario Tapa Dura 100 Hojas",           "Papeleria",           "hojas cuadriculadas tapa cartonada espiral doble 21x29cm"),
    ("Set de Boligrafos Gel Premium x12",                    "Papeleria",           "tinta gel de secado rapido punta 0.7mm colores variados ergonomico"),
    ("Agenda Ejecutiva Anual con Semana Vista",              "Papeleria",           "tapa simil cuero cierre iman separadores mensuales bolsillo interior"),
    ("Block de Notas Adhesivas Fluorescentes x5",            "Papeleria",           "adhesivo reposicionable 75x75mm 100 hojas por block colores neon"),
    ("Carpeta con Ganchos Metalicos A4",                     "Papeleria",           "tapa resistente lomo 5cm ganchos de palanca capacidad 350 hojas"),
    ("Resaltadores de Texto Pastel x8",                      "Papeleria",           "tinta base agua lavable doble punta biselada y fina tonos pastel"),
    ("Libro de Actas Foliado con Tapa Dura",                 "Papeleria",           "200 folios numerados papel 90g certificado para uso legal"),
    ("Portafolios Ejecutivo con Cremallera",                 "Papeleria",           "material sintetico 5 divisiones portaclips tarjetero argollas A4"),
    ("Regla Metalica Antideslizante 50cm",                   "Papeleria",           "aluminio anodizado borde biselado graduacion milimetrica doble cara"),
    ("Tijeras de Acero Inoxidable 21cm",                     "Papeleria",           "hoja de acero inoxidable mango ergonomico bimaterial para zurdo y diestro"),
    ("Corrector Liquido con Aplicador de Punta Fina",        "Papeleria",           "formula de secado rapido tapa hermetica aplicador de metal 20ml"),
    ("Sacapuntas Electrico Escritorio",                      "Papeleria",           "motor silencioso guia de seguridad apto para lapices 6-12mm adaptador"),
    ("Clips Mariposa Metalicos Surtidos x50",                "Papeleria",           "acero galvanizado anticorrosion medidas 19mm 25mm 50mm caja surtida"),
    ("Papel para Impresora A4 75g Resma x500",               "Papeleria",           "blancura 92% apto laser e inkjet libre de acidos 80g certificado FSC"),
    ("Ficha de Colores Cartulina 180g A4 x50",               "Papeleria",           "180g/m2 20 colores surtidos pH neutro apto para acuarela y marcadores"),
    ("Separadores Plasticos para Carpeta x12",               "Papeleria",           "polipropileno rigido pestaña numerada del 1 al 12 multitaladro A4"),
    ("Plastico Termofusible A4 para Encuadernadora",         "Papeleria",           "gramaje 80 micrones transparente brillante caja x100 unidades"),
    ("Perforadora de Escritorio 40 Hojas",                   "Papeleria",           "base metalica regla de centrado capacidad 40 hojas tope de confetti"),
    ("Abrochadora Metalica 24 Hojas",                        "Papeleria",           "cuerpo de zinc carga rapida alcance 60mm compatible grapas 24/6 26/6"),
    ("Cinta Adhesiva Doble Faz Transparente 18mm x10m",      "Papeleria",           "adhesivo acrilico alta resistencia soporte de PET transparente sin relleno"),
]

UTILES_ESCOLARES = [
    ("Lapices de Colores Largos x48",                        "Utiles escolares",    "mina de 3.8mm resistente a la rotura pigmentos altamente saturados hexagonal"),
    ("Compas Escolar de Precision con Regla",                "Utiles escolares",    "punta de acero ajuste de presion brazo articulado incluye repuesto de mina"),
    ("Transportador 180 Grados Acrilico",                    "Utiles escolares",    "acrilico transparente 15cm graduacion cada grado borde biselado para exactitud"),
    ("Escuadras Set x2 45-60 Grados",                        "Utiles escolares",    "acrilico transparente borde milimetrado 30cm apto para tablero de dibujo"),
    ("Plasticola en Barra Lavable 40g",                      "Utiles escolares",    "formula base agua no toxico lavable en frio apto para papel tela y foami"),
    ("Temperas Escolares x12 Colores 30ml",                  "Utiles escolares",    "pigmentos lavables no toxicos secado rapido apta para papel carton madera"),
    ("Acuarelas Solidas x24 Colores",                        "Utiles escolares",    "pastillas solidas pigmentos transparentes incluye pincel pelo sintetico"),
    ("Marcadores para Pizarron x8 Colores",                  "Utiles escolares",    "tinta de base alcohol borrable punta tipo cuña cuerpo ergonomico con clip"),
    ("Tijeras Escolares Punta Roma 13cm",                    "Utiles escolares",    "hoja de acero inoxidable mango de plastico ABS apto para diestros y zurdos"),
    ("Plastilina Escolar x12 Colores 300g",                  "Utiles escolares",    "base de cera suave moldeable no mancha no se endurece al aire colores primarios"),
    ("Cartuchera Doble Cierre con Bolsillos",                "Utiles escolares",    "poliester 600D cierre YKK doble bolsillo frontal interior con elasticos"),
    ("Mochila Escolar Primaria con Refuerzo Lumbar",         "Utiles escolares",    "600D resistente al agua compartimento principal 2 bolsillos laterales 20L"),
    ("Regla Flexible 30cm con Escala Milimetrica",           "Utiles escolares",    "polipropileno flexible transparente escala en mm y cm resistente a impactos"),
    ("Cuaderno de Dibujo Tecnico A3 50 Hojas",               "Utiles escolares",    "papel obra 90g satinado apto para lapiz tinta china y acuarela tapa blanda"),
    ("Goma de Borrar Miga de Pan Suave",                     "Utiles escolares",    "formula suave para grafito y carbon no mancha ni daña el papel sin PVC"),
    ("Crayones de Cera Triangulares x24",                    "Utiles escolares",    "forma triangular antirruedo mina gruesa 8mm alta pigmentacion no toxico"),
    ("Lapiz Negro HB Triangular Antirruedo x12",             "Utiles escolares",    "mina de grafito natural resistente a la rotura cuerpo triangular ergonomico"),
    ("Portaminas 0.5mm con Repuesto x3",                     "Utiles escolares",    "cuerpo de metal mecanismo rotatorio grip de goma incluye eraser integrado"),
    ("Foami Pliego x10 Colores Surtidos",                    "Utiles escolares",    "espuma EVA 2mm grosor 50x70cm apto para manualidades y decoracion"),
    ("Cartulina Afiche x10 Colores",                         "Utiles escolares",    "160g/m2 pliego 70x100cm colores intensos apta para rotulado y carteles"),
]

INSUMOS_OFICINA = [
    ("Toner Compatible HP LaserJet Negro",                   "Insumos de oficina",  "rendimiento 3000 paginas al 5% cobertura chip integrado compatible serie 85A"),
    ("Cinta para Impresora de Matriz de Punto",              "Insumos de oficina",  "nylon entintado compatible Epson FX rendimiento 3 millones de caracteres"),
    ("Papel Termico para Fax 210mm x30m",                    "Utiles de oficina",   "alta sensibilidad termica libre de BPA imagen estable hasta 10 anos rollo precortado"),
    ("Cartucho de Tinta Canon CLI Negro Compat",             "Insumos de oficina",  "tinta de pigmento resistente al agua rendimiento 400 paginas chip reseteado"),
    ("Etiquetas Adhesivas para Archivo x240",                "Insumos de oficina",  "papel blanco 70x37mm adhesivo permanente apta para laser e inkjet perforada"),
    ("Folder Manila Oficio x50",                             "Insumos de oficina",  "cartulina manilla 150g troquelado pestaña centrada apta para archivo muerto"),
    ("Archivador Lomo Ancho AZ con Rieles",                  "Insumos de oficina",  "carton prensado forrado capacidad 500 hojas riel metalico lomo 8cm"),
    ("Caja de Archivo Definitivo Carton",                    "Insumos de oficina",  "carton microcorrugado 600g tapa abatible capacidad 5000 folios impresa"),
    ("Tablero Portatil con Clipboard A4",                    "Insumos de oficina",  "MDF 3mm laminado clip de presion metalico con regla incorporada 23x31cm"),
    ("Sellos de Caucho Personalizado Fecha",                 "Insumos de oficina",  "caucho laser grabado base plastica calidad para 50000 impresiones tinta incluida"),
    ("Tampones de Tinta Azul para Sello",                    "Insumos de oficina",  "esponja impregnada base metalica recargable tinta base aceite secado lento"),
    ("Sobre Manila Mediano C5 x100",                         "Insumos de oficina",  "kraft 90g solapa engomada medida 162x229mm apto para documentos sin doblar"),
    ("Dispensador de Cinta Adhesiva Escritorio",             "Insumos de oficina",  "base de zinc fundido nucleo para cintas de 25mm peso propio antideslizante"),
    ("Calculadora Cientifica 417 Funciones",                 "Insumos de oficina",  "display LCD 2 lineas fracciones estadistica modo ecuaciones apto para examen"),
    ("Reloj Marcador de Personal Digital",                   "Insumos de oficina",  "impresion termica identifica hasta 50 empleados exporta a Excel memoria interna"),
    ("Destructora de Papel Nivel P4 x8 Hojas",              "Insumos de oficina",  "corte en particulas 4x35mm capacidad 8 hojas destruye tarjetas CD USB"),
    ("Plastificadora en Frio A4 de Escritorio",              "Insumos de oficina",  "sin calor apta para fotos y documentos delicados velocidad 300mm/min"),
    ("Encuadernadora para Espiral Metalico Hasta A4",        "Insumos de oficina",  "capacidad 150 hojas perfora y encuaderna hasta 21 pines abertura lateral ajustable"),
    ("Bandeja Portadocumentos Acrilico x3 Pisos",            "Insumos de oficina",  "acrilico cristal transparente 3 bandejas apilables formato A4 patas metalicas"),
    ("Boligrafo Roller Tinta Liquida Negra x12",             "Insumos de oficina",  "punta de metal 0.5mm tinta base agua secado rapido escritura suave sin borroso"),
]

# ── Construir 999 productos combinando categorías ──────────────────────────────
TODOS_LOS_PRODUCTOS_BASE = LIBROS_TECNICOS + PAPELERIA + UTILES_ESCOLARES + INSUMOS_OFICINA  # 80 base

random.seed(42)  # reproducible
PRODUCTOS_999 = []

# Primero usamos todos los productos base (80)
for nombre, categoria, caracteristicas in TODOS_LOS_PRODUCTOS_BASE:
    PRODUCTOS_999.append({
        "nombre":          nombre,
        "categoria":       categoria,
        "caracteristicas": caracteristicas,
    })

# Luego generamos variantes numeradas hasta llegar a 999
variantes_adicionales = [
    ("Libro de Ejercicios Resueltos {n}",            "Material academico",   "ejercicios graduados con solucionario detallado nivel universitario edicion {n}"),
    ("Cuaderno Profesional Tapa Flexible {n}",       "Papeleria",            "papel rayado 80g 80 hojas formato A4 espiral lateral marca pagina integrada"),
    ("Caja de Lapices de Color Largos Edicion {n}",  "Utiles escolares",     "minas de 3.8mm alta saturacion surtido {n} colores hexagonales sin PVC"),
    ("Resma Papel Reciclado 75g Edicion {n}",        "Insumos de oficina",   "75g/m2 500 hojas A4 libre de acidos blanqueado sin cloro certificado {n}"),
    ("Agenda de Bolsillo Semanal {n}",               "Papeleria",            "formato 9x14cm papel ivory 80g portaboligrafos bandas elasticas cierre"),
    ("Marcador Permanente Doble Punta Set {n}",      "Papeleria",            "tinta permanente resistente al agua punta fina 1mm y gruesa 3mm {n} colores"),
    ("Calculadora Basica Solar {n}",                 "Insumos de oficina",   "12 digitos alimentacion solar y bateria funciones basicas pantalla LCD grande"),
    ("Archivador Bibliorato Plastico {n}",           "Insumos de oficina",   "polipropileno resistente lomo 5cm argollas 25mm capacidad 350 hojas A4"),
    ("Boligrafo Retractil Grip Serie {n}",           "Papeleria",            "tinta aceite punto metalico 1mm agarre de caucho clip metalico retractil"),
    ("Folder Plastico con Solapa Serie {n}",         "Insumos de oficina",   "polipropileno cristal 200 micrones formato A4 protector de bordes surtido"),
    ("Libro de Texto Universitario Serie {n}",       "Libro academico",      "bibliografia actualizada indice tematico glosario tecnico edicion revisada"),
    ("Set de Notas Adhesivas Surtidas {n}",          "Papeleria",            "adhesivo reposicionable surtido de tamanos 5 colores 50 hojas por block"),
]

i = len(PRODUCTOS_999) + 1
while len(PRODUCTOS_999) < 999:
    plantilla = variantes_adicionales[(i - 1) % len(variantes_adicionales)]
    PRODUCTOS_999.append({
        "nombre":          plantilla[0].replace("{n}", str(i)),
        "categoria":       plantilla[1],
        "caracteristicas": plantilla[2].replace("{n}", str(i)),
    })
    i += 1

PRODUCTOS_999 = PRODUCTOS_999[:999]

# ══════════════════════════════════════════════════════════════════════════════
# Configuración del stress test
# ══════════════════════════════════════════════════════════════════════════════
IDIOMA      = "es"
TONO        = "tecnico"
PAIS        = "Colombia"
TOTAL       = len(PRODUCTOS_999)
inicio_ts   = datetime.now()

SEP  = "═" * 72
SEP2 = "─" * 72

print(f"\n{SEP}")
print(f"  DescribeAI — Stress Test de Procesamiento Masivo")
print(f"  Productos  : {TOTAL}")
print(f"  Idioma     : Español  |  Tono: Técnico  |  País: Colombia")
print(f"  Concurrencia: {STRESS_MAX_WORKERS} hilos | Delay: {STRESS_DELAY}s | Retries: {STRESS_MAX_RETRIES}")
print(f"  Inicio     : {inicio_ts.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{SEP}\n")

# ══════════════════════════════════════════════════════════════════════════════
# Procesamiento inteligente con rate limiting y retries
# ══════════════════════════════════════════════════════════════════════════════
resultados    = [None] * TOTAL
completados   = 0
errores_count = 0
fallidos_log  = []   # productos que fallaron tras todos los reintentos

def _procesar_con_retry(idx: int, producto: dict) -> tuple:
    """
    Llama a generar_descripcion con hasta STRESS_MAX_RETRIES intentos propios.
    Si recibe 429 explícito espera con backoff pesado (10s → 30s → 60s).
    Retorna (idx, descripcion_o_error, fue_ok).
    """
    esperas_429 = [5, 15, 30]
    for intento in range(STRESS_MAX_RETRIES):
        try:
            desc = generar_descripcion(producto, TONO, IDIOMA, PAIS)
            if desc and not desc.startswith("Error:"):
                return idx, desc, True
            # generar_descripcion agotó sus reintentos internos
            if intento < STRESS_MAX_RETRIES - 1:
                wait = esperas_429[intento]
                time.sleep(wait)
        except _RateLimitError:
            wait = esperas_429[min(intento, len(esperas_429) - 1)]
            print(f"  ⚠  429 en producto #{idx+1} — esperando {wait}s (intento {intento+1}/{STRESS_MAX_RETRIES})")
            if intento < STRESS_MAX_RETRIES - 1:
                time.sleep(wait)
        except Exception as exc:
            return idx, f"Error: {type(exc).__name__}: {exc}", False

    return idx, "Error: fallido tras todos los reintentos", False


print(f"  Procesando {TOTAL} productos (modo rate-limit friendly)...\n")

from concurrent.futures import Future
with ThreadPoolExecutor(max_workers=STRESS_MAX_WORKERS) as executor:
    futures: dict[Future, int] = {}

    # Enviar jobs con delay entre cada submit para no saturar
    def _submit_all():
        for i, prod in enumerate(PRODUCTOS_999):
            f = executor.submit(_procesar_con_retry, i, prod)
            futures[f] = i
            time.sleep(STRESS_DELAY)   # pausa entre envíos

    import threading
    submit_thread = threading.Thread(target=_submit_all, daemon=True)
    submit_thread.start()

    # Recoger resultados a medida que llegan
    processed = 0
    while processed < TOTAL:
        done_futures = [f for f in list(futures) if f.done()]
        for future in done_futures:
            if future in futures:
                idx = futures.pop(future)
                try:
                    i, desc, ok = future.result()
                    resultados[i] = desc
                    completados += 1
                    processed += 1
                    if not ok:
                        errores_count += 1
                        fallidos_log.append({
                            "idx":     i,
                            "nombre":  PRODUCTOS_999[i]["nombre"],
                            "error":   desc,
                        })
                    if completados % 50 == 0 or completados == TOTAL:
                        pct = completados / TOTAL * 100
                        print(f"  [{completados:>3}/{TOTAL}] {pct:.0f}% — errores: {errores_count}")
                except Exception as exc:
                    resultados[idx] = f"Error: {type(exc).__name__}: {exc}"
                    errores_count += 1
                    completados += 1
                    processed += 1
                    fallidos_log.append({
                        "idx":    idx,
                        "nombre": PRODUCTOS_999[idx]["nombre"],
                        "error":  str(exc),
                    })
        if processed < TOTAL:
            time.sleep(0.3)

    submit_thread.join()

fin_ts   = datetime.now()
duracion = round((fin_ts - inicio_ts).total_seconds(), 1)
ok_count = TOTAL - errores_count

# ══════════════════════════════════════════════════════════════════════════════
# Muestra aleatoria de 15 productos
# ══════════════════════════════════════════════════════════════════════════════
indices_muestra = sorted(random.sample(range(TOTAL), 15))
muestra_items   = [(PRODUCTOS_999[i], resultados[i]) for i in indices_muestra]

# ══════════════════════════════════════════════════════════════════════════════
# Reporte Markdown
# ══════════════════════════════════════════════════════════════════════════════
tasa = round(ok_count / TOTAL * 100, 1)

lineas = [
    "# DescribeAI — Reporte de Stress Test: Librería 999 Productos",
    "",
    "## Resumen ejecutivo",
    "",
    "| Campo | Valor |",
    "|---|---|",
    f"| **Fecha** | {fin_ts.strftime('%Y-%m-%d %H:%M:%S')} |",
    f"| **Total productos** | {TOTAL} |",
    f"| **Idioma / Tono / País** | Español / Técnico / Colombia |",
    f"| **Concurrencia** | {STRESS_MAX_WORKERS} hilos | delay {STRESS_DELAY}s entre envíos |",
    f"| **Tiempo total** | {duracion} segundos ({duracion/60:.1f} minutos) |",
    f"| **Procesados OK** | {ok_count} / {TOTAL} |",
    f"| **Errores / Fallos** | {errores_count} / {TOTAL} |",
    f"| **Tasa de éxito** | {tasa}% |",
    "",
    "---",
    "",
    "## Muestra aleatoria — 15 productos verificados",
    "",
    "*(Verificar vocabulario técnico y modismos de Colombia)*",
    "",
    "| # | Producto | Descripción generada |",
    "|:--:|---------|----------------------|",
]

for prod, desc in muestra_items:
    nombre_md = prod["nombre"].replace("|", "\\|")
    desc_md   = (desc or "— sin descripción —")[:120].replace("|", "\\|").replace("\n", " ")
    if desc and len(desc) > 120:
        desc_md += "..."
    lineas.append(f"| — | **{nombre_md}** | {desc_md} |")

# Errores detallados si los hay
errores_lista = [
    (i, PRODUCTOS_999[i]["nombre"], resultados[i])
    for i in range(TOTAL)
    if resultados[i] and resultados[i].startswith("Error:")
]

if fallidos_log:
    lineas += [
        "",
        "---",
        "",
        f"## Productos fallidos ({len(fallidos_log)} de {TOTAL})",
        "",
        "| # | Producto | Error |",
        "|:--:|---------|-------|",
    ]
    for item in fallidos_log[:50]:  # máximo 50 en el reporte
        lineas.append(f"| {item['idx']+1} | {item['nombre']} | `{item['error'][:100]}` |")
    if len(fallidos_log) > 50:
        lineas.append(f"\n*... y {len(fallidos_log) - 50} errores más (omitidos para brevedad)*")
else:
    lineas += [
        "",
        "---",
        "",
        "## ✅ Sin errores",
        "",
        "Los 999 productos fueron procesados correctamente.",
    ]

lineas += [
    "",
    "---",
    "",
    f"*Generado por `run_stress_test.py` · DescribeAI © {fin_ts.year}*",
]

REPORTE = "auditoria_stress_libreria.md"
with open(REPORTE, "w", encoding="utf-8") as f:
    f.write("\n".join(lineas))

# ── Resumen final ──────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print(f"  Stress Test completado")
print(f"  Tasa de éxito : {ok_count}/{TOTAL} ({tasa}%)")
print(f"  Errores       : {errores_count}")
print(f"  Tiempo total  : {duracion}s ({duracion/60:.1f} min)")
print(f"  Reporte       : {REPORTE}")
print(f"{SEP}\n")

sys.exit(0 if errores_count == 0 else 1)
