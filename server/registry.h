// ======================================================
// registry.h - Estado del servidor central
//
// Punto 3.2 del proyecto. Aqui vive todo lo que el
// servidor central debe recordar y decidir:
//
//   - identificar los dispositivos conectados
//   - recibir y procesar mediciones
//   - detectar valores anomalos
//   - generar alertas
//   - responder consultas de los operadores
//   - sobrevivir a desconexiones y errores
//
// Todas las estructuras se protegen con mutex porque el
// servidor es concurrente (punto 6): el hilo UDP, el hilo
// monitor y un hilo por operador las tocan a la vez.
// ======================================================

#ifndef REGISTRY_H
#define REGISTRY_H

#include <time.h>
#include <stddef.h>

// ------------------------------------------------------
// Limites del servidor
// ------------------------------------------------------

#define MAX_NODES             64
#define MAX_VARS_PER_NODE      8
#define MAX_OPERATORS         32
#define MAX_ALERTS           128   // historial circular de alertas
#define MAX_MEASUREMENTS     256   // historial circular de mediciones
#define MAX_THRESHOLDS        64
#define MAX_ALERTS_PER_MSG     8   // alertas que puede generar un solo datagrama

#define NODE_ID_LEN           32
#define NODE_TYPE_LEN         32
#define NODE_LOCATION_LEN     64
#define VAR_NAME_LEN          16
#define UNIT_LEN               8
#define ALERT_TYPE_LEN        32
#define SEVERITY_LEN          12

// Un nodo pasa a OFFLINE si no reporta en este tiempo
#define NODE_TIMEOUT_SEG      15
#define MONITOR_PERIOD_SEG     5

// Periodo de muestreo que el servidor sugiere en OK|REGISTER
#define SUGGESTED_INTERVAL     3

// ------------------------------------------------------
// Estructuras
// ------------------------------------------------------

typedef struct {
    char   name[VAR_NAME_LEN];
    char   unit[UNIT_LEN];
    double valor;
    time_t ts;
    int    tiene_valor;
} registry_var_t;

typedef struct {
    int    en_uso;
    int    online;

    char   id[NODE_ID_LEN];
    char   tipo[NODE_TYPE_LEN];
    char   ubicacion[NODE_LOCATION_LEN];
    char   direccion[64];          // ip:puerto del ultimo datagrama

    time_t registrado_en;
    time_t ultima_medicion;

    unsigned long msgs_recibidos;
    unsigned long perdidos_est;
    long          ultimo_seq;      // -1 mientras no llegue el primero

    int            nvars;
    registry_var_t vars[MAX_VARS_PER_NODE];
} node_t;

typedef struct {
    char   node_id[NODE_ID_LEN];
    char   tipo[ALERT_TYPE_LEN];   // TEMP_HIGH, VIB_HIGH, NODE_OFFLINE...
    char   var[VAR_NAME_LEN];
    double valor;
    time_t ts;
    char   severidad[SEVERITY_LEN];
} alert_t;

// ------------------------------------------------------
// Ciclo de vida
// ------------------------------------------------------

void registry_init(int udp_port, int tcp_port);

// Lanza el hilo que vigila los nodos caidos. Devuelve 0 si todo fue bien.
int  registry_start_monitor(void);

long registry_uptime(void);
int  registry_udp_port(void);

// ------------------------------------------------------
// Nodos de telemetria
// ------------------------------------------------------

int registry_register_node(const char *id,
                           const char *tipo,
                           const char *ubicacion,
                           char nombres[][VAR_NAME_LEN],
                           char unidades[][UNIT_LEN],
                           int  nvars);

// Procesa un TELEMETRY. Deja en *alertas el numero de alertas
// que produjo este datagrama. Devuelve TSP_OK o un codigo de error.
int registry_record_telemetry(const char *id,
                              long seq,
                              const char *direccion,
                              char nombres[][VAR_NAME_LEN],
                              const double *valores,
                              int  nvars,
                              int *alertas);

// ------------------------------------------------------
// Consultas de los operadores (punto 3.3)
//
// Cada funcion construye la respuesta TSP completa,
// incluida la cabecera y el centinela END.
// ------------------------------------------------------

int registry_build_list_nodes(char *out, size_t cap);
int registry_build_node_status(const char *id, char *out, size_t cap);
int registry_build_last(int n, char *out, size_t cap);
int registry_build_alerts(int n, char *out, size_t cap);
int registry_build_system(char *out, size_t cap);

int registry_set_threshold(const char *node_id,
                           const char *var,
                           double minimo,
                           double maximo);

// ------------------------------------------------------
// Operadores conectados
// ------------------------------------------------------

// Devuelve el slot asignado, o -1 si se alcanzo el maximo (error 503)
int  registry_operator_add(int fd, const char *direccion);
void registry_operator_remove(int slot);
void registry_operator_set_name(int slot, const char *nombre);
void registry_operator_subscribe(int slot, int activar);

// Un slot solo cuenta como operador cuando la conexion se identifica
// como tal; las conexiones TCP de los nodos (REGISTER) no se cuentan.
void registry_operator_set_role(int slot, int es_operador);

// Envio protegido por mutex: el hilo monitor tambien escribe
// en estos sockets para empujar alertas.
int  registry_operator_send(int slot, const char *msg, size_t len);

// ------------------------------------------------------
// Estadisticas globales
// ------------------------------------------------------

void registry_stat_comando(void);
void registry_stat_rechazo(void);

#endif // REGISTRY_H
