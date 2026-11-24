import json
import os
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import paho.mqtt.client as mqtt

# ==========================================
# 1. CONFIGURACIÓN GENERAL Y MQTT
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ecoclima.db")
DATA_JSON_PATH = os.path.join(BASE_DIR, "data.json")

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TOPICO_TELEMETRIA = "utp/ds8/g6/EcoClima"
TOPICO_CMD = "utp/ds8/g6/EcoClima/cmd"
TOPICO_UMBRALES = "utp/ds8/g6/EcoClima/umbrales"

app = FastAPI(title="EcoClima IoT Enterprise API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 2. ESTADO EN MEMORIA
# ==========================================
salones_data = {}             # Salones activos en el Dashboard
sensores_detectados = {}      # Hardware reportado por el ESP32
asignaciones_sensores = {}    # Vínculo sensor_id -> nombre_salon
mqtt_conectado = False


class AsignacionRequest(BaseModel):
    sensor_id: str
    numero_salon: str


# ==========================================
# 3. BASE DE DATOS SQLITE Y PERSISTENCIA
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS salones (
            id_salon INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            sensor_id TEXT,
            estado_emergencia INTEGER DEFAULT 0,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lecturas_telemetria (
            id_lectura INTEGER PRIMARY KEY AUTOINCREMENT,
            id_salon INTEGER NOT NULL,
            temperatura REAL NOT NULL,
            humedad REAL NOT NULL,
            co2_ppm INTEGER NOT NULL,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (id_salon) REFERENCES salones(id_salon) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS historial_comandos (
            id_comando INTEGER PRIMARY KEY AUTOINCREMENT,
            salon_destino TEXT NOT NULL,
            accion TEXT NOT NULL,
            estado INTEGER NOT NULL,
            fecha_comando TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Migración segura por si la tabla salones ya existía sin la columna sensor_id
    try:
        cursor.execute("ALTER TABLE salones ADD COLUMN sensor_id TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


def guardar_respaldo_json():
    try:
        with open(DATA_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(salones_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[JSON] Error guardando respaldo: {e}")


def persistir_lectura_sqlite(nombre_salon: str, temp: float, hum: float, co2: int, sensor_id: str = None):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO salones (nombre, sensor_id) VALUES (?, ?)",
            (nombre_salon, sensor_id),
        )
        if sensor_id:
            cursor.execute(
                "UPDATE salones SET sensor_id = ? WHERE nombre = ?",
                (sensor_id, nombre_salon),
            )

        cursor.execute("SELECT id_salon FROM salones WHERE nombre = ?", (nombre_salon,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                INSERT INTO lecturas_telemetria (id_salon, temperatura, humedad, co2_ppm)
                VALUES (?, ?, ?, ?)
                """,
                (row[0], temp, hum, co2),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SQLite] Error guardando lectura: {e}")


def eliminar_salon_sqlite(nombre_salon: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("DELETE FROM salones WHERE nombre = ?", (nombre_salon,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SQLite] Error eliminando salón: {e}")


def cargar_estado_persistente():
    """Recupera los salones y vínculos sensor -> salón desde SQLite (o data.json) al iniciar."""
    global salones_data, asignaciones_sensores, sensores_detectados
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id_salon, nombre, sensor_id, estado_emergencia FROM salones")
        salones_db = cursor.fetchall()

        for s in salones_db:
            nombre = s["nombre"]
            sensor_id = s["sensor_id"]
            emergencia = bool(s["estado_emergencia"])

            # Obtener la última telemetría registrada para ese salón
            cursor.execute(
                """
                SELECT temperatura, humedad, co2_ppm
                FROM lecturas_telemetria
                WHERE id_salon = ?
                ORDER BY id_lectura DESC
                LIMIT 1
                """,
                (s["id_salon"],),
            )
            ultima = cursor.fetchone()

            temp = round(float(ultima["temperatura"]), 1) if ultima else 24.0
            hum = round(float(ultima["humedad"]), 1) if ultima else 50.0
            co2 = int(ultima["co2_ppm"]) if ultima else 400

            salones_data[nombre] = {
                "temperature": temp,
                "humidity": hum,
                "co2": co2,
                "emergency": emergencia,
                "sensor_id": sensor_id,
            }

            if sensor_id:
                asignaciones_sensores[sensor_id] = nombre
                pin_num = int(sensor_id.replace("DHT22-GPIO", "")) if "GPIO" in sensor_id else None
                sensores_detectados[sensor_id] = {
                    "sensor_id": sensor_id,
                    "pin": pin_num,
                    "temperature": temp,
                    "humidity": hum,
                    "co2": co2,
                    "salon_asignado": nombre,
                    "ultima_lectura": "Recuperado BD",
                }

        conn.close()

        # Si SQLite estaba vacío pero data.json tenía datos previos, restaurarlos
        if not salones_data and os.path.exists(DATA_JSON_PATH):
            with open(DATA_JSON_PATH, "r", encoding="utf-8") as f:
                respaldo = json.load(f)
            if isinstance(respaldo, dict) and respaldo:
                for nombre, datos in respaldo.items():
                    salones_data[nombre] = datos
                    s_id = datos.get("sensor_id")
                    if s_id:
                        asignaciones_sensores[s_id] = nombre
                    persistir_lectura_sqlite(
                        nombre,
                        float(datos.get("temperature", 24.0)),
                        float(datos.get("humidity", 50.0)),
                        int(datos.get("co2", 400)),
                        s_id,
                    )

        print(f"[PERSISTENCIA] Salones cargados al iniciar: {list(salones_data.keys())}")
    except Exception as e:
        print(f"[PERSISTENCIA] Error cargando estado previo: {e}")


def persistir_comando_sqlite(salon_destino: str, accion: str, estado: bool):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO historial_comandos (salon_destino, accion, estado)
            VALUES (?, ?, ?)
            """,
            (salon_destino, accion, 1 if estado else 0),
        )
        if salon_destino != "GLOBAL":
            cursor.execute(
                "UPDATE salones SET estado_emergencia = ? WHERE nombre = ?",
                (1 if estado else 0, salon_destino),
            )
        else:
            cursor.execute(
                "UPDATE salones SET estado_emergencia = ?",
                (1 if estado else 0,),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SQLite] Error guardando comando: {e}")


# ==========================================
# 4. PROCESAMIENTO DE TELEMETRÍA MQTT
# ==========================================
def procesar_telemetria_mqtt(payload: dict):
    sensor_id = payload.get("sensor_id")
    room_directo = payload.get("room")
    temp = round(float(payload.get("temperature", 0.0)), 1)
    hum = round(float(payload.get("humidity", 0.0)), 1)
    co2 = int(payload.get("co2", 400))

    if sensor_id:
        salon_asignado = asignaciones_sensores.get(sensor_id)
        sensores_detectados[sensor_id] = {
            "sensor_id": sensor_id,
            "pin": payload.get("pin"),
            "temperature": temp,
            "humidity": hum,
            "co2": co2,
            "salon_asignado": salon_asignado,
            "ultima_lectura": datetime.now().strftime("%H:%M:%S"),
        }

        if salon_asignado:
            estado_emergencia = salones_data.get(salon_asignado, {}).get("emergency", False)
            salones_data[salon_asignado] = {
                "temperature": temp,
                "humidity": hum,
                "co2": co2,
                "emergency": estado_emergencia,
                "sensor_id": sensor_id,
            }
            guardar_respaldo_json()
            persistir_lectura_sqlite(salon_asignado, temp, hum, co2, sensor_id)

    elif room_directo:
        estado_emergencia = salones_data.get(room_directo, {}).get("emergency", False)
        salones_data[room_directo] = {
            "temperature": temp,
            "humidity": hum,
            "co2": co2,
            "emergency": estado_emergencia,
        }
        guardar_respaldo_json()
        persistir_lectura_sqlite(room_directo, temp, hum, co2)


def on_connect(client, userdata, flags, rc):
    global mqtt_conectado
    mqtt_conectado = (rc == 0)
    print(f"[MQTT] Conectado al broker (código {rc})")
    client.subscribe(TOPICO_TELEMETRIA)
    print(f"[MQTT] Suscrito a: {TOPICO_TELEMETRIA}")


def on_disconnect(client, userdata, rc):
    global mqtt_conectado
    mqtt_conectado = False


def on_message(client, userdata, msg):
    try:
        raw_payload = msg.payload.decode("utf-8")
        if msg.topic == TOPICO_TELEMETRIA:
            reenviar_telemetria_profesor(raw_payload)
        payload = json.loads(raw_payload)
        procesar_telemetria_mqtt(payload)
    except Exception as e:
        print(f"[MQTT] Error procesando mensaje: {e}")


try:
    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION1,
        client_id="fastapi_ecoclima_backend_g3",
    )
except AttributeError:
    mqtt_client = mqtt.Client(client_id="fastapi_ecoclima_backend_g3")

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message


@app.on_event("startup")
def startup_event():
    init_db()
    cargar_estado_persistente()  # 1. Primero recupera lo guardado en BD/JSON
    guardar_respaldo_json()      # 2. Sincroniza el respaldo sin borrarlo
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        iniciar_puente_profesor()
    except Exception as e:
        print(f"[MQTT] No se pudo conectar al iniciar: {e}")

        from fastapi import Request

TOPICO_UMBRALES = "utp/ds8/disp3/EcoClima/umbrales"
UMBRALES_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "umbrales.json")
umbrales_actuales = {
    "temp_max": 40.0,
    "temp_warn": 35.0,
    "hum_max": 90.0,
    "hum_warn": 80.0,
    "co2_max": 1000.0,
    "co2_warn": 800.0,
}

if os.path.exists(UMBRALES_JSON_PATH):
    try:
        with open(UMBRALES_JSON_PATH, "r", encoding="utf-8") as f:
            umbrales_actuales.update(json.load(f))
    except Exception:
        pass

@app.get("/api/umbrales")
@app.get("/api/thresholds")
def obtener_umbrales():
    return umbrales_actuales

@app.post("/api/umbrales")
@app.post("/api/thresholds")
async def actualizar_umbrales(request: Request):
    body = await request.json()
    for clave in umbrales_actuales:
        if clave in body and body[clave] is not None:
            umbrales_actuales[clave] = float(body[clave])

    with open(UMBRALES_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(umbrales_actuales, f, indent=4)

    mensaje = json.dumps({"action": "thresholds", **umbrales_actuales})
    mqtt_client.publish(TOPICO_UMBRALES, mensaje, retain=True)
    mqtt_client.publish(TOPICO_CMD, mensaje)
    print(f"[UMBRALES -> THONNY ESP32] Enviado: {umbrales_actuales}")
    return {"ok": True, "umbrales": umbrales_actuales}

    import os
import json
import sqlite3
from datetime import datetime
from fastapi import Request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ecoclima.db")
UMBRALES_JSON_PATH = os.path.join(BASE_DIR, "umbrales.json")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS salones (
            id TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            sensor_id TEXT,
            temperature REAL DEFAULT 0,
            humidity REAL DEFAULT 0,
            co2 INTEGER DEFAULT 420,
            alarma INTEGER DEFAULT 0,
            servo_activo INTEGER DEFAULT 0,
            led_activo INTEGER DEFAULT 0,
            ultima_actualizacion TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lecturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            salon_id TEXT,
            sensor_id TEXT,
            temperature REAL,
            humidity REAL,
            co2 INTEGER,
            timestamp TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS umbrales (
            clave TEXT PRIMARY KEY,
            valor REAL
        )
    """)
    conn.commit()
    conn.close()

# ==========================================
# PERSISTENCIA DE UMBRALES
# ==========================================
umbrales_actuales = {
    "temp_max": 40.0,
    "temp_warn": 35.0,
    "hum_max": 90.0,
    "hum_warn": 80.0,
    "co2_max": 1000.0,
    "co2_warn": 800.0,
}

def cargar_umbrales_db():
    conn = get_db()
    filas = conn.execute("SELECT clave, valor FROM umbrales").fetchall()
    conn.close()
    if filas:
        for r in filas:
            if r["clave"] in umbrales_actuales:
                umbrales_actuales[r["clave"]] = float(r["valor"])
    elif os.path.exists(UMBRALES_JSON_PATH):
        with open(UMBRALES_JSON_PATH, "r", encoding="utf-8") as f:
            umbrales_actuales.update(json.load(f))
        guardar_umbrales_db()

def guardar_umbrales_db():
    conn = get_db()
    for k, v in umbrales_actuales.items():
        conn.execute(
            "INSERT OR REPLACE INTO umbrales (clave, valor) VALUES (?, ?)",
            (k, float(v))
        )
    conn.commit()
    conn.close()
    with open(UMBRALES_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(umbrales_actuales, f, indent=4)

@app.get("/api/umbrales")
@app.get("/api/thresholds")
def obtener_umbrales():
    cargar_umbrales_db()
    return umbrales_actuales

@app.post("/api/umbrales")
@app.post("/api/thresholds")
async def actualizar_umbrales(request: Request):
    body = await request.json()
    for clave in umbrales_actuales:
        if clave in body and body[clave] is not None:
            umbrales_actuales[clave] = float(body[clave])

    guardar_umbrales_db()
    mensaje = json.dumps({"action": "thresholds", **umbrales_actuales})
    mqtt_client.publish("utp/ds8/disp3/EcoClima/umbrales", mensaje, retain=True)
    mqtt_client.publish(TOPICO_CMD, mensaje)
    return {"ok": True, "umbrales": umbrales_actuales}

# ==========================================
# PERSISTENCIA DE ACTUADORES Y ALARMA POR SALÓN
# ==========================================
@app.post("/api/actuadores")
@app.post("/api/cmd")
async def controlar_actuadores(request: Request):
    body = await request.json()
    salon_id = body.get("salon_id") or body.get("id")
    action = body.get("action")
    state = bool(body.get("state", False))

    conn = get_db()
    if salon_id:
        if action in ("emergency", "alarma"):
            conn.execute(
                "UPDATE salones SET alarma = ?, servo_activo = ?, led_activo = ? WHERE id = ?",
                (1 if state else 0, 1 if state else 0, 1 if state else 0, salon_id)
            )
        elif action == "servo":
            conn.execute(
                "UPDATE salones SET servo_activo = ? WHERE id = ?",
                (1 if state else 0, salon_id)
            )
        elif action == "led":
            conn.execute(
                "UPDATE salones SET led_activo = ? WHERE id = ?",
                (1 if state else 0, salon_id)
            )
    else:
        # Paro de emergencia global
        conn.execute(
            "UPDATE salones SET alarma = ?, servo_activo = ?, led_activo = ?",
            (1 if state else 0, 1 if state else 0, 1 if state else 0)
        )
    conn.commit()
    conn.close()

    mqtt_client.publish(TOPICO_CMD, json.dumps({
        "action": action or "emergency",
        "salon_id": salon_id,
        "state": state
    }))
    return {"ok": True, "action": action, "state": state}


@app.on_event("shutdown")
def shutdown_event():
    guardar_respaldo_json()
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

    import paho.mqtt.client as mqtt
from fastapi import Request

PROF_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profesor_mqtt.json")
prof_client = None
prof_conectado = False
prof_config = {
    "habilitado": True,
    "broker": "10.112.177.38",
    "port": 1883,
    "user": "g6",
    "password": "123g6",
    "topic": "utp/ds8/disp3/EcoClima/telemetria"
}

def cargar_config_profesor():
    global prof_config
    if os.path.exists(PROF_CONFIG_PATH):
        with open(PROF_CONFIG_PATH, "r", encoding="utf-8") as f:
            prof_config.update(json.load(f))
    else:
        with open(PROF_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(prof_config, f, indent=4)

def iniciar_puente_profesor():
    global prof_client, prof_conectado
    cargar_config_profesor()
    if prof_client:
        try:
            prof_client.loop_stop()
            prof_client.disconnect()
        except Exception:
            pass
    prof_conectado = False

    if not prof_config.get("habilitado", True):
        print("[PUENTE PROFESOR] Deshabilitado en profesor_mqtt.json")
        return

    prof_client = mqtt.Client(client_id="ecoclima_puente_g6")
    if prof_config.get("user"):
        prof_client.username_pw_set(prof_config["user"], prof_config.get("password", ""))

    def on_connect_prof(client, userdata, flags, rc):
        global prof_conectado
        if rc == 0:
            prof_conectado = True
            print(f"[PUENTE PROFESOR] Conectado a {prof_config['broker']}:{prof_config['port']} como '{prof_config['user']}'")
        else:
            prof_conectado = False
            print(f"[PUENTE PROFESOR] Error de conexión/autenticación (código rc={rc})")

    def on_disconnect_prof(client, userdata, rc):
        global prof_conectado
        prof_conectado = False
        print(f"[PUENTE PROFESOR] Desconectado (rc={rc})")

    prof_client.on_connect = on_connect_prof
    prof_client.on_disconnect = on_disconnect_prof

    try:
        prof_client.connect_async(prof_config["broker"], int(prof_config["port"]), 60)
        prof_client.loop_start()
    except Exception as e:
        print(f"[PUENTE PROFESOR] No se pudo alcanzar {prof_config['broker']}: {e}")

def reenviar_telemetria_profesor(payload_json_str: str):
    if prof_client and prof_conectado:
        topico_destino = prof_config.get("topic", "utp/ds8/disp3/EcoClima/telemetria")
        info = prof_client.publish(topico_destino, payload_json_str, qos=1)
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"[PUENTE PROFESOR -> {prof_config['broker']}] Enviado a '{topico_destino}': {payload_json_str}")
    else:
        print("[PUENTE PROFESOR] Pendiente de conexión con el broker del profesor...")

@app.post("/api/profesor/reconectar")
async def reconectar_puente_profesor(request: Request):
    try:
        body = await request.json()
        if body:
            cargar_config_profesor()
            prof_config.update(body)
            with open(PROF_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(prof_config, f, indent=4)
    except Exception:
        pass
    iniciar_puente_profesor()
    return {"ok": True, "config": {k: v for k, v in prof_config.items() if k != "password"}}


# =========================
# 5. ENDPOINTS REST 
# =========================
@app.get("/api/mqtt/status")
def estado_mqtt():
    return {
        "connected": mqtt_conectado,
        "status": "connected" if mqtt_conectado else "disconnected",
        "broker": MQTT_BROKER,
        "topic": TOPICO_TELEMETRIA,
    }


@app.get("/api/sensors")
@app.get("/api/sensores")
@app.get("/sensors")
@app.get("/sensores")
@app.get("/api/salones")
def obtener_salones():
    return salones_data


@app.get("/api/sensores-disponibles")
def listar_sensores_disponibles():
    lista = list(sensores_detectados.values())
    disponibles = [s for s in lista if s["salon_asignado"] is None]
    return {
        "total_detectados": len(lista),
        "total_disponibles": len(disponibles),
        "sensores": lista,
    }


@app.post("/api/asignar-sensor")
def asignar_sensor_a_salon(req: AsignacionRequest):
    sensor = sensores_detectados.get(req.sensor_id)
    if not sensor:
        return {"ok": False, "error": "El sensor seleccionado no está conectado."}

    nombre_limpio = req.numero_salon.strip()
    if not nombre_limpio:
        return {"ok": False, "error": "Debes escribir un nombre o número de salón."}

    nombre_salon = f"SALON {nombre_limpio}" if nombre_limpio.isdigit() else nombre_limpio.upper()

    # Si el sensor estaba asignado antes a otro nombre de salón, limpiar el anterior
    salon_anterior = asignaciones_sensores.get(req.sensor_id)
    if salon_anterior and salon_anterior != nombre_salon:
        salones_data.pop(salon_anterior, None)
        eliminar_salon_sqlite(salon_anterior)

    # Liberar si ese salón tenía otro sensor asignado previamente
    for s_id, room in list(asignaciones_sensores.items()):
        if room == nombre_salon and s_id != req.sensor_id:
            del asignaciones_sensores[s_id]
            if s_id in sensores_detectados:
                sensores_detectados[s_id]["salon_asignado"] = None

    asignaciones_sensores[req.sensor_id] = nombre_salon
    sensor["salon_asignado"] = nombre_salon

    salones_data[nombre_salon] = {
        "temperature": sensor["temperature"],
        "humidity": sensor["humidity"],
        "co2": sensor["co2"],
        "emergency": False,
        "sensor_id": req.sensor_id,
    }

    guardar_respaldo_json()
    persistir_lectura_sqlite(
        nombre_salon,
        sensor["temperature"],
        sensor["humidity"],
        sensor["co2"],
        req.sensor_id,
    )
    return {"ok": True, "salon": nombre_salon, "sensor_id": req.sensor_id}


@app.post("/api/desasignar-sensor/{sensor_id}")
def desasignar_sensor(sensor_id: str):
    salon = asignaciones_sensores.pop(sensor_id, None)
    if sensor_id in sensores_detectados:
        sensores_detectados[sensor_id]["salon_asignado"] = None
    if salon:
        salones_data.pop(salon, None)
        eliminar_salon_sqlite(salon)
    guardar_respaldo_json()
    return {"ok": True, "sensor_id": sensor_id}


@app.post("/api/sensors")
@app.post("/api/salones")
async def crear_salon_manual(request: Request):
    body = await request.json()
    nombre_raw = str(body.get("room") or body.get("nombre") or body.get("name") or "").strip()
    if not nombre_raw:
        return {"ok": False, "error": "Nombre de salón requerido"}

    nombre_salon = f"SALON {nombre_raw}" if nombre_raw.isdigit() else nombre_raw.upper()
    if nombre_salon not in salones_data:
        salones_data[nombre_salon] = {
            "temperature": 24.0,
            "humidity": 50.0,
            "co2": 400,
            "emergency": False,
        }
        guardar_respaldo_json()
        persistir_lectura_sqlite(nombre_salon, 24.0, 50.0, 400)
    return {"ok": True, "salon": nombre_salon}


@app.delete("/api/sensors/{room_name}")
@app.delete("/api/salones/{room_name}")
@app.delete("/sensors/{room_name}")
def eliminar_salon(room_name: str):
    if room_name in salones_data:
        del salones_data[room_name]

    eliminar_salon_sqlite(room_name)

    for s_id, assigned_room in list(asignaciones_sensores.items()):
        if assigned_room == room_name:
            del asignaciones_sensores[s_id]
            if s_id in sensores_detectados:
                sensores_detectados[s_id]["salon_asignado"] = None

    guardar_respaldo_json()
    return {"ok": True, "deleted": room_name}


@app.post("/api/emergency")
@app.post("/emergency")
@app.post("/api/emergencia")
async def controlar_emergencia(request: Request):
    body = await request.json()
    room = body.get("room") or body.get("salon") or "GLOBAL"
    state = bool(body.get("state", body.get("emergency", False)))

    if room == "GLOBAL":
        for r in salones_data:
            salones_data[r]["emergency"] = state
    elif room in salones_data:
        salones_data[room]["emergency"] = state

    guardar_respaldo_json()
    persistir_comando_sqlite(room, "emergency", state)

    comando_mqtt = json.dumps({"action": "emergency", "room": room, "state": state})
    mqtt_client.publish(TOPICO_CMD, comando_mqtt)
    return {"ok": True, "room": room, "state": state}


@app.post("/api/emergency/global")
@app.post("/emergency/global")
async def controlar_emergencia_global(request: Request):
    body = await request.json()
    state = bool(body.get("state", True))

    for r in salones_data:
        salones_data[r]["emergency"] = state

    guardar_respaldo_json()
    persistir_comando_sqlite("GLOBAL", "emergency", state)

    comando_mqtt = json.dumps({"action": "emergency", "room": "GLOBAL", "state": state})
    mqtt_client.publish(TOPICO_CMD, comando_mqtt)
    return {"ok": True, "room": "GLOBAL", "state": state}


@app.get("/api/historial/{room_name}")
def obtener_historial_salon(room_name: str, limite: int = 15):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT l.temperatura, l.humedad, l.co2_ppm,
               strftime('%H:%M:%S', l.fecha_registro) AS hora
        FROM lecturas_telemetria l
        JOIN salones s ON l.id_salon = s.id_salon
        WHERE s.nombre = ?
        ORDER BY l.id_lectura DESC
        LIMIT ?
        """,
        (room_name, limite),
    )
    filas = [dict(r) for r in cursor.fetchall()]
    conn.close()
    filas.reverse()
    return filas