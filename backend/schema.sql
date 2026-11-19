PRAGMA foreign_keys = ON;

-- 1. Catálogo de salones
CREATE TABLE IF NOT EXISTS salones (
    id_salon INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE CHECK (length(trim(nombre)) > 0),
    ubicacion TEXT NOT NULL DEFAULT 'Campus Central',
    emergencia_activa INTEGER NOT NULL DEFAULT 0 CHECK (emergencia_activa IN (0, 1)),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    fecha_creacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 2. Umbrales (Set-Points) por salón
CREATE TABLE IF NOT EXISTS umbrales_salon (
    id_umbral INTEGER PRIMARY KEY AUTOINCREMENT,
    id_salon INTEGER NOT NULL UNIQUE,
    temp_advertencia REAL NOT NULL DEFAULT 26.0,
    temp_critica REAL NOT NULL DEFAULT 30.0,
    hum_advertencia REAL NOT NULL DEFAULT 60.0,
    hum_critica REAL NOT NULL DEFAULT 70.0,
    co2_advertencia INTEGER NOT NULL DEFAULT 800,
    co2_critico INTEGER NOT NULL DEFAULT 1000,
    ultima_actualizacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (temp_advertencia > -20.0 AND temp_advertencia < temp_critica AND temp_critica <= 100.0),
    CHECK (hum_advertencia >= 0.0 AND hum_advertencia < hum_critica AND hum_critica <= 100.0),
    CHECK (co2_advertencia >= 350 AND co2_advertencia < co2_critico AND co2_critico <= 10000),
    FOREIGN KEY (id_salon) REFERENCES salones(id_salon) ON DELETE CASCADE
);

-- 3. Histórico de telemetría
CREATE TABLE IF NOT EXISTS lecturas_telemetria (
    id_lectura INTEGER PRIMARY KEY AUTOINCREMENT,
    id_salon INTEGER NOT NULL,
    temperatura REAL NOT NULL CHECK (temperatura BETWEEN -40.0 AND 125.0),
    humedad REAL NOT NULL CHECK (humedad BETWEEN 0.0 AND 100.0),
    co2_ppm INTEGER NOT NULL CHECK (co2_ppm BETWEEN 0 AND 10000),
    estado_calculado TEXT NOT NULL CHECK (estado_calculado IN ('OPTIMO', 'ADVERTENCIA', 'CRITICA')),
    fecha_registro TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (id_salon) REFERENCES salones(id_salon) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_telemetria_salon_fecha 
ON lecturas_telemetria(id_salon, fecha_registro DESC);

-- 4. Centro de alertas
CREATE TABLE IF NOT EXISTS alertas (
    id_alerta INTEGER PRIMARY KEY AUTOINCREMENT,
    id_salon INTEGER NOT NULL,
    id_lectura INTEGER,
    nivel TEXT NOT NULL CHECK (nivel IN ('ADVERTENCIA', 'CRITICA')),
    mensaje TEXT NOT NULL CHECK (length(trim(mensaje)) > 0),
    atendida INTEGER NOT NULL DEFAULT 0 CHECK (atendida IN (0, 1)),
    fecha_alerta TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (id_salon) REFERENCES salones(id_salon) ON DELETE CASCADE,
    FOREIGN KEY (id_lectura) REFERENCES lecturas_telemetria(id_lectura) ON DELETE SET NULL
);

-- 5. Auditoría de comandos MQTT
CREATE TABLE IF NOT EXISTS historial_comandos (
    id_comando INTEGER PRIMARY KEY AUTOINCREMENT,
    id_salon INTEGER NOT NULL,
    accion TEXT NOT NULL CHECK (accion IN ('emergency', 'normalizar', 'paro_global')),
    estado_solicitado INTEGER NOT NULL CHECK (estado_solicitado IN (0, 1)),
    origen TEXT NOT NULL DEFAULT 'DASHBOARD_WEB' 
        CHECK (origen IN ('DASHBOARD_WEB', 'BOTON_FISICO', 'AUTOMATICO_ESP32')),
    fecha_comando TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (id_salon) REFERENCES salones(id_salon) ON DELETE CASCADE
);

-- TRIGGER 1: Crear umbrales por defecto al registrar un salón
CREATE TRIGGER IF NOT EXISTS trg_crear_umbrales_defecto
AFTER INSERT ON salones
BEGIN
    INSERT INTO umbrales_salon (id_salon) VALUES (NEW.id_salon);
END;

-- TRIGGER 2: Crear alerta automática si la lectura es ADVERTENCIA o CRITICA
CREATE TRIGGER IF NOT EXISTS trg_generar_alerta_telemetria
AFTER INSERT ON lecturas_telemetria
WHEN NEW.estado_calculado IN ('ADVERTENCIA', 'CRITICA')
BEGIN
    INSERT INTO alertas (id_salon, id_lectura, nivel, mensaje)
    VALUES (
        NEW.id_salon,
        NEW.id_lectura,
        NEW.estado_calculado,
        'Umbral excedido -> Temp: ' || NEW.temperatura || '°C | Hum: ' || NEW.humedad || '% | CO2: ' || NEW.co2_ppm || ' ppm'
    );
END;

-- TRIGGER 3: Actualizar estado de emergencia en el salón al registrar comando
CREATE TRIGGER IF NOT EXISTS trg_sincronizar_emergencia
AFTER INSERT ON historial_comandos
BEGIN
    UPDATE salones
    SET emergencia_activa = NEW.estado_solicitado
    WHERE id_salon = NEW.id_salon;
END;

-- VISTA: Última lectura activa de cada salón para el Dashboard
CREATE VIEW IF NOT EXISTS vw_estado_actual_salones AS
SELECT 
    s.id_salon,
    s.nombre,
    s.ubicacion,
    s.emergencia_activa,
    t.temperatura,
    t.humedad,
    t.co2_ppm,
    t.estado_calculado,
    t.fecha_registro AS ultima_lectura
FROM salones s
LEFT JOIN lecturas_telemetria t ON t.id_lectura = (
    SELECT id_lectura 
    FROM lecturas_telemetria 
    WHERE id_salon = s.id_salon 
    ORDER BY fecha_registro DESC, id_lectura DESC 
    LIMIT 1
)
WHERE s.activo = 1;
