# =============================================================================
# app.py — Normalizador COMUNAS_NORM
# Arquitectura y Almacenamiento de Datos — Evaluación 2 · 2026
# Integrantes: Jostin Sáez, Gerardo Millán, Eduardo Díaz
# =============================================================================
# Descripción:
#   Aplicación web Flask que permite cargar un archivo .txt con nombres de
#   comunas, normalizar los datos (formato, tildes, ñ, duplicados, espacios),
#   almacenar el resultado en una base de datos SQLite y descargar el CSV,
#   log de cambios o script SQL resultante.
# =============================================================================

import os           # Manejo de rutas y variables de entorno
import re           # Expresiones regulares para limpieza de texto
import sqlite3      # Motor de base de datos SQLite (sin instalación extra)
import unicodedata  # Para remover tildes correctamente (Unicode)
from datetime import datetime  # Registro de fechas en el log
from io import StringIO        # Buffer en memoria para generar archivos

# Flask: framework web minimalista para Python
from flask import (
    Flask, render_template, request,
    jsonify, send_file, g
)

# ===========================================================================
# CONFIGURACIÓN DE LA APLICACIÓN
# ===========================================================================

# Crear la instancia de la aplicación Flask
app = Flask(__name__)

# Ruta del archivo de base de datos SQLite
# En Railway, DATABASE_URL puede apuntar a otro motor, aquí usamos SQLite local
DATABASE = os.environ.get('DATABASE_PATH', 'comunas_norm.db')

# Puerto: Railway inyecta la variable PORT automáticamente
PORT = int(os.environ.get('PORT', 5000))


# ===========================================================================
# BASE DE DATOS — CONEXIÓN Y ESQUEMA
# ===========================================================================

def get_db():
    """
    Obtiene la conexión a la base de datos SQLite.
    Usa el objeto 'g' de Flask para reutilizar la conexión
    dentro de una misma petición HTTP (patrón recomendado en Flask).
    """
    if 'db' not in g:
        # Conectar (crea el archivo si no existe)
        g.db = sqlite3.connect(DATABASE)
        # Devolver filas como diccionarios en vez de tuplas
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    """
    Cierra la conexión a la base de datos al finalizar cada petición.
    Se registra automáticamente con app.teardown_appcontext.
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()


# Registrar el cierre automático al final de cada request
app.teardown_appcontext(close_db)


def init_db():
    """
    Crea las tablas necesarias si no existen.
    Se llama una vez al iniciar la aplicación.

    Tablas:
      - COMUNAS_NORM : almacena los nombres normalizados y únicos
      - PROCESO_LOG  : guarda el historial de cada procesamiento
    """
    db = sqlite3.connect(DATABASE)
    cursor = db.cursor()

    # Tabla principal: comunas normalizadas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS COMUNAS_NORM (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_comuna  TEXT NOT NULL UNIQUE,  -- único para evitar duplicados a nivel BD
            fecha_insercion TEXT NOT NULL          -- cuándo se insertó el registro
        )
    ''')

    # Tabla de log: cada fila representa un cambio detectado durante el proceso ETL
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS PROCESO_LOG (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id    TEXT NOT NULL,    -- identificador único por procesamiento
            linea_num    INTEGER,          -- número de línea en el archivo original
            valor_orig   TEXT,             -- valor antes de normalizar
            valor_norm   TEXT,             -- valor después de normalizar
            estado       TEXT,             -- OK | MODIFICADO | DUPLICADO
            fecha        TEXT NOT NULL     -- timestamp del procesamiento
        )
    ''')

    db.commit()
    db.close()
    print("[DB] Base de datos inicializada correctamente.")


# ===========================================================================
# FUNCIONES DE NORMALIZACIÓN (núcleo del ETL)
# ===========================================================================

def quitar_tildes(texto):
    """
    Elimina tildes y diacríticos usando Unicode NFD.
    Ejemplo: 'Ñiquén' → 'Niquen' (si también se aplica reemplazar_enie)

    Proceso:
      1. NFD descompone caracteres: 'á' → 'a' + combinación de acento
      2. Se filtran solo las categorías 'L' (letras) y 'N' (números) y espacios/guiones
      3. El resultado es texto sin marcas diacríticas
    """
    # Normalizar a NFD (descomponer caracteres compuestos)
    nfd = unicodedata.normalize('NFD', texto)
    # Filtrar: conservar solo caracteres que NO sean marcas diacríticas (Mn)
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')


def reemplazar_enie(texto):
    """
    Reemplaza ñ/Ñ por n/N según corresponda.
    Se aplica ANTES de cambiar el case para preservar correctamente
    mayúsculas y minúsculas.
    Ejemplo: 'Ñuñoa' → 'Nunoa'
    """
    return texto.replace('ñ', 'n').replace('Ñ', 'N')


def a_titulo(texto):
    """
    Convierte el texto a formato Título con reglas del español.
    Las preposiciones y artículos cortos se mantienen en minúsculas
    (excepto la primera palabra).

    Ejemplo: 'SAN PEDRO DE LA PAZ' → 'San Pedro de la Paz'
    """
    # Palabras que van en minúsculas salvo que sean la primera
    minusculas = {'de', 'del', 'la', 'las', 'los', 'el', 'y', 'e',
                  'o', 'a', 'en', 'al', 'con', 'por', 'para', 'entre',
                  'sin', 'sobre', 'bajo', 'ante', 'tras', 'desde', 'hasta'}

    palabras = texto.lower().split()
    resultado = []
    for i, p in enumerate(palabras):
        if i == 0 or p not in minusculas:
            resultado.append(p.capitalize())
        else:
            resultado.append(p)
    return ' '.join(resultado)


def aplicar_formato(texto, fmt):
    """
    Aplica el formato de texto seleccionado por el usuario.
    Parámetros:
      texto : string ya limpio (sin tildes/ñ si se eligió esa opción)
      fmt   : 'titulo' | 'mayus' | 'minus'
    """
    # Limpiar apóstrofes con espacio: "O' Higgins" → "O'Higgins"
    texto = re.sub(r"'\s+", "'", texto)

    if fmt == 'titulo':
        return a_titulo(texto)
    elif fmt == 'mayus':
        return texto.upper()
    elif fmt == 'minus':
        return texto.lower()
    return texto  # fallback: sin cambio


def normalizar_valor(raw, opts):
    """
    Aplica todas las transformaciones configuradas a un valor crudo.

    Parámetros:
      raw  : string original leído del archivo
      opts : dict con las opciones activadas por el usuario

    Flujo de transformaciones:
      1. Limpiar espacios múltiples
      2. Quitar tildes
      3. Reemplazar Ñ
      4. Aplicar formato de texto
    """
    val = raw.strip()

    # Paso 1: corregir espacios múltiples
    if opts.get('spaces'):
        val = re.sub(r'\s+', ' ', val)

    # Paso 2: eliminar tildes y acentos
    if opts.get('tildes'):
        val = quitar_tildes(val)

    # Paso 3: reemplazar Ñ → N
    if opts.get('enie'):
        val = reemplazar_enie(val)

    # Paso 4: aplicar formato (Título / MAYÚSCULAS / minúsculas)
    val = aplicar_formato(val, opts.get('fmt', 'titulo'))

    return val


def clave_dedup(texto):
    """
    Genera una clave de comparación para detectar duplicados.
    Elimina TODOS los caracteres no alfanuméricos y convierte a minúsculas.
    Esto permite detectar como iguales: 'Santiago', 'SANTIAGO', 'sanitago'

    Ejemplo:
      'San Pedro de la Paz' → 'sanpedodelapaz'
      'SAN PEDRO DE LA PAZ' → 'sanpedodelapaz'  ← mismo resultado → duplicado
    """
    sin_tildes = quitar_tildes(texto)
    sin_enie   = sin_tildes.replace('ñ', 'n').replace('Ñ', 'N')
    solo_alfa  = re.sub(r'[^a-z0-9]', '', sin_enie.lower())
    return solo_alfa


# ===========================================================================
# FUNCIÓN PRINCIPAL DE PROCESAMIENTO
# ===========================================================================

def procesar_datos(lineas, opts, sesion_id):
    """
    Orquesta todo el proceso ETL sobre la lista de líneas del archivo.

    Retorna un diccionario con:
      - rows       : lista de dicts con original, normalizado, estado, línea
      - resultado  : lista final de valores únicos y normalizados
      - stats      : estadísticas del proceso
      - log_lines  : líneas del log de texto plano
    """
    log_lines = []
    rows = []
    resultado = []
    seen = {}          # clave_dedup → número de línea donde se vio primero
    dup_count = 0
    changed_count = 0

    # Cabecera del log
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_lines.append('=' * 55)
    log_lines.append('  LOG COMUNAS_NORM — Proceso ETL')
    log_lines.append('=' * 55)
    log_lines.append(f'Fecha              : {now}')
    log_lines.append(f'Sesión ID          : {sesion_id}')
    log_lines.append(f'Registros cargados : {len(lineas)}')
    log_lines.append(f'Formato            : {opts.get("fmt")}')
    log_lines.append(f'Quitar tildes      : {"Sí" if opts.get("tildes") else "No"}')
    log_lines.append(f'Reemplazar Ñ→N     : {"Sí" if opts.get("enie") else "No"}')
    log_lines.append(f'Eliminar duplic.   : {"Sí" if opts.get("dedup") else "No"}')
    log_lines.append(f'Limpiar espacios   : {"Sí" if opts.get("spaces") else "No"}')
    log_lines.append('-' * 55)
    log_lines.append('DETALLE DE CAMBIOS:')
    log_lines.append('-' * 55)

    for idx, original in enumerate(lineas):
        num = idx + 1

        # Normalizar el valor actual
        normalizado = normalizar_valor(original, opts)

        # Detectar si hubo cambio
        changed = original.strip() != normalizado

        # Generar clave para comparación de duplicados
        clave = clave_dedup(normalizado)

        # Detectar duplicado
        if opts.get('dedup') and clave in seen:
            estado = 'DUPLICADO'
            dup_count += 1
            log_lines.append(
                f'[{str(num).rjust(5)}] DUPLICADO  | '
                f'"{original}" → "{normalizado}" '
                f'(igual a línea {seen[clave]})'
            )
        else:
            # Registrar como visto
            if opts.get('dedup'):
                seen[clave] = num

            if changed:
                estado = 'MODIFICADO'
                changed_count += 1
                log_lines.append(
                    f'[{str(num).rjust(5)}] MODIFICADO | '
                    f'"{original.strip()}" → "{normalizado}"'
                )
            else:
                estado = 'OK'

            # Agregar al resultado final
            resultado.append(normalizado)

        # Guardar fila para la vista previa y la BD
        rows.append({
            'linea':       num,
            'original':    original.strip(),
            'normalizado': normalizado,
            'estado':      estado
        })

    # Pie del log
    log_lines.append('-' * 55)
    log_lines.append(f'Registros originales  : {len(lineas)}')
    log_lines.append(f'Duplicados eliminados : {dup_count}')
    log_lines.append(f'Registros únicos      : {len(resultado)}')
    log_lines.append(f'Valores modificados   : {changed_count}')
    log_lines.append('=' * 55)
    log_lines.append('FIN DEL LOG')

    return {
        'rows':      rows,
        'resultado': resultado,
        'log_lines': log_lines,
        'stats': {
            'total':    len(lineas),
            'unicos':   len(resultado),
            'duplicados': dup_count,
            'modificados': changed_count
        }
    }


# ===========================================================================
# FUNCIONES DE PERSISTENCIA EN BASE DE DATOS
# ===========================================================================

def guardar_en_db(resultado, rows, sesion_id):
    """
    Guarda los resultados del proceso ETL en la base de datos SQLite.

    Tablas afectadas:
      - COMUNAS_NORM : insertar comunas únicas (INSERT OR IGNORE para no fallar si ya existe)
      - PROCESO_LOG  : registrar cada fila procesada con su estado
    """
    db = get_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Insertar comunas normalizadas en COMUNAS_NORM
    # INSERT OR IGNORE: si el nombre ya existe (UNIQUE), no falla
    for nombre in resultado:
        db.execute(
            'INSERT OR IGNORE INTO COMUNAS_NORM (nombre_comuna, fecha_insercion) VALUES (?, ?)',
            (nombre, now)
        )

    # Insertar cada fila en el log de proceso
    for r in rows:
        db.execute(
            '''INSERT INTO PROCESO_LOG
               (sesion_id, linea_num, valor_orig, valor_norm, estado, fecha)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (sesion_id, r['linea'], r['original'], r['normalizado'], r['estado'], now)
        )

    # Confirmar los cambios en la base de datos
    db.commit()


# ===========================================================================
# RUTAS HTTP (endpoints de la API)
# ===========================================================================

@app.route('/')
def index():
    """
    Ruta raíz: sirve la interfaz web principal (index.html).
    """
    return render_template('index.html')


@app.route('/api/normalizar', methods=['POST'])
def api_normalizar():
    """
    Endpoint principal del ETL.
    Recibe el archivo y las opciones via POST multipart/form-data.
    Procesa los datos, los guarda en la BD y retorna JSON con resultados.

    Body esperado:
      - archivo : archivo .txt (multipart)
      - fmt     : 'titulo' | 'mayus' | 'minus'
      - tildes  : 'true' | 'false'
      - enie    : 'true' | 'false'
      - dedup   : 'true' | 'false'
      - spaces  : 'true' | 'false'

    Retorna JSON con stats, primeras 200 filas para preview y log.
    """
    # Verificar que se recibió un archivo
    if 'archivo' not in request.files:
        return jsonify({'error': 'No se recibió ningún archivo'}), 400

    archivo = request.files['archivo']

    if archivo.filename == '':
        return jsonify({'error': 'Nombre de archivo vacío'}), 400

    # Leer el contenido del archivo y separar en líneas
    contenido = archivo.read().decode('utf-8', errors='replace')
    lineas = [l.strip() for l in contenido.splitlines() if l.strip()]

    if not lineas:
        return jsonify({'error': 'El archivo está vacío o no tiene datos válidos'}), 400

    # Leer opciones enviadas desde el frontend
    opts = {
        'fmt':    request.form.get('fmt', 'titulo'),
        'tildes': request.form.get('tildes', 'true') == 'true',
        'enie':   request.form.get('enie', 'true')   == 'true',
        'dedup':  request.form.get('dedup', 'true')  == 'true',
        'spaces': request.form.get('spaces', 'true') == 'true',
    }

    # Generar ID único para esta sesión de procesamiento
    sesion_id = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Ejecutar el proceso ETL
    resultado_etl = procesar_datos(lineas, opts, sesion_id)

    # Guardar en la base de datos
    guardar_en_db(
        resultado_etl['resultado'],
        resultado_etl['rows'],
        sesion_id
    )

    # Preparar respuesta JSON (solo las primeras 200 filas para la preview)
    return jsonify({
        'sesion_id': sesion_id,
        'stats':     resultado_etl['stats'],
        'preview':   resultado_etl['rows'][:200],
        'log':       '\n'.join(resultado_etl['log_lines'])
    })


@app.route('/api/descargar/<sesion_id>/<tipo>')
def api_descargar(sesion_id, tipo):
    """
    Genera y descarga archivos del resultado del procesamiento.
    Parámetros:
      sesion_id : ID de la sesión retornado por /api/normalizar
      tipo      : 'csv' | 'log' | 'sql'
    """
    db = get_db()

    if tipo == 'csv':
        # Obtener comunas únicas de COMUNAS_NORM
        filas = db.execute(
            'SELECT id, nombre_comuna FROM COMUNAS_NORM ORDER BY id'
        ).fetchall()

        buf = StringIO()
        buf.write('id,nombre_comuna\n')  # cabecera
        for f in filas:
            buf.write(f'{f["id"]},"{f["nombre_comuna"]}"\n')

        buf.seek(0)
        return send_file(
            StringIO(buf.read()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='COMUNAS_NORM.csv'
        )

    elif tipo == 'log':
        # Obtener el log de esta sesión específica
        filas = db.execute(
            '''SELECT linea_num, valor_orig, valor_norm, estado, fecha
               FROM PROCESO_LOG WHERE sesion_id = ? ORDER BY linea_num''',
            (sesion_id,)
        ).fetchall()

        buf = StringIO()
        buf.write(f'=== LOG COMUNAS_NORM — Sesión {sesion_id} ===\n\n')
        buf.write(f'{"#".ljust(6)} {"ESTADO".ljust(12)} {"ORIGINAL".ljust(35)} {"NORMALIZADO"}\n')
        buf.write('-' * 80 + '\n')
        for f in filas:
            buf.write(
                f'{str(f["linea_num"]).rjust(5)}  '
                f'{f["estado"].ljust(12)} '
                f'{f["valor_orig"].ljust(35)} '
                f'→ {f["valor_norm"]}\n'
            )

        buf.seek(0)
        return send_file(
            StringIO(buf.read()),
            mimetype='text/plain',
            as_attachment=True,
            download_name=f'log_comunas_{sesion_id}.txt'
        )

    elif tipo == 'sql':
        # Generar script INSERT para COMUNAS_NORM
        filas = db.execute(
            'SELECT nombre_comuna FROM COMUNAS_NORM ORDER BY id'
        ).fetchall()

        buf = StringIO()
        buf.write('-- ===========================================\n')
        buf.write('-- Script SQL: tabla COMUNAS_NORM\n')
        buf.write(f'-- Generado: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        buf.write(f'-- Total registros: {len(filas)}\n')
        buf.write('-- ===========================================\n\n')
        buf.write('CREATE TABLE IF NOT EXISTS COMUNAS_NORM (\n')
        buf.write('    id             INT AUTO_INCREMENT PRIMARY KEY,\n')
        buf.write('    nombre_comuna  VARCHAR(100) NOT NULL UNIQUE\n')
        buf.write(');\n\n')
        buf.write('INSERT INTO COMUNAS_NORM (nombre_comuna) VALUES\n')

        valores = [f"    ('{f['nombre_comuna'].replace(chr(39), chr(39)+chr(39))}')" for f in filas]
        buf.write(',\n'.join(valores) + ';\n')

        buf.seek(0)
        return send_file(
            StringIO(buf.read()),
            mimetype='text/plain',
            as_attachment=True,
            download_name='insert_comunas_norm.sql'
        )

    return jsonify({'error': 'Tipo de descarga no válido'}), 400


@app.route('/api/comunas')
def api_comunas():
    """
    Retorna todas las comunas almacenadas en COMUNAS_NORM como JSON.
    Útil para verificar el estado actual de la base de datos.
    """
    db = get_db()
    filas = db.execute(
        'SELECT id, nombre_comuna, fecha_insercion FROM COMUNAS_NORM ORDER BY nombre_comuna'
    ).fetchall()
    return jsonify([dict(f) for f in filas])


@app.route('/api/limpiar', methods=['POST'])
def api_limpiar():
    """
    Limpia la tabla COMUNAS_NORM para empezar de cero.
    Útil para pruebas o cuando se quiere procesar un nuevo dataset limpio.
    """
    db = get_db()
    db.execute('DELETE FROM COMUNAS_NORM')
    db.execute('DELETE FROM PROCESO_LOG')
    db.commit()
    return jsonify({'mensaje': 'Base de datos limpiada correctamente'})


# ===========================================================================
# PUNTO DE ENTRADA
# ===========================================================================

if __name__ == '__main__':
    # Crear las tablas si no existen antes de iniciar el servidor
    init_db()
    print(f"[APP] Servidor iniciado en http://0.0.0.0:{PORT}")
    # debug=False en producción (Railway)
    app.run(host='0.0.0.0', port=PORT, debug=False)
