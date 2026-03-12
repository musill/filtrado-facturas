# -*- coding: utf-8 -*-
import os
import re
import time
import shutil
import glob
from dataclasses import dataclass
from typing import List, Optional, Tuple

from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)


# =========================
# CONFIGURACIÓN PRINCIPAL
# =========================
@dataclass
class Config:
    base_url_login: str = "https://srienlinea.sri.gob.ec/tuportal-internet/"
    url_recibidos_full: str = (
        "https://srienlinea.sri.gob.ec/comprobantes-electronicos-internet/pages/consultas/recibidos/"
        "comprobantesRecibidos.jsf?&contextoMPT=https://srienlinea.sri.gob.ec/tuportal-internet"
        "&pathMPT=Facturaci%C3%B3n%20Electr%C3%B3nica"
        "&actualMPT=Comprobantes%20electr%C3%B3nicos%20recibidos%20"
        "&linkMPT=%2Fcomprobantes-electronicos-internet%2Fpages%2Fconsultas%2Frecibidos%2FcomprobantesRecibidos.jsf%3F"
        "&esFavorito=S"
    )
    download_dir: str = os.path.join(os.getcwd(), "facturas_xml")
    headless: bool = False
    wait_short: int = 10
    wait_long: int = 30
    pause_after_click: float = 1.0  # pausa tras cada click de descarga


# =========================
# UTILIDADES DE FS/DESCARGA
# =========================
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def newest_file_in(dir_path: str, pattern: str = "*.xml") -> Optional[str]:
    files = glob.glob(os.path.join(dir_path, pattern))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def wait_for_no_crdownload(dir_path: str, timeout: int = 120) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if not glob.glob(os.path.join(dir_path, "*.crdownload")):
            return True
        time.sleep(0.5)
    return False


def move_new_xml_renamed(
    download_dir: str,
    dest_dir: str,
    before_ts: float,
    prefix: Optional[str] = None,
) -> Optional[str]:
    """
    Mueve el XML más nuevo llegado después de before_ts al dest_dir.
    Si prefix está definido, renombra a: <prefix>_<archivoOriginal>.xml
    Devuelve la ruta destino si movió algo; None si no detectó nuevo.
    """
    ensure_dir(dest_dir)
    wait_for_no_crdownload(download_dir, timeout=120)

    nf = newest_file_in(download_dir, "*.xml")
    if nf and os.path.getmtime(nf) >= before_ts:
        base = os.path.basename(nf)

        # Sanitizar prefijo para nombre de archivo
        if prefix:
            sprefix = re.sub(r"[^0-9A-Za-z_-]+", "", prefix)
            dest_name = f"{sprefix}_{base}"
        else:
            dest_name = base

        dest = os.path.join(dest_dir, dest_name)

        # Evitar sobreescritura añadiendo sufijo incremental
        if os.path.exists(dest):
            name, ext = os.path.splitext(dest_name)
            i = 2
            while True:
                candidate = os.path.join(dest_dir, f"{name}_{i}{ext}")
                if not os.path.exists(candidate):
                    dest = candidate
                    break
                i += 1

        shutil.move(nf, dest)
        return dest
    return None


# =========================
# UTILIDADES SELENIUM
# =========================
def build_driver(cfg: Config):
    ensure_dir(cfg.download_dir)
    options = webdriver.ChromeOptions()

    # ✅ Safe Browsing ACTIVADO (valores por defecto)
    prefs = {
        "download.default_directory": cfg.download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,

        # Permitir múltiples descargas sin pedir confirmación
        "profile.default_content_setting_values.automatic_downloads": 1,
        # NO desactivamos safebrowsing
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--window-size=1280,900")
    if cfg.headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # Reducir huella de automatización
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")

    # ⛔️ Importante: NO agregar --safebrowsing-disable-download-protection

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(cfg.wait_long)

    # Ocultar navigator.webdriver (opcional)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
        )
    except Exception:
        pass

    return driver


def switch_to_last_window(driver):
    if len(driver.window_handles) > 1:
        driver.switch_to.window(driver.window_handles[-1])


def find_in_root_or_iframes(driver, locators, timeout=5):
    driver.switch_to.default_content()
    wait = WebDriverWait(driver, timeout)
    # raíz
    for by, sel in locators:
        try:
            return wait.until(EC.presence_of_element_located((by, sel)))
        except TimeoutException:
            continue
    # iframes
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for iframe in iframes:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(iframe)
            for by, sel in locators:
                try:
                    return WebDriverWait(driver, 2).until(EC.presence_of_element_located((by, sel)))
                except TimeoutException:
                    continue
        except Exception:
            continue
    driver.switch_to.default_content()
    return None


def is_on_login_page(driver) -> bool:
    try:
        if driver.find_elements(By.ID, "usuario") and driver.find_elements(By.ID, "password"):
            return True
    except Exception:
        pass
    return False


def is_on_recibidos_page(driver) -> bool:
    locators = [
        (By.CSS_SELECTOR, "select[id$=':ano']"),
        (By.XPATH, "//select[contains(@id,':ano') or contains(@name,':ano')]"),
        (By.CSS_SELECTOR, "select.sri-input-combo-anio"),
    ]
    el = find_in_root_or_iframes(driver, locators, timeout=3)
    return el is not None


# =========================
# PARSING DE FILAS
# =========================
ROW_NUMBER_XPATH = ".//td[1]//div"
DATE_REGEX = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*$")

def parse_rows_with_metadata(driver) -> List[Tuple[str, str, str, str, object]]:
    """
    Devuelve lista de tuplas por fila:
      (numero_str, anio, mes, clave_acceso, xml_link_element)
    - numero_str: texto de la primera columna (1, 2, 3, ...)
    - anio/mes: de la fecha 'dd/mm/yyyy' (fecha de emisión)
    - clave_acceso: texto del <a> de detalle (0401...); sirve como ID único
    - xml_link_element: <a> del icono XML
    """
    rows = driver.find_elements(By.XPATH, "//tr[@role='row' and @data-ri]")
    entries = []
    for row in rows:
        # Número
        try:
            numero = (row.find_element(By.XPATH, ROW_NUMBER_XPATH).text or "").strip()
        except Exception:
            numero = ""

        # Fecha emisión dd/mm/yyyy -> año/mes
        anio, mes = "desconocido", "desconocido"
        for dc in row.find_elements(By.XPATH, ".//td//div"):
            txt = (dc.text or "").strip()
            m = DATE_REGEX.match(txt)
            if m:
                dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
                anio, mes = yyyy, mm
                break

        # Clave de acceso (texto del <a> de detalle grande, sin img)
        clave_acceso = ""
        try:
            ca_el = row.find_element(
                By.XPATH,
                ".//a[starts-with(@id,'frmPrincipal:tablaCompRecibidos') and not(img)]"
            )
            clave_acceso = (ca_el.text or "").strip()
        except Exception:
            pass

        # Enlace al XML (ícono)
        xml_link = None
        try:
            xml_link = row.find_element(By.XPATH, ".//a[img[contains(@src,'xml.gif')]]")
        except Exception:
            pass

        if xml_link:
            entries.append((numero, anio, mes, clave_acceso, xml_link))

    return entries


# =========================
# DESCARGA PÁGINA A PÁGINA
# =========================
def click_next_page(driver) -> bool:
    candidates = [
        "//a[contains(@class,'ui-paginator-next') and not(contains(@class,'ui-state-disabled'))]",
        "//a[contains(text(),'»') or contains(.,'Siguiente') or contains(.,'>')]",
    ]
    for xp in candidates:
        try:
            el = driver.find_element(By.XPATH, xp)
            cls = el.get_attribute("class") or ""
            aria = el.get_attribute("aria-disabled") or "false"
            if "disabled" in cls or aria == "true":
                continue
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            el.click()
            return True
        except NoSuchElementException:
            continue
        except Exception:
            continue
    return False


# Mantener dedupe entre páginas durante la ejecución
SEEN_KEYS = set()

def download_all_xml_from_current_results(driver, cfg: Config):
    """
    Recorre TODAS las páginas de resultados actuales y descarga:
      - Carpeta destino: facturas_xml/<AAAA>/<MM>/
      - Nombre: <NUMERO>_<CLAVEACCESO>_<archivoOriginal>.xml
      - Evita duplicados usando CLAVEACCESO (SEEN_KEYS)
    """
    total_downloads = 0
    page_idx = 1

    while True:
        entries = parse_rows_with_metadata(driver)
        print(f"   - Página {page_idx}: {len(entries)} filas con XML detectadas.")

        for (numero, anio, mes, clave_acceso, link) in entries:
            # Dedupe por clave de acceso si la tenemos
            if clave_acceso and clave_acceso in SEEN_KEYS:
                continue

            try:
                before_ts = time.time()
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
                try:
                    link.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", link)

                time.sleep(cfg.pause_after_click)

                # Directorio por año/mes (o 'desconocido')
                dest_dir = os.path.join(cfg.download_dir, anio, mes)

                # Prefijo: numero + clave (si existen)
                prefix_parts = []
                if numero:
                    prefix_parts.append(numero)
                if clave_acceso:
                    prefix_parts.append(clave_acceso)
                prefix = "_".join(prefix_parts) if prefix_parts else None

                moved_path = move_new_xml_renamed(cfg.download_dir, dest_dir, before_ts, prefix=prefix)

                if moved_path:
                    total_downloads += 1
                    if clave_acceso:
                        SEEN_KEYS.add(clave_acceso)
                    print(f"      · [{numero or '-'}] XML → {moved_path}")
                else:
                    # Reintento corto
                    time.sleep(1.5)
                    moved_path = move_new_xml_renamed(cfg.download_dir, dest_dir, before_ts, prefix=prefix)
                    if moved_path:
                        total_downloads += 1
                        if clave_acceso:
                            SEEN_KEYS.add(clave_acceso)
                        print(f"      · [{numero or '-'}] XML → {moved_path}")
                    else:
                        print(f"      ⚠ No se detectó nuevo XML para la fila [{numero or '-'}].")

            except StaleElementReferenceException:
                print("      ⚠ Enlace obsoleto (stale). Continuando…")
            except Exception as e:
                print(f"      ⚠ Error al descargar un XML de la fila [{numero or '-'}]: {e}")

        # Siguiente página
        if not click_next_page(driver):
            break
        page_idx += 1
        time.sleep(2)

    print(f"\n✅ Descarga completa de la búsqueda actual: {total_downloads} archivos.")
    print(f"📁 Carpeta base: {cfg.download_dir}")
    return total_downloads


# =========================
# FLUJO PRINCIPAL (MODO MANUAL)
# =========================
def main():
    load_dotenv()
    cfg = Config()

    driver = build_driver(cfg)

    try:
        # 1) Abrimos login y mostramos menú de comandos
        driver.get(cfg.base_url_login)
        WebDriverWait(driver, cfg.wait_long).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        print("\n🔐 LOGIN MANUAL")
        print(" - En el navegador: inicia sesión manualmente (y resuelve captcha si sale).")
        print(" - Navega a: Facturación Electrónica → Comprobantes electrónicos recibidos.")
        print(" - Elige Año / Mes / Día / Tipo y presiona Buscar (todo manual).")
        print(" - Comandos en consola:")
        print("       d  → descargar TODOS los XML de la búsqueda actual (paginación automática)")
        print("       l  → abrir login de nuevo (si te expulsó)")
        print("       r  → abrir URL directa de 'Recibidos' (si hay sesión)")
        print("       q  → salir\n")

        while True:
            try:
                cmd = input("Comando [d/l/r/q]: ").strip().lower()
            except EOFError:
                cmd = "d"

            if cmd == "q":
                print("Saliendo…")
                break

            if cmd == "l":
                driver.get(cfg.base_url_login)
                print("➡️ Abriendo login. Inicia sesión nuevamente y navega a 'Recibidos'.")
                continue

            if cmd == "r":
                driver.get(cfg.url_recibidos_full)
                switch_to_last_window(driver)
                print("➡️ Intentando abrir 'Recibidos' directamente (requiere sesión activa).")
                continue

            if cmd == "d":
                if is_on_login_page(driver):
                    print("⚠️ Estás en la pantalla de login. Inicia sesión, navega a 'Recibidos', aplica filtros y pulsa Buscar.")
                    continue
                if not is_on_recibidos_page(driver):
                    print("⚠️ No detecto los combos de Año/Mes/Día/Tipo. Abre 'Recibidos', aplica filtros y pulsa Buscar.")
                    continue

                download_all_xml_from_current_results(driver, cfg)
                print("\n➡️ Puedes cambiar filtros en el portal y volver a presionar 'd' para otra tanda.")
                continue

            print("Comando no reconocido. Usa: d (descargar) / l (login) / r (recibidos directo) / q (salir).")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
