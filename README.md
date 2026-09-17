# Plataforma Distribuida de Telemetría

Proyecto de Telemática 2026-2.

## Integrantes

- Alejandro Jaramillo Rodriguez
- Samuel Herrera
- Simon Castro
- JE

## Arquitectura

El proyecto implementa una plataforma distribuida de telemetría utilizando comunicación TCP y UDP.

### Puertos actuales

- TCP: 6000
- UDP: 5000

## Servidor

El servidor está desarrollado en C.

Actualmente soporta:

- comunicación TCP;
- comunicación UDP;
- múltiples clientes TCP mediante pthreads;
- TCP y UDP ejecutándose simultáneamente;
- manejo básico de desconexiones y errores.

## Compilación

Servidor concurrente:

```bash
gcc server/server_concurrent.c -o server/server_concurrent -pthread
```

Cliente TCP de prueba:

```bash
gcc server/client_tcp_test.c -o server/client_tcp_test
```

Cliente UDP de prueba:

```bash
gcc server/client_udp_test.c -o server/client_udp_test
```
