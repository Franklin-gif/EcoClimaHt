from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os
from datetime import datetime
import paho.mqtt.client as mqtt # Librería para el Broker

app = FastAPI(title="EcoClima API Enterprise")

# Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_FILE = "data.json"

# ==========================================
# CONFIGURACIÓN DEL BROKER MQTT (PROFESOR)
# ==========================================
MQTT_BROKER = "broker.hivemq.com"  # Reemplazar con la IP/Dominio 
MQTT_PORT = 1883
MQTT_USER = ""                     # Credencial 
MQTT_PASS = ""                     # Credencial
MQTT_TOPIC_TELEMETRIA = "utp/ds8/disp3/EcoClima/telemetria"
MQTT_TOPIC_CMD = "utp/ds8/disp3/EcoClima/cmd"

mqtt_connected = False
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Backend_EcoClima_G3")

def on_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    if rc == 0:
        print("✅ Conectado exitosamente al Broker MQTT")
        mqtt_connected = True
        client.subscribe(MQTT_TOPIC_TELEMETRIA) # Escuchar lo que manda el ESP32
    else:
        print(f"❌ Error al conectar al broker. Código: {rc}")

def on_message(client, userdata, msg):
    # Cuando el broker nos envía datos del ESP32, los guardamos en data.json para la web
    try:
        payload = json.loads(msg.payload.decode())
        data = read_data()
        room = payload.get("room")
        if room:
            emergency_status = data.get(room, {}).get("emergency", False)
            data[room] = {
                "temperature": payload.get("temperature"),
                "humidity": payload.get("humidity"),
                "co2": payload.get("co2"),
                "last_updated": datetime.now().strftime("%H:%M:%S"),
                "emergency": emergency_status
            }
            with open(DATA_FILE, "w") as f:
                json.dump(data, f, indent=4)
    except Exception as e:
        print("Error leyendo mensaje MQTT:", e)

def on_disconnect(client, userdata, rc):
    global mqtt_connected
    print("⚠️ Desconectado del Broker MQTT")
    mqtt_connected = False

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message # Agregamos la función que escucha
mqtt_client.on_disconnect = on_disconnect

# Inicializar conexión MQTT al arrancar FastAPI
@app.on_event("startup")
def startup_mqtt():
    if MQTT_USER and MQTT_PASS:
        mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    try:
        print(f"Conectando al broker MQTT {MQTT_BROKER}...")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()  # Hilo en segundo plano para mantener la conexión viva
    except Exception as e:
        print(f"❌ No se pudo inicializar MQTT: {e}")


# ==========================================
# MODELOS Y LÓGICA DE DATOS REST
# ==========================================
class SensorData(BaseModel):
    room: str
    temperature: float
    humidity: float
    co2: int

class EmergencyData(BaseModel):
    room: str
    active: bool

def read_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

@app.post("/api/sensors")
async def receive_sensor_data(payload: SensorData):
    data = read_data()
    emergency_status = data.get(payload.room, {}).get("emergency", False)
    
    data[payload.room] = {
        "temperature": payload.temperature,
        "humidity": payload.humidity,
        "co2": payload.co2,
        "last_updated": datetime.now().strftime("%H:%M:%S"),
        "emergency": emergency_status
    }
    
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)
        
    # INTEGRACIÓN PROFESOR: Publicar métricas al broker
    if mqtt_connected:
        mqtt_payload = json.dumps(payload.dict())
        mqtt_client.publish(MQTT_TOPIC_TELEMETRIA, mqtt_payload)
        
    return {"status": "success", "message": f"Datos guardados para {payload.room}"}

@app.post("/api/emergency")
async def trigger_emergency(payload: EmergencyData):
    data = read_data()
    if payload.room in data:
        data[payload.room]["emergency"] = payload.active
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
            
        # INTEGRACIÓN PROFESOR: Enviar comando de activación/desactivación a la placa
        if mqtt_connected:
            cmd_payload = json.dumps({"room": payload.room, "action": "emergency", "state": payload.active})
            mqtt_client.publish(MQTT_TOPIC_CMD, cmd_payload)
            
        return {"status": "success", "emergency": payload.active}
    
    raise HTTPException(status_code=404, detail="Salón no encontrado")

@app.get("/api/sensors")
async def get_sensor_data():
    return read_data()

# NUEVO: Endpoint para que el HTML sepa si el Broker está en línea
@app.get("/api/mqtt/status")
async def get_mqtt_status():
    return {"connected": mqtt_connected}

@app.delete("/api/sensors/{room_name}")
async def delete_sensor_room(room_name: str):
    data = read_data()
    if room_name in data:
        del data[room_name]
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
        return {"status": "success", "message": f"Salón {room_name} eliminado"}
    raise HTTPException(status_code=404, detail="Salón no encontrado")