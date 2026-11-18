import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "ecoclima.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def inicializar_db():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
        print(f"[DB] Base de datos inicializada correctamente en: {DB_PATH}")
    finally:
        conn.close()


def registrar_lectura(nombre_salon: str, temperatura: float, humedad: float, co2_ppm: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # 1. Buscar salón o crearlo automáticamente si es nuevo
        cursor.execute("SELECT id_salon FROM salones WHERE nombre = ?", (nombre_salon,))
        fila = cursor.fetchone()
        if not fila:
            cursor.execute("INSERT INTO salones (nombre) VALUES (?)", (nombre_salon,))
            id_salon = cursor.lastrowid
        else:
            id_salon = fila["id_salon"]
            cursor.execute("UPDATE salones SET activo = 1 WHERE id_salon = ?", (id_salon,))

        # 2. Obtener umbrales del salón para evaluar el estado
        cursor.execute("SELECT * FROM umbrales_salon WHERE id_salon = ?", (id_salon,))
        u = cursor.fetchone()

        if temperatura >= u["temp_critica"] or humedad >= u["hum_critica"] or co2_ppm >= u["co2_critico"]:
            estado = "CRITICA"
        elif temperatura >= u["temp_advertencia"] or humedad >= u["hum_advertencia"] or co2_ppm >= u["co2_advertencia"]:
            estado = "ADVERTENCIA"
        else:
            estado = "OPTIMO"

        # 3. Insertar telemetría (dispara automáticamente el trigger de alertas si no es OPTIMO)
        cursor.execute(
            """
            INSERT INTO lecturas_telemetria (id_salon, temperatura, humedad, co2_ppm, estado_calculado)
            VALUES (?, ?, ?, ?, ?)
            """,
            (id_salon, temperatura, humedad, int(co2_ppm), estado),
        )
        conn.commit()
        return {"id_salon": id_salon, "estado": estado}
    finally:
        conn.close()


def obtener_estado_salones():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vw_estado_actual_salones")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def registrar_comando(nombre_salon: str, accion: str, estado_solicitado: bool, origen: str = "DASHBOARD_WEB"):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id_salon FROM salones WHERE nombre = ?", (nombre_salon,))
        fila = cursor.fetchone()
        if not fila:
            return False

        cursor.execute(
            """
            INSERT INTO historial_comandos (id_salon, accion, estado_solicitado, origen)
            VALUES (?, ?, ?, ?)
            """,
            (fila["id_salon"], accion, 1 if estado_solicitado else 0, origen),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def obtener_alertas(limite: int = 50):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.*, s.nombre AS salon
            FROM alertas a
            JOIN salones s ON a.id_salon = s.id_salon
            ORDER BY a.fecha_alerta DESC, a.id_alerta DESC
            LIMIT ?
            """,
            (limite,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# Prueba directa al ejecutar este archivo
if __name__ == "__main__":
    inicializar_db()
    res = registrar_lectura("SALON 455", 25.5, 55.0, 480)
    print("[DB] Prueba de inserción:", res)
    print("[DB] Estado actual:", obtener_estado_salones())