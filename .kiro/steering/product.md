# Producto

Plataforma Distribuida de Telemetría y Gestión de Infraestructura Inteligente
(Proyecto de Telemática 2026-2).

Sistema de monitoreo distribuido en el que nodos IoT simulados envían
mediciones periódicas a un servidor central. El servidor identifica los
dispositivos conectados, detecta valores anómalos, genera y difunde alertas, y
responde consultas de los operadores.

## Actores

- **Nodos de telemetría** (Python): se registran una vez y reportan mediciones
  periódicas de variables como `TEMP`, `HUM`, `PWR`, `VIB` y `STATUS`.
- **Servidor central** (C): concurrente, mantiene el estado del sistema
  (nodos, mediciones, umbrales, alertas y estadísticas) y detecta anomalías.
- **Operadores** (Python, CLI y GUI): consultan el estado, ajustan umbrales y
  reciben alertas en tiempo real.
- **Servicio Web** (Python/Servidor C): Interfaz HTTP básica que permite consultar desde un navegador web el estado general del servidor, cantidad de nodos, últimas mediciones y alertas recientes, cumpliendo con el punto 7 del enunciado del proyecto.

## Protocolo propio: TSP/1.0

Los tres actores hablan **TSP/1.0** (Telemetry Simple Protocol), un protocolo
de aplicación propio, basado en texto y orientado a línea. No se apoya en HTTP,
MQTT ni otro protocolo existente; se transporta directamente sobre sockets TCP
(registro, comandos, alertas) y UDP (telemetría). La especificación completa y
autoritativa vive en `docs/PROTOCOLO.md` y debe respetarse al modificar
cualquier parte del sistema.

## Idioma

El código, comentarios y documentación están en español. Mantén ese idioma al
generar código, comentarios, mensajes de commit y documentación nueva.
