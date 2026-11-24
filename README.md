# EcoClima — Sistema Integral de Monitoreo Ambiental IoT

**EcoClima** es una plataforma IoT de monitoreo ambiental y control de actuadores en tiempo real desarrollada con **ESP32 (MicroPython)**, **FastAPI**, **SQLite**, **MQTT** y una interfaz web interactiva. El sistema supervisa temperatura, humedad relativa y concentración estimada de $\text{CO}_2$, gestiona alertas visuales y sonoras mediante umbrales configurables de forma bidireccional y cuenta con un puente de reenvío MQTT hacia servidores externos autenticados.

---

## Arquitectura del Sistema

El proyecto opera bajo una arquitectura desacoplada en tres capas:

1. **Capa de Borde / Hardware (ESP32 + MicroPython):**
   - Lectura simultánea de múltiples sensores ambientales (DHT11 / DHT22) con escaneo automático de pines y reintentos ante fallos de lectura.
   - Control local inmediato de semáforo LED, buzzer de alarma y servomotor de ventilación.
   - Persistencia de umbrales en la memoria flash del microcontrolador (`umbrales.json`) y sincronización bidireccional vía MQTT (`broker.hivemq.com`).
   - Compatible tanto con hardware físico (cargado mediante **Thonny**) como con simulación virtual en **Wokwi**.

2. **Capa Backend y Puente MQTT (Python + FastAPI + SQLite):**
   - Suscripción continua al broker MQTT principal para ingestar telemetría en tiempo real.
   - Almacenamiento persistente de lecturas históricas, estado de salones, actuadores y umbrales en base de datos **SQLite** (`ecoclima.db`) con respaldo en archivos JSON.
   - **Puente MQTT Externo (`profesor_mqtt.json`):** Reenvío automático y asíncrono de los paquetes de telemetría hacia un broker MQTT externo con autenticación por usuario y contraseña, sin afectar el flujo principal de la aplicación.

3. **Capa Frontend Web (HTML5 + CSS3 + JavaScript + Chart.js):**
   - **Dashboard General:** Visualización en vivo por salón/sensor, estado de conexión con el broker y paro de emergencia global.
   - **Vista de Detalle:** Gráficas históricas en tiempo real de temperatura y humedad, junto con interruptores individuales para ventilación (servomotor) y alarma visual (LEDs).
   - **Configuración de Umbrales:** Ajuste dinámico de niveles de advertencia (amarillo) y críticos (rojo) sincronizados instantáneamente con el backend y el ESP32.

---

## Estructura del Proyecto

```text
HtEcoClima/
├── backend/
│   ├── main.py                # Servidor FastAPI, endpoints REST, cliente MQTT y puente externo
│   ├── database.py            # Gestión de conexión y operaciones sobre SQLite
│   ├── schema.sql             # Esquema relacional de tablas (salones, lecturas, umbrales)
│   ├── ecoclima.db            # Base de datos SQLite local
│   ├── profesor_mqtt.json     # Configuración dinámica del broker MQTT de destino externo
│   ├── umbrales.json          # Respaldo persistente de umbrales del sistema
│   └── data.json              # Respaldo de estado general
├── frontend-web/
│   ├── index.html             # Interfaz web principal (Dashboard, gráficas y controles)
│   └── CSS/                   # Hojas de estilo de la plataforma
└── README.md                  # Documentación general del proyecto
```

---

## Hardware y Pinout (ESP32 DevKit V1)

| Componente | Pin ESP32 | Modo / Protocolo | Función en el Sistema |
| :--- | :---: | :---: | :--- |
| **Sensor DHT11 / DHT22 (Zona 1)** | `GPIO 4` (`D4`) | Digital / 1-Wire | Medición de temperatura (°C) y humedad (%) |
| **Sensor DHT11 / DHT22 (Zona 2)** | `GPIO 16` (`RX2`) | Digital / 1-Wire | Medición secundaria de temperatura (°C) y humedad (%) |
| **LED Verde (Óptimo)** | `GPIO 18` (`D18`) | Salida Digital | Indica parámetros dentro de rangos normales |
| **LED Amarillo (Advertencia)** | `GPIO 19` (`D19`) | Salida Digital | Indica superación de umbral preventivo (`warn`) |
| **LED Rojo (Crítico / Alarma)** | `GPIO 21` (`D21`) | Salida Digital | Indica umbral crítico (`max`) o emergencia manual activa |
| **Servomotor SG90** | `GPIO 17` (`TX2`) | PWM (50 Hz) | Simula apertura de ventilación HVAC (`duty(0)` en reposo) |
| **Buzzer Activo / Pasivo** | `GPIO 23` (`D23`) | Salida Digital | Alerta sonora en estado crítico o emergencia manual |
| **Botón de Emergencia** | `GPIO 5` (`D5`) | Entrada (`PULL_DOWN`) | Activa o desactiva manualmente la alarma local |
| **Potenciómetro $\text{CO}_2$ (Opcional)** | `GPIO 34` (`D34`) | Entrada Analógica (ADC) | Simula concentración de $\text{CO}_2$ (400 – 2000 ppm) |

---

## Protocolo y Tópicos MQTT

- **Broker Principal:** `broker.hivemq.com` (Puerto `1883`)
- **Tópico de Telemetría (ESP32 $\rightarrow$ Backend / Externo):** `utp/ds8/g6/EcoClima`
- **Tópico de Comandos (Web / Backend $\rightarrow$ ESP32):** `utp/ds8/g6/EcoClima/cmd`
- **Tópico de Umbrales (Web / Backend $\rightarrow$ ESP32):** `utp/ds8/g6/EcoClima/umbrales`

### Formato del Payload de Telemetría (JSON)

```json
{
  "sensor_id": "DHT11-GPIO4",
  "pin": 4,
  "temperature": 30.0,
  "humidity": 68.0,
  "co2": 420
}
```

---

## Instalación y Ejecución

### 1. Requisitos Previos
- **Python 3.10+** instalado en el equipo.
- **Thonny IDE** (con firmware MicroPython en el ESP32) o acceso a **Wokwi**.
- Dependencias de Python para el backend:
  ```bash
  pip install fastapi uvicorn paho-mqtt
  ```

### 2. Iniciar el Backend (FastAPI)
Desde la carpeta `backend/`, ejecuta el servidor en el puerto `8000`:
```bash
cd backend
uvicorn main:app --reload --port 8000
```
El servidor inicializará automáticamente `ecoclima.db`, cargará los umbrales guardados y se conectará tanto al broker principal como al puente externo configurado.

### 3. Ejecutar el Firmware del Microcontrolador
- **En físico (Thonny):** Abre el script del ESP32, configura `WIFI_SSID` y `WIFI_PASS` con las credenciales de tu red local y ejecuta (`F5`).
- **En simulación (Wokwi):** Mantén `WIFI_SSID = "Wokwi-GUEST"` y presiona **Start Simulation**.

### 4. Abrir la Interfaz Web
Abre `frontend-web/index.html` en tu navegador (mediante **Live Server** en VS Code o directamente desde `http://localhost:8000` si está servido por FastAPI).

---

## Configuración del Puente MQTT Externo

Para reenviar automáticamente la telemetría hacia otro servidor MQTT sin modificar el código fuente, edita el archivo `backend/profesor_mqtt.json`:

```json
{
  "habilitado": true,
  "broker": "10.123.197.38",
  "port": 1883,
  "user": "g6",
  "password": "TU_PASSWORD",
  "topic": "utp/ds8/g6/EcoClima"
}
```
> **Nota de red:** Si el servidor de destino utiliza una dirección IP privada (`10.x.x.x` o `192.168.x.x`), el equipo que ejecuta el backend debe estar conectado a la misma red local o subred que el broker receptor. Tras modificar `profesor_mqtt.json`, reinicia `uvicorn` para aplicar los cambios.

---

## Endpoints Principales de la API REST

| Método | Ruta | Descripción |
| :--- | :--- | :--- |
| `GET` | `/api/mqtt/status` | Devuelve el estado de conexión con el broker MQTT principal |
| `GET` | `/api/umbrales` | Obtiene los umbrales actuales almacenados en SQLite / JSON |
| `POST` | `/api/umbrales` | Actualiza los umbrales, los guarda en BD y los publica al ESP32 |
| `POST` | `/api/actuadores` | Controla el estado de emergencia, servomotor o LEDs por salón |
| `POST` | `/api/profesor/reconectar` | Recarga `profesor_mqtt.json` y reinicia el puente MQTT externo |