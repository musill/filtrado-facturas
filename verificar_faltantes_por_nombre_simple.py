import re
import csv
import glob
from pathlib import Path
from collections import defaultdict

# Si existe ./facturas_xml, úsalo; si no, asume que estás dentro de facturas_xml
BASE_DIR = Path("./facturas_xml") if Path("./facturas_xml").exists() else Path(".")
MESES = [f"{i:02d}" for i in range(1, 13)]

# Extrae el PRIMER grupo de dígitos que aparezca en el nombre (sin extensión)
# Ejemplos válidos: "23_", "23 ", "23", "23-algo", "23(1)", "23.xml"
RE_NUM = re.compile(r"(\d+)")

def extraer_numero_desde_nombre(path: Path):
    """Devuelve el primer entero encontrado en el nombre de archivo (sin extensión), o None."""
    nombre = path.stem  # sin .xml
    m = RE_NUM.search(nombre)
    if not m:
        return None
    try:
        return int(m.group(1))
    except:
        return None

def verificar_anio_por_nombre_simple(anio: str, export_csv: bool = True):
    # Soporta correr desde raíz o desde dentro de facturas_xml
    year_dir = (BASE_DIR / anio) if BASE_DIR != Path(".") else Path("./" + anio)
    if not year_dir.exists():
        print(f"❌ No existe la carpeta: {year_dir}")
        return

    # { mes: set(numeros_encontrados) }
    datos = defaultdict(set)

    for mes in MESES:
        mes_dir = year_dir / mes
        if not mes_dir.exists():
            continue
        for xml_file in glob.glob(str(mes_dir / "*.xml")):
            n = extraer_numero_desde_nombre(Path(xml_file))
            if n is not None:
                datos[mes].add(n)

    filas_csv = []

    print(f"\n== Verificación por NOMBRE SIMPLE – Año {anio} ==")
    for mes in MESES:
        nums = sorted(datos.get(mes, set()))
        if not nums:
            continue

        max_n = max(nums)  # “el último número del archivo de cada mes es el total que hay”
        expected = set(range(1, max_n + 1))
        faltan = sorted(expected - set(nums))

        if faltan:
            print(f"\nMes {mes}: esperado 1..{max_n} | encontrados={len(nums)} → FALTAN {len(faltan)}")
            muestra = ", ".join(map(str, faltan[:25]))
            if len(faltan) > 25:
                muestra += f", ... (+{len(faltan)-25})"
            print(f"  Faltantes: {muestra}")
        else:
            print(f"\nMes {mes}: esperado 1..{max_n} | encontrados={len(nums)} → OK ✅ (sin faltantes)")

        if export_csv:
            filas_csv.append({
                "anio": anio,
                "mes": mes,
                "max_esperado": max_n,
                "encontrados": len(nums),
                "faltantes_cantidad": len(faltan),
                "faltantes": ",".join(map(str, faltan))
            })

    if export_csv:
        out_csv = Path(f"faltantes_simple_{anio}.csv")
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["anio", "mes", "max_esperado", "encontrados", "faltantes_cantidad", "faltantes"]
            )
            writer.writeheader()
            for row in filas_csv:
                writer.writerow(row)
        print(f"\n📄 CSV generado: {out_csv.resolve()}")

def main():
    anio = input("Ingresa el año a verificar (ej. 2022): ").strip()
    if not anio.isdigit():
        print("⚠️ Año inválido.")
        return
    verificar_anio_por_nombre_simple(anio, export_csv=True)

if __name__ == "__main__":
    main()
