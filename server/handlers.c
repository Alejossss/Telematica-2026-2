// ======================================================
// handlers.c - Despacho de comandos TSP/1.0
//
// Regla de oro de este modulo: un mensaje invalido SIEMPRE
// produce un ERR y NUNCA tumba la conexion ni el servidor
// (punto 3.2: "manejar desconexiones y errores sin
// finalizar abruptamente").
// ======================================================

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <time.h>

#include "handlers.h"
#include "protocol.h"
#include "registry.h"

// ======================================================
// SESIONES TCP
// ======================================================

int handlers_session_init(tsp_session_t *s, int fd, const char *direccion) {
    s->fd     = fd;
    s->rol    = TSP_ROLE_UNKNOWN;
    s->cerrar = 0;
    s->slot   = -1;

    snprintf(s->direccion, sizeof(s->direccion), "%s", direccion);

    s->respuesta = malloc(TSP_RESPONSE_MAX);

    if (s->respuesta == NULL) {
        return TSP_ERR_INTERNAL;
    }

    s->respuesta[0] = '\0';

    s->slot = registry_operator_add(fd, direccion);

    if (s->slot < 0) {
        free(s->respuesta);
        s->respuesta = NULL;

        return TSP_ERR_SERVER_FULL;
    }

    return TSP_OK;
}

void handlers_session_end(tsp_session_t *s) {
    if (s->slot >= 0) {
        registry_operator_remove(s->slot);
        s->slot = -1;
    }

    if (s->respuesta != NULL) {
        free(s->respuesta);
        s->respuesta = NULL;
    }
}

size_t handlers_build_error(tsp_session_t *s, int codigo, const char *desc) {
    if (s->respuesta == NULL) {
        return 0;
    }

    return (size_t)tsp_format_error(s->respuesta, TSP_RESPONSE_MAX, codigo, desc);
}

// ======================================================
// AYUDANTES
// ======================================================

static size_t responder(tsp_session_t *s, const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);

    int escritos = vsnprintf(s->respuesta, TSP_RESPONSE_MAX, fmt, args);

    va_end(args);

    if (escritos < 0 || (size_t)escritos >= TSP_RESPONSE_MAX) {
        return handlers_build_error(s, TSP_ERR_INTERNAL, "Respuesta demasiado grande");
    }

    return (size_t)escritos;
}

// Copia acotada de un campo del mensaje a un buffer mas pequeno.
// El exceso se descarta: un identificador truncado simplemente no
// coincidira con ningun nodo y la consulta respondera 404.
static void copiar_campo(char *destino, size_t cap, const char *origen) {
    if (cap == 0) {
        return;
    }

    size_t i = 0;

    while (origen[i] != '\0' && i + 1 < cap) {
        destino[i] = origen[i];
        i++;
    }

    destino[i] = '\0';
}

// Extrae los pares <VAR>|<VALOR> de un TELEMETRY o
// <VAR>|<UNIDAD> de un REGISTER, a partir del campo "inicio".
static int extraer_pares(const tsp_message_t *msg,
                         int inicio,
                         char nombres[][VAR_NAME_LEN],
                         char textos[][TSP_FIELD_LEN],
                         int max_pares) {

    int disponibles = msg->count - inicio;

    if (disponibles < 2 || (disponibles % 2) != 0) {
        return -1;
    }

    int pares = disponibles / 2;

    if (pares > max_pares) {
        pares = max_pares;
    }

    for (int i = 0; i < pares; i++) {
        copiar_campo(nombres[i], VAR_NAME_LEN,  msg->field[inicio + i * 2]);
        copiar_campo(textos[i],  TSP_FIELD_LEN, msg->field[inicio + i * 2 + 1]);

        tsp_to_upper(nombres[i]);
    }

    return pares;
}

// ======================================================
// COMANDOS SOBRE TCP
// ======================================================

static size_t cmd_hello(tsp_session_t *s, const tsp_message_t *msg) {
    if (msg->count < 2 || msg->field[1][0] == '\0') {
        return handlers_build_error(
            s, TSP_ERR_MISSING_PARAM, "HELLO requiere el nombre del operador");
    }

    s->rol = TSP_ROLE_OPERATOR;

    registry_operator_set_role(s->slot, 1);
    registry_operator_set_name(s->slot, msg->field[1]);

    printf("[OPERADOR] %s identificado desde %s\n", msg->field[1], s->direccion);

    return responder(
        s,
        "OK|HELLO|%s|%s|%ld\n",
        TSP_SERVER_ID,
        TSP_VERSION,
        registry_uptime()
    );
}

static size_t cmd_register(tsp_session_t *s, const tsp_message_t *msg) {
    // REGISTER|<ID>|<TIPO>|<UBICACION>|<VAR>|<UNIDAD>...
    if (msg->count < 6) {
        return handlers_build_error(
            s, TSP_ERR_MISSING_PARAM,
            "REGISTER requiere id, tipo, ubicacion y al menos una variable");
    }

    if (!tsp_valid_identifier(msg->field[1])) {
        return handlers_build_error(
            s, TSP_ERR_INVALID_PARAM, "Identificador de nodo invalido");
    }

    char nombres[MAX_VARS_PER_NODE][VAR_NAME_LEN];
    char textos[MAX_VARS_PER_NODE][TSP_FIELD_LEN];

    int pares = extraer_pares(msg, 4, nombres, textos, MAX_VARS_PER_NODE);

    if (pares < 1) {
        return handlers_build_error(
            s, TSP_ERR_BAD_REQUEST,
            "Las variables deben venir en pares nombre/unidad");
    }

    char unidades[MAX_VARS_PER_NODE][UNIT_LEN];

    for (int i = 0; i < pares; i++) {
        copiar_campo(unidades[i], UNIT_LEN, textos[i]);
    }

    int resultado = registry_register_node(
        msg->field[1],
        msg->field[2],
        msg->field[3],
        nombres,
        unidades,
        pares
    );

    if (resultado != TSP_OK) {
        return handlers_build_error(
            s, resultado, "No fue posible registrar el nodo");
    }

    s->rol = TSP_ROLE_NODE;

    registry_operator_set_role(s->slot, 0);

    return responder(
        s,
        "OK|REGISTER|%s|%d|%d\n",
        msg->field[1],
        registry_udp_port(),
        SUGGESTED_INTERVAL
    );
}

static size_t cmd_get_status(tsp_session_t *s, const tsp_message_t *msg) {
    if (msg->count < 2 || msg->field[1][0] == '\0') {
        return handlers_build_error(
            s, TSP_ERR_MISSING_PARAM,
            "GET_STATUS requiere el identificador del nodo");
    }

    int resultado = registry_build_node_status(
        msg->field[1], s->respuesta, TSP_RESPONSE_MAX);

    if (resultado == TSP_ERR_NODE_NOT_FOUND) {
        return handlers_build_error(
            s, TSP_ERR_NODE_NOT_FOUND, "El nodo consultado no esta registrado");
    }

    if (resultado == TSP_ERR_NO_DATA) {
        return handlers_build_error(
            s, TSP_ERR_NO_DATA, "El nodo aun no ha reportado ninguna medicion");
    }

    if (resultado != TSP_OK) {
        return handlers_build_error(
            s, TSP_ERR_INTERNAL, "No fue posible construir la respuesta");
    }

    return strlen(s->respuesta);
}

// Lee el parametro numerico opcional de GET_LAST / GET_ALERTS
static int cantidad_solicitada(const tsp_message_t *msg, int por_defecto) {
    if (msg->count < 2 || msg->field[1][0] == '\0') {
        return por_defecto;
    }

    long n = 0;

    if (!tsp_parse_long(msg->field[1], &n) || n <= 0) {
        return -1;   // parametro invalido
    }

    return (int)n;
}

static size_t cmd_get_last(tsp_session_t *s, const tsp_message_t *msg) {
    int n = cantidad_solicitada(msg, 10);

    if (n < 0) {
        return handlers_build_error(
            s, TSP_ERR_INVALID_PARAM, "La cantidad debe ser un entero positivo");
    }

    if (registry_build_last(n, s->respuesta, TSP_RESPONSE_MAX) != TSP_OK) {
        return handlers_build_error(
            s, TSP_ERR_INTERNAL, "No fue posible construir la respuesta");
    }

    return strlen(s->respuesta);
}

static size_t cmd_get_alerts(tsp_session_t *s, const tsp_message_t *msg) {
    int n = cantidad_solicitada(msg, 10);

    if (n < 0) {
        return handlers_build_error(
            s, TSP_ERR_INVALID_PARAM, "La cantidad debe ser un entero positivo");
    }

    if (registry_build_alerts(n, s->respuesta, TSP_RESPONSE_MAX) != TSP_OK) {
        return handlers_build_error(
            s, TSP_ERR_INTERNAL, "No fue posible construir la respuesta");
    }

    return strlen(s->respuesta);
}

static size_t cmd_set_threshold(tsp_session_t *s, const tsp_message_t *msg) {
    if (msg->count < 5) {
        return handlers_build_error(
            s, TSP_ERR_MISSING_PARAM,
            "SET_THRESHOLD requiere nodo, variable, minimo y maximo");
    }

    double minimo = 0.0;
    double maximo = 0.0;

    if (!tsp_parse_double(msg->field[3], &minimo) ||
        !tsp_parse_double(msg->field[4], &maximo)) {

        return handlers_build_error(
            s, TSP_ERR_INVALID_PARAM, "Los umbrales deben ser numeros");
    }

    if (minimo > maximo) {
        return handlers_build_error(
            s, TSP_ERR_INVALID_PARAM,
            "El umbral minimo no puede ser mayor que el maximo");
    }

    char destino[NODE_ID_LEN];
    char variable[VAR_NAME_LEN];

    copiar_campo(destino,  sizeof(destino),  msg->field[1]);
    copiar_campo(variable, sizeof(variable), msg->field[2]);

    tsp_to_upper(variable);

    int resultado = registry_set_threshold(destino, variable, minimo, maximo);

    if (resultado == TSP_ERR_NODE_NOT_FOUND) {
        return handlers_build_error(
            s, TSP_ERR_NODE_NOT_FOUND, "El nodo indicado no esta registrado");
    }

    if (resultado != TSP_OK) {
        return handlers_build_error(
            s, resultado, "No fue posible aplicar el umbral");
    }

    return responder(
        s,
        "OK|SET_THRESHOLD|%s|%s|%.2f|%.2f\n",
        destino,
        variable,
        minimo,
        maximo
    );
}

static size_t cmd_subscribe(tsp_session_t *s, const tsp_message_t *msg, int activar) {
    const char *canal = (msg->count >= 2) ? msg->field[1] : "ALERTS";

    char normalizado[32];

    copiar_campo(normalizado, sizeof(normalizado), canal);
    tsp_to_upper(normalizado);

    if (strcmp(normalizado, "ALERTS") != 0) {
        return handlers_build_error(
            s, TSP_ERR_INVALID_PARAM, "El unico canal disponible es ALERTS");
    }

    s->rol = TSP_ROLE_OPERATOR;

    registry_operator_set_role(s->slot, 1);
    registry_operator_subscribe(s->slot, activar);

    return responder(
        s,
        "OK|%s|ALERTS\n",
        activar ? "SUBSCRIBE" : "UNSUBSCRIBE"
    );
}

// ======================================================
// PUNTO DE ENTRADA TCP
// ======================================================

size_t handlers_process_tcp_line(tsp_session_t *s, const char *linea) {
    if (s->respuesta == NULL) {
        return 0;
    }

    tsp_message_t msg;

    int resultado = tsp_parse(linea, &msg);

    if (resultado != TSP_OK) {
        registry_stat_comando();

        return handlers_build_error(
            s,
            resultado,
            resultado == TSP_ERR_MESSAGE_TOO_LONG
                ? "El mensaje supera los 1024 bytes"
                : "Mensaje vacio o mal formado"
        );
    }

    registry_stat_comando();

    const char *tipo = msg.field[0];

    if (strcmp(tipo, "HELLO") == 0) {
        return cmd_hello(s, &msg);
    }

    if (strcmp(tipo, "REGISTER") == 0) {
        return cmd_register(s, &msg);
    }

    if (strcmp(tipo, "LIST_NODES") == 0) {
        if (registry_build_list_nodes(s->respuesta, TSP_RESPONSE_MAX) != TSP_OK) {
            return handlers_build_error(
                s, TSP_ERR_INTERNAL, "No fue posible construir la respuesta");
        }

        return strlen(s->respuesta);
    }

    if (strcmp(tipo, "GET_STATUS") == 0) {
        return cmd_get_status(s, &msg);
    }

    if (strcmp(tipo, "GET_LAST") == 0) {
        return cmd_get_last(s, &msg);
    }

    if (strcmp(tipo, "GET_ALERTS") == 0) {
        return cmd_get_alerts(s, &msg);
    }

    if (strcmp(tipo, "GET_SYSTEM") == 0) {
        if (registry_build_system(s->respuesta, TSP_RESPONSE_MAX) != TSP_OK) {
            return handlers_build_error(
                s, TSP_ERR_INTERNAL, "No fue posible construir la respuesta");
        }

        return strlen(s->respuesta);
    }

    if (strcmp(tipo, "SET_THRESHOLD") == 0) {
        return cmd_set_threshold(s, &msg);
    }

    if (strcmp(tipo, "SUBSCRIBE") == 0) {
        return cmd_subscribe(s, &msg, 1);
    }

    if (strcmp(tipo, "UNSUBSCRIBE") == 0) {
        return cmd_subscribe(s, &msg, 0);
    }

    if (strcmp(tipo, "PING") == 0) {
        return responder(s, "PONG|%ld\n", (long)time(NULL));
    }

    if (strcmp(tipo, "BYE") == 0) {
        s->cerrar = 1;

        return responder(s, "OK|BYE\n");
    }

    // TELEMETRY existe, pero solo es valido sobre UDP
    if (strcmp(tipo, "TELEMETRY") == 0) {
        return handlers_build_error(
            s, TSP_ERR_UNKNOWN_COMMAND,
            "TELEMETRY solo se acepta por UDP");
    }

    return handlers_build_error(
        s, TSP_ERR_UNKNOWN_COMMAND, "Comando no reconocido en TSP/1.0");
}

// ======================================================
// PUNTO DE ENTRADA UDP
// ======================================================

size_t handlers_process_udp(const char *datagrama,
                            const char *direccion,
                            char *out,
                            size_t cap) {

    tsp_message_t msg;

    int resultado = tsp_parse(datagrama, &msg);

    if (resultado != TSP_OK) {
        registry_stat_rechazo();

        return (size_t)tsp_format_error(
            out, cap, resultado, "Datagrama vacio o mal formado");
    }

    // Sobre UDP solo viaja telemetria
    if (strcmp(msg.field[0], "TELEMETRY") != 0) {
        registry_stat_rechazo();

        return (size_t)tsp_format_error(
            out, cap, TSP_ERR_UNKNOWN_COMMAND,
            "Por UDP solo se acepta TELEMETRY");
    }

    // TELEMETRY|<ID>|<SEQ>|<VAR>|<VALOR>...
    if (msg.count < 5) {
        registry_stat_rechazo();

        return (size_t)tsp_format_error(
            out, cap, TSP_ERR_MISSING_PARAM,
            "TELEMETRY requiere id, secuencia y al menos una medicion");
    }

    long seq = 0;

    if (!tsp_parse_long(msg.field[2], &seq) || seq < 0) {
        registry_stat_rechazo();

        return (size_t)tsp_format_error(
            out, cap, TSP_ERR_INVALID_PARAM,
            "El numero de secuencia debe ser un entero no negativo");
    }

    char nombres[MAX_VARS_PER_NODE][VAR_NAME_LEN];
    char textos[MAX_VARS_PER_NODE][TSP_FIELD_LEN];

    int pares = extraer_pares(&msg, 3, nombres, textos, MAX_VARS_PER_NODE);

    if (pares < 1) {
        registry_stat_rechazo();

        return (size_t)tsp_format_error(
            out, cap, TSP_ERR_BAD_REQUEST,
            "Las mediciones deben venir en pares variable/valor");
    }

    double valores[MAX_VARS_PER_NODE];

    for (int i = 0; i < pares; i++) {
        if (!tsp_parse_double(textos[i], &valores[i])) {
            registry_stat_rechazo();

            return (size_t)tsp_format_error(
                out, cap, TSP_ERR_INVALID_PARAM,
                "Todos los valores deben ser numericos con punto decimal");
        }
    }

    int alertas = 0;

    resultado = registry_record_telemetry(
        msg.field[1],
        seq,
        direccion,
        nombres,
        valores,
        pares,
        &alertas
    );

    if (resultado == TSP_ERR_NOT_REGISTERED) {
        return (size_t)tsp_format_error(
            out, cap, TSP_ERR_NOT_REGISTERED,
            "El nodo debe registrarse por TCP antes de enviar telemetria");
    }

    if (resultado != TSP_OK) {
        return (size_t)tsp_format_error(
            out, cap, resultado, "No fue posible procesar la telemetria");
    }

    int escritos = snprintf(
        out,
        cap,
        "ACK|%s|%ld|%d\n",
        msg.field[1],
        seq,
        alertas
    );

    if (escritos < 0 || (size_t)escritos >= cap) {
        return 0;
    }

    return (size_t)escritos;
}
