#!/usr/bin/env python3
"""
test_backend.py - Suite de integracion para DescribeAI
Usa FastAPI TestClient (sin levantar servidor).
Ejecutar con: python test_backend.py
"""

import io
import os
import sys

# Forzar UTF-8 en Windows para soportar emojis y caracteres especiales
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import threading
from unittest.mock import patch, MagicMock

# ── Mockear dependencias externas ANTES de importar app ───────────────────────
# Evita que los tests fallen por falta de keys de Groq / Resend / MercadoPago
os.environ.setdefault("GROQ_API_KEY",      "test-key-groq")
os.environ.setdefault("RESEND_API_KEY",    "test-key-resend")
os.environ.setdefault("MP_ACCESS_TOKEN",   "test-key-mp")
os.environ.setdefault("ADMIN_PASSWORD",    "test-admin")
os.environ.setdefault("SITE_URL",          "http://testserver")

# Parchamos las llamadas externas que no queremos ejecutar en CI
with patch("resend.Emails.send", return_value={"id": "mock"}), \
     patch("groq.Groq"):
    from fastapi.testclient import TestClient
    from app import app, DB_PATH, LIMITES

client = TestClient(app, raise_server_exceptions=False)

# ── Colores / símbolos para terminal ──────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
PASS   = f"{GREEN}✅ PASSED{RESET}"
FAIL   = f"{RED}❌ FAILED{RESET}"

results: list[tuple[str, bool, str]] = []


# ── Helpers ───────────────────────────────────────────────────────────────────
def make_csv(columns: list, rows: list) -> bytes:
    """Genera un CSV en memoria."""
    buf = io.StringIO()
    buf.write(",".join(columns) + "\n")
    for row in rows:
        buf.write(",".join(str(v) for v in row) + "\n")
    return buf.getvalue().encode("utf-8")


def fresh_code(plan: str = "basic") -> str:
    """Obtiene un código de acceso nuevo desde el endpoint real."""
    res = client.get(f"/generate-code?type={plan}")
    assert res.status_code == 200, f"No se pudo generar código: {res.text}"
    return res.json()["code"]


def post_csv(code: str, csv_bytes: bytes, filename: str = "test.csv",
             email: str = "qa@describeai.store") -> object:
    """Wrapper del POST /procesar."""
    return client.post(
        "/procesar",
        data={
            "email":       email,
            "storeName":   "Tienda QA",
            "tone":        "profesional",
            "lang":        "es",
            "access_code": code,
        },
        files={"file": (filename, csv_bytes, "text/csv")},
    )


def run_test(name: str, fn):
    """Ejecuta un test y registra el resultado."""
    sep = "─" * 62
    print(f"\n{sep}")
    print(f"  🧪  {name}")
    print(sep)
    try:
        detail = fn()
        print(f"  {PASS}  {detail or ''}")
        results.append((name, True, ""))
    except AssertionError as exc:
        print(f"  {FAIL}")
        print(f"  {RED}   ↳ {exc}{RESET}")
        results.append((name, False, str(exc)))
    except Exception as exc:
        print(f"  {FAIL}  (excepción inesperada)")
        print(f"  {RED}   ↳ {type(exc).__name__}: {exc}{RESET}")
        results.append((name, False, str(exc)))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — Alias de columna: 'name' debe aceptarse como 'nombre'
# ══════════════════════════════════════════════════════════════════════════════
def test_1_alias_columna():
    code = fresh_code("basic")
    csv  = make_csv(
        columns=["name", "category", "features"],
        rows=[["Zapatilla Pro", "Calzado", "Suela antideslizante liviana"]],
    )
    res = post_csv(code, csv)

    assert res.status_code == 200, \
        f"Esperaba HTTP 200, recibí {res.status_code}. Body: {res.json()}"
    body = res.json()
    assert body.get("status") == "ok", f"status != 'ok': {body}"
    assert "1 producto" in body.get("message", ""), \
        f"Mensaje inesperado: {body.get('message')}"

    return f"Alias 'name' aceptado → {body['message']}"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — Columnas inválidas: ['sku', 'precio', 'stock'] → HTTP 400
# ══════════════════════════════════════════════════════════════════════════════
def test_2_columnas_invalidas():
    code = fresh_code("basic")
    csv  = make_csv(
        columns=["sku", "precio", "stock"],
        rows=[["SKU001", "9999", "50"],
              ["SKU002", "4500", "20"]],
    )
    res = post_csv(code, csv)

    assert res.status_code == 400, \
        f"Esperaba HTTP 400, recibí {res.status_code}. Body: {res.json()}"
    detail = res.json().get("detail", "")
    assert detail, "La respuesta no incluye campo 'detail'"

    # Debe mencionar qué columnas recibió O cómo corregirlo
    lower = detail.lower()
    assert any(kw in lower for kw in ["sku", "nombre", "columna", "renamb", "renombrá"]), \
        f"Mensaje 400 no es informativo: '{detail}'"

    return f"Rebotado con 400 → '{detail[:90]}...'"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Excede límite del plan basic (51 > 50) → HTTP 400
# ══════════════════════════════════════════════════════════════════════════════
def test_3_limite_plan():
    limite = LIMITES["basic"]   # 50
    exceso = limite + 1         # 51

    code = fresh_code("basic")
    rows = [[f"Producto {i}", "Ropa", "Algodon"] for i in range(1, exceso + 1)]
    csv  = make_csv(["nombre", "categoria", "caracteristicas"], rows)

    res = post_csv(code, csv)

    assert res.status_code == 400, \
        f"Esperaba HTTP 400, recibí {res.status_code}. Body: {res.json()}"
    detail = res.json().get("detail", "")

    # El mensaje debe mencionar ambos números
    assert str(exceso) in detail, \
        f"El detalle no menciona {exceso} productos: '{detail}'"
    assert str(limite) in detail, \
        f"El detalle no menciona el límite {limite}: '{detail}'"

    return f"Rebotado con 400 → '{detail}'"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — Concurrencia: 3 requests simultáneos → todos HTTP 200
# ══════════════════════════════════════════════════════════════════════════════
def test_4_concurrencia():
    n_threads = 3
    codes     = [fresh_code("basic") for _ in range(n_threads)]
    csv_bytes = make_csv(
        columns=["nombre", "categoria", "caracteristicas"],
        rows=[["Producto Stress", "Test", "Carga concurrente"]],
    )

    responses: dict[int, int]  = {}
    bodies:    dict[int, dict] = {}
    errors:    dict[int, str]  = {}

    def enviar(idx: int, code: str):
        try:
            res = post_csv(
                code, csv_bytes,
                email=f"stress{idx}@describeai.store",
            )
            responses[idx] = res.status_code
            bodies[idx]    = res.json()
        except Exception as exc:
            errors[idx] = str(exc)

    threads = [
        threading.Thread(target=enviar, args=(i, codes[i]), daemon=True)
        for i in range(n_threads)
    ]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)

    # Verificaciones
    assert not errors, \
        f"Hilos con error: {errors}"
    assert len(responses) == n_threads, \
        f"Solo llegaron {len(responses)}/{n_threads} respuestas"

    fallidos = {i: s for i, s in responses.items() if s != 200}
    assert not fallidos, \
        f"Requests concurrentes fallaron (status != 200): {fallidos}\nBodies: {bodies}"

    statuses = list(responses.values())
    return f"{n_threads}/{n_threads} requests simultáneos → statuses {statuses}"


# ══════════════════════════════════════════════════════════════════════════════
# TESTS EXTRA — Casos borde importantes
# ══════════════════════════════════════════════════════════════════════════════
def test_5_archivo_vacio():
    code = fresh_code("basic")
    res  = post_csv(code, b"")
    assert res.status_code == 400, f"Esperaba 400 para archivo vacío, recibí {res.status_code}"
    return f"Archivo vacío → 400: '{res.json()['detail']}'"


def test_6_extension_invalida():
    code = fresh_code("basic")
    csv  = make_csv(["nombre"], [["Producto"]])
    # Subimos con extensión .xlsx
    res = client.post("/procesar", data={
        "email": "qa@describeai.store", "storeName": "QA", "tone": "profesional",
        "lang": "es", "access_code": code,
    }, files={"file": ("datos.xlsx", csv, "application/vnd.ms-excel")})
    assert res.status_code == 400, f"Esperaba 400 para .xlsx, recibí {res.status_code}"
    assert ".xlsx" in res.json().get("detail", "").lower() or "permitido" in res.json().get("detail", "").lower()
    return f"Extensión .xlsx → 400: '{res.json()['detail']}'"


def test_7_codigo_invalido():
    csv = make_csv(["nombre"], [["Producto"]])
    res = post_csv("INVALIDO-XXXX", csv)
    assert res.status_code == 400
    return f"Código inválido → 400: '{res.json()['detail']}'"


def test_8_codigo_ya_usado():
    code = fresh_code("basic")
    csv  = make_csv(["nombre", "categoria", "caracteristicas"],
                    [["Producto", "Cat", "Feat"]])
    # Primer uso — debe pasar
    res1 = post_csv(code, csv)
    assert res1.status_code == 200, f"Primer uso falló: {res1.json()}"
    # Segundo uso — debe rechazar
    res2 = post_csv(code, csv)
    assert res2.status_code == 400
    assert "usado" in res2.json().get("detail", "").lower()
    return f"Reutilización de código → 400: '{res2.json()['detail']}'"


# ── Runner principal ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═" * 62)
    print("   DescribeAI — Test Suite de Integración")
    print("   Backend: app.py  |  Cliente: FastAPI TestClient")
    print("═" * 62)

    run_test("Test 1 — Alias de columna ('name' → 'nombre')",          test_1_alias_columna)
    run_test("Test 2 — Columnas inválidas (sku, precio, stock)",        test_2_columnas_invalidas)
    run_test("Test 3 — Excede límite del plan basic (51 > 50)",         test_3_limite_plan)
    run_test("Test 4 — Concurrencia (3 requests simultáneos)",          test_4_concurrencia)
    run_test("Test 5 — Archivo vacío",                                  test_5_archivo_vacio)
    run_test("Test 6 — Extensión inválida (.xlsx rechazado)",           test_6_extension_invalida)
    run_test("Test 7 — Código de acceso inválido",                      test_7_codigo_invalido)
    run_test("Test 8 — Código ya usado (reutilización bloqueada)",      test_8_codigo_ya_usado)

    # ── Reporte final ──────────────────────────────────────────────────────────
    passed  = sum(1 for _, ok, _ in results if ok)
    failed  = sum(1 for _, ok, _ in results if not ok)
    total   = len(results)

    print("\n" + "═" * 62)
    print(f"  Resultado final: {passed}/{total} tests pasaron")
    print()

    for name, ok, msg in results:
        icon = "✅" if ok else "❌"
        print(f"  {icon}  {name}")
        if not ok and msg:
            print(f"      {RED}↳ {msg[:100]}{RESET}")

    print()
    if passed == total:
        print(f"  {GREEN}🎉 Todos los tests PASSED — backend blindado y listo para producción.{RESET}")
    else:
        print(f"  {YELLOW}⚠️  {failed} test(s) fallaron. Revisá los detalles arriba.{RESET}")
    print("═" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
