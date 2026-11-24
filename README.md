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

## Cómo Ejecutar el Proyecto (Paso a Paso)

Sigue este orden para levantar el sistema completo sin conflictos de puertos ni de red:

### Paso 1: Instalar Requisitos Previos
Asegúrate de tener instalado **Python 3.10 o superior**, **Visual Studio Code** (con la extensión *Live Server*) y **Thonny IDE** (si usarás el ESP32 físico). Luego, instala las librerías del backend desde una terminal:

```bash
pip install fastapi uvicorn paho-mqtt
```

### Paso 2: Configurar el Destino MQTT Externo (Opcional)
Si deseas reenviar la telemetría a un broker externo (por ejemplo, el servidor de evaluación), abre `backend/profesor_mqtt.json` y verifica los datos de conexión antes de arrancar el servidor:

```json
{
  "habilitado": true,
  "broker": "10.123.197.38",
  "port": 1883,
  "user": "g6",
  "password": "123g6",
  "topic": "utp/ds8/g6/EcoClima"
}
```
> **Nota:** Si el broker externo usa una IP privada (`10.x.x.x` o `192.168.x.x`), tu computadora debe estar conectada a la misma red Wi-Fi o subred que ese servidor.

### Paso 3: Arrancar el Backend (FastAPI + Puente MQTT)
1. Abre la carpeta `HtEcoClima` en **VS Code**.
2. Abre una terminal integrada (`Ctrl + ñ`), entra a la carpeta `backend` y ejecuta Uvicorn en el puerto **`8000`**:
   ```bash
   cd backend
   uvicorn main:app --reload --port 8000
   ```
   *(Importante: No uses el puerto `1883` para Uvicorn; ese puerto es exclusivo del protocolo MQTT).*
3. **Verificación en consola:** Debes ver mensajes similares a:
   ```text
   INFO:     Uvicorn running on [http://127.0.0.1:8000](http://127.0.0.1:8000) (Press CTRL+C to quit)
   [MQTT] Conectado al broker (código 0)
   [MQTT] Suscrito a: utp/ds8/g6/EcoClima
   ```
   *(Cada vez que edites `profesor_mqtt.json`, detén el servidor con `Ctrl + C` y vuelve a ejecutar `uvicorn main:app --reload --port 8000`).*

### Paso 4: Iniciar el Microcontrolador (Físico o Simulado)
Elige una de las dos modalidades según tu entorno de prueba:

* **Opción A — Prototipo Físico (ESP32 + Thonny):**
  1. Conecta el ESP32 por USB a la computadora y abre **Thonny**.
  2. En la esquina inferior derecha de Thonny, selecciona el intérprete **MicroPython (ESP32)**.
  3. Abre el archivo `main.py` del microcontrolador, actualiza `WIFI_SSID` y `WIFI_PASS` con el nombre y contraseña de tu red Wi-Fi, y asegúrate de tener:
     ```python
     MQTT_BROKER = "broker.hivemq.com"
     TOPICO_TELEMETRIA = "utp/ds8/g6/EcoClima"
     TOPICO_CMD = "utp/ds8/g6/EcoClima/cmd"
     ```
  4. Presiona **`F5`** (o el botón verde **Run**) para iniciar la lectura de sensores.

* **Opción B — Simulación Virtual (Wokwi):**
  1. Abre el proyecto en **Wokwi** con `WIFI_SSID = "Wokwi-GUEST"` y `WIFI_PASS = ""`.
  2. Verifica que `TOPICO_TELEMETRIA = "utp/ds8/g6/EcoClima"` y `TOPICO_CMD = "utp/ds8/g6/EcoClima/cmd"`.
  3. Haz clic en el botón verde **Start Simulation**.

* **Verificación:** Tanto en Thonny como en Wokwi comenzará a imprimirse cada 5 segundos:
  ```text
  Reportando [DHT11-GPIO4]: {'temperature': 30.0, 'co2': 420, 'pin': 4, 'sensor_id': 'DHT11-GPIO4', 'humidity': 68.0}
  ```

### Paso 5: Abrir la Interfaz Web (Dashboard)
1. En **VS Code**, haz clic derecho sobre `frontend-web/index.html` y selecciona **Open with Live Server** (se abrirá en `http://127.0.0.1:5500/frontend-web/index.html`).
2. **Verificación visual:**
   - En la esquina inferior izquierda debe aparecer el indicador verde **`Broker MQTT: Conectado`**.
   - Las tarjetas de los salones mostrarán las lecturas actualizadas en vivo y la terminal de `uvicorn` confirmará el envío hacia el broker externo (`[PUENTE PROFESOR -> ...] Enviado a 'utp/ds8/g6/EcoClima'`).

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

## Endpoints Principales de la API REST

| Método | Ruta | Descripción |
| :--- | :--- | :--- |
| `GET` | `/api/mqtt/status` | Devuelve el estado de conexión con el broker MQTT principal |
| `GET` | `/api/umbrales` | Obtiene los umbrales actuales almacenados en SQLite / JSON |
| `POST` | `/api/umbrales` | Actualiza los umbrales, los guarda en BD y los publica al ESP32 |
| `POST` | `/api/actuadores` | Controla el estado de emergencia, servomotor o LEDs por salón |
| `POST` | `/api/profesor/reconectar` | Recarga `profesor_mqtt.json` y reinicia el puente MQTT externo |