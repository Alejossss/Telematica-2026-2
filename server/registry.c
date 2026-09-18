// ======================================================
// registry.c - Estado y logica del servidor central
// ======================================================

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <time.h>
#include <errno.h>

#include <sys/socket.h>

#include "registry.h"
#include "protocol.h"

// ======================================================
// TABLAS PROTEGIDAS POR MUTEX
//
// Orden de bloqueo: NUNCA se toma g_op_mutex teniendo
// g_mutex. Las alertas se copian a una variable local,
// se libera g_mutex y solo despues se difunden. Asi el
// envio por socket jamas bloquea al hilo UDP.
// ======================================================

static pthread_mutex_t g_mutex    = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t g_op_mutex = PTHREAD_MUTEX_INITIALIZER;

// ------------------------------------------------------
// Nodos
// ------------------------------------------------------

static node_t g_nodes[MAX_NODES];

// ------------------------------------------------------
// Historial circular de mediciones
// ------------------------------------------------------

typedef struct {
    char   node_id[NODE_ID_LEN];
    char   var[VAR_NAME_LEN];
    char   unidad[UNIT_LEN];
    double valor;
    time_t ts;
} measurement_t;

static measurement_t g_meas[MAX_MEASUREMENTS];
static int           g_meas_head  = 0;
static int           g_meas_count = 0;

// ------------------------------------------------------
// Historial circular de alertas
// ------------------------------------------------------

static alert_t g_alerts[MAX_ALERTS];
static int     g_alert_head  = 0;
static int     g_alert_count = 0;

// ------------------------------------------------------
// Umbrales de deteccion de anomalias
// ------------------------------------------------------

typedef struct {
    int    en_uso;
    char   node_id[NODE_ID_LEN];   // "*" = umbral global
    char   var[VAR_NAME_LEN];
    double minimo;
    double maximo;
} threshold_t;

static threshold_t g_thresholds[MAX_THRESHOLDS];

// ------------------------------------------------------
// Operadores conectados
// ------------------------------------------------------

typedef struct {
    int    en_uso;
    int    fd;
    int    suscrito;
    int    es_operador;   // 0 mientras la conexion no se identifique
    char   nombre[48];
    char   direccion[64];
    time_t conectado_en;
} operator_t;

static operator_t g_operators[MAX_OPERATORS];

// ------------------------------------------------------
// Estadisticas globales
// ------------------------------------------------------

static time_t        g_inicio            = 0;
static int           g_udp_port          = 0;
static int           g_tcp_port          = 0;
static unsigned long g_telemetria_ok     = 0;
static unsigned long g_telemetria_rechazada = 0;
static unsigned long g_comandos_tcp      = 0;
static unsigned long g_alertas_generadas = 0;

// ======================================================
// UTILIDADES INTERNAS (se llaman con g_mutex tomado)
// ======================================================

static int comparar_ident(const char *a, const char *b) {
    // R7: identificadores y variables se comparan en mayusculas
    for (; *a && *b; a++, b++) {
        char ca = (*a >= 'a' && *a <= 'z') ? (char)(*a - 32) : *a;
        char cb = (*b >= 'a' && *b <= 'z') ? (char)(*b - 32) : *b;

        if (ca != cb) {
            return 0;
        }
    }

    return *a == '\0' && *b == '\0';
}

static node_t *buscar_nodo(const char *id) {
    for (int i = 0; i < MAX_NODES; i++) {
        if (g_nodes[i].en_uso && comparar_ident(g_nodes[i].id, id)) {
            return &g_nodes[i];
        }
    }

    return NULL;
}

static void copiar(char *destino, size_t cap, const char *origen) {
    if (cap == 0) {
        return;
    }

    size_t i = 0;

    while (origen != NULL && origen[i] != '\0' && i + 1 < cap) {
        char c = origen[i];
        destino[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
        i++;
    }

    destino[i] = '\0';
}

static void copiar_tal_cual(char *destino, size_t cap, const char *origen) {
    if (cap == 0) {
        return;
    }

    size_t i = 0;

    while (origen != NULL && origen[i] != '\0' && i + 1 < cap) {
        destino[i] = origen[i];
        i++;
    }

    destino[i] = '\0';
}

// Busca el umbral aplicable: primero la excepcion del nodo,
// despues el umbral global de la variable.
static threshold_t *buscar_umbral(const char *node_id, const char *var) {
    threshold_t *global = NULL;

    for (int i = 0; i < MAX_THRESHOLDS; i++) {
        if (!g_thresholds[i].en_uso) {
            continue;
        }

        if (!comparar_ident(g_thresholds[i].var, var)) {
            continue;
        }

        if (comparar_ident(g_thresholds[i].node_id, node_id)) {
            return &g_thresholds[i];
        }

        if (strcmp(g_thresholds[i].node_id, "*") == 0) {
            global = &g_thresholds[i];
        }
    }

    return global;
}

static void guardar_medicion(const char *node_id,
                             const char *var,
                             const char *unidad,
                             double valor,
                             time_t ts) {

    measurement_t *m = &g_meas[g_meas_head];

    copiar_tal_cual(m->node_id, sizeof(m->node_id), node_id);
    copiar_tal_cual(m->var,     sizeof(m->var),     var);
    copiar_tal_cual(m->unidad,  sizeof(m->unidad),  unidad);

    m->valor = valor;
    m->ts    = ts;

    g_meas_head = (g_meas_head + 1) % MAX_MEASUREMENTS;

    if (g_meas_count < MAX_MEASUREMENTS) {
        g_meas_count++;
    }
}

static void guardar_alerta(const alert_t *a) {
    g_alerts[g_alert_head] = *a;

    g_alert_head = (g_alert_head + 1) % MAX_ALERTS;

    if (g_alert_count < MAX_ALERTS) {
        g_alert_count++;
    }

    g_alertas_generadas++;
}

// ======================================================
// DIFUSION DE ALERTAS A LOS OPERADORES SUSCRITOS
//
// Se llama SIN g_mutex tomado.
// ======================================================

static void difundir_alertas(const alert_t *alertas, int n) {
    for (int i = 0; i < n; i++) {
        char linea[TSP_MAX_MESSAGE];

        int largo = snprintf(
            linea,
            sizeof(linea),
            "ALERT|%s|%s|%.2f|%ld|%s\n",
            alertas[i].node_id,
            alertas[i].tipo,
            alertas[i].valor,
            (long)alertas[i].ts,
            alertas[i].severidad
        );

        if (largo < 0 || (size_t)largo >= sizeof(linea)) {
            continue;
        }

        printf(
            "[ALERTA] %s %s valor=%.2f severidad=%s\n",
            alertas[i].node_id,
            alertas[i].tipo,
            alertas[i].valor,
            alertas[i].severidad
        );

        fflush(stdout);

        pthread_mutex_lock(&g_op_mutex);

        for (int s = 0; s < MAX_OPERATORS; s++) {
            if (!g_operators[s].en_uso || !g_operators[s].suscrito) {
                continue;
            }

            // Si el operador ya se fue, send() falla y simplemente
            // se ignora: su propio hilo hara la limpieza del slot.
            ssize_t enviados = send(g_operators[s].fd, linea, (size_t)largo, 0);

            if (enviados < 0) {
                perror("[ALERTA] Error empujando alerta a un operador");
            }
        }

        pthread_mutex_unlock(&g_op_mutex);
    }
}

// ======================================================
// INICIALIZACION
// ======================================================

static void agregar_umbral_por_defecto(const char *var, double minimo, double maximo) {
    for (int i = 0; i < MAX_THRESHOLDS; i++) {
        if (g_thresholds[i].en_uso) {
            continue;
        }

        g_thresholds[i].en_uso = 1;

        copiar(g_thresholds[i].node_id, sizeof(g_thresholds[i].node_id), "*");
        copiar(g_thresholds[i].var,     sizeof(g_thresholds[i].var),     var);

        g_thresholds[i].minimo = minimo;
        g_thresholds[i].maximo = maximo;

        return;
    }
}

void registry_init(int udp_port, int tcp_port) {
    pthread_mutex_lock(&g_mutex);

    memset(g_nodes,      0, sizeof(g_nodes));
    memset(g_meas,       0, sizeof(g_meas));
    memset(g_alerts,     0, sizeof(g_alerts));
    memset(g_thresholds, 0, sizeof(g_thresholds));

    g_meas_head  = 0;
    g_meas_count = 0;

    g_alert_head  = 0;
    g_alert_count = 0;

    g_inicio   = time(NULL);
    g_udp_port = udp_port;
    g_tcp_port = tcp_port;

    g_telemetria_ok        = 0;
    g_telemetria_rechazada = 0;
    g_comandos_tcp         = 0;
    g_alertas_generadas    = 0;

    // Umbrales por defecto (seccion 6 de docs/PROTOCOLO.md)
    agregar_umbral_por_defecto("TEMP",   -10.0,   40.0);
    agregar_umbral_por_defecto("HUM",     10.0,   85.0);
    agregar_umbral_por_defecto("PWR",      0.0, 2000.0);
    agregar_umbral_por_defecto("VIB",      0.0,    5.0);
    agregar_umbral_por_defecto("STATUS",   1.0,    1.0);  // 1 = operativo

    pthread_mutex_unlock(&g_mutex);

    pthread_mutex_lock(&g_op_mutex);
    memset(g_operators, 0, sizeof(g_operators));
    pthread_mutex_unlock(&g_op_mutex);

    printf("[REGISTRO] Estado inicializado (UDP %d, TCP %d)\n", udp_port, tcp_port);
}

// ======================================================
// HILO MONITOR - DETECCION DE NODOS CAIDOS
// ======================================================

static void *monitor_thread(void *arg) {
    (void)arg;

    printf("[MONITOR] Vigilando nodos (timeout %d s)\n", NODE_TIMEOUT_SEG);

    while (1) {
        sleep(MONITOR_PERIOD_SEG);

        alert_t pendientes[MAX_NODES];
        int     n_pendientes = 0;

        time_t ahora = time(NULL);

        pthread_mutex_lock(&g_mutex);

        for (int i = 0; i < MAX_NODES; i++) {
            node_t *nodo = &g_nodes[i];

            if (!nodo->en_uso || !nodo->online) {
                continue;
            }

            if (ahora - nodo->ultima_medicion <= NODE_TIMEOUT_SEG) {
                continue;
            }

            // Transicion ONLINE -> OFFLINE: se alerta una sola vez
            nodo->online = 0;

            if (n_pendientes < MAX_NODES) {
                alert_t *a = &pendientes[n_pendientes++];

                memset(a, 0, sizeof(*a));

                copiar_tal_cual(a->node_id,   sizeof(a->node_id),   nodo->id);
                copiar_tal_cual(a->tipo,      sizeof(a->tipo),      "NODE_OFFLINE");
                copiar_tal_cual(a->var,       sizeof(a->var),       "-");
                copiar_tal_cual(a->severidad, sizeof(a->severidad), "CRITICAL");

                a->valor = (double)(ahora - nodo->ultima_medicion);
                a->ts    = ahora;

                guardar_alerta(a);
            }
        }

        pthread_mutex_unlock(&g_mutex);

        difundir_alertas(pendientes, n_pendientes);
    }

    return NULL;
}

int registry_start_monitor(void) {
    pthread_t hilo;

    if (pthread_create(&hilo, NULL, monitor_thread, NULL) != 0) {
        perror("[MONITOR] Error creando hilo monitor");
        return -1;
    }

    pthread_detach(hilo);

    return 0;
}

// ======================================================
// REGISTRO DE NODOS
// ======================================================

int registry_register_node(const char *id,
                           const char *tipo,
                           const char *ubicacion,
                           char nombres[][VAR_NAME_LEN],
                           char unidades[][UNIT_LEN],
                           int  nvars) {

    if (nvars <= 0 || nvars > MAX_VARS_PER_NODE) {
        return TSP_ERR_LIMIT_REACHED;
    }

    pthread_mutex_lock(&g_mutex);

    node_t *nodo = buscar_nodo(id);
    int     nuevo = 0;

    // Un nodo que estaba caido y se vuelve a registrar es una vuelta al
    // servicio, y como tal hay que anunciarla
    int volvio = (nodo != NULL && !nodo->online);

    if (nodo == NULL) {
        for (int i = 0; i < MAX_NODES; i++) {
            if (!g_nodes[i].en_uso) {
                nodo  = &g_nodes[i];
                nuevo = 1;
                break;
            }
        }
    }

    if (nodo == NULL) {
        pthread_mutex_unlock(&g_mutex);
        return TSP_ERR_LIMIT_REACHED;
    }

    time_t ahora = time(NULL);

    memset(nodo, 0, sizeof(*nodo));

    nodo->en_uso = 1;
    nodo->online = 1;

    copiar(nodo->id, sizeof(nodo->id), id);

    copiar_tal_cual(nodo->tipo,      sizeof(nodo->tipo),      tipo);
    copiar_tal_cual(nodo->ubicacion, sizeof(nodo->ubicacion), ubicacion);
    copiar_tal_cual(nodo->direccion, sizeof(nodo->direccion), "-");

    nodo->registrado_en = ahora;

    // Se le concede el periodo de gracia del monitor para su primer envio
    nodo->ultima_medicion = ahora;

    nodo->ultimo_seq    = -1;
    nodo->msgs_recibidos = 0;
    nodo->perdidos_est   = 0;

    nodo->nvars = nvars;

    for (int i = 0; i < nvars; i++) {
        copiar(nodo->vars[i].name, sizeof(nodo->vars[i].name), nombres[i]);
        copiar_tal_cual(nodo->vars[i].unit, sizeof(nodo->vars[i].unit), unidades[i]);

        nodo->vars[i].tiene_valor = 0;
    }

    alert_t aviso;
    int     hay_aviso = 0;

    if (volvio) {
        memset(&aviso, 0, sizeof(aviso));

        copiar_tal_cual(aviso.node_id,   sizeof(aviso.node_id),   nodo->id);
        copiar_tal_cual(aviso.tipo,      sizeof(aviso.tipo),      "NODE_ONLINE");
        copiar_tal_cual(aviso.var,       sizeof(aviso.var),       "-");
        copiar_tal_cual(aviso.severidad, sizeof(aviso.severidad), "INFO");

        aviso.valor = 0.0;
        aviso.ts    = ahora;

        guardar_alerta(&aviso);

        hay_aviso = 1;
    }

    pthread_mutex_unlock(&g_mutex);

    // La difusion siempre se hace fuera del mutex
    if (hay_aviso) {
        difundir_alertas(&aviso, 1);
    }

    printf(
        "[REGISTRO] Nodo %s %s (%s / %s) con %d variables\n",
        id,
        nuevo ? "dado de alta" : "re-registrado",
        tipo,
        ubicacion,
        nvars
    );

    return TSP_OK;
}

// ======================================================
// PROCESAMIENTO DE TELEMETRIA Y DETECCION DE ANOMALIAS
// ======================================================

int registry_record_telemetry(const char *id,
                              long seq,
                              const char *direccion,
                              char nombres[][VAR_NAME_LEN],
                              const double *valores,
                              int  nvars,
                              int *alertas) {

    alert_t pendientes[MAX_ALERTS_PER_MSG];
    int     n_pendientes = 0;

    *alertas = 0;

    pthread_mutex_lock(&g_mutex);

    node_t *nodo = buscar_nodo(id);

    if (nodo == NULL) {
        g_telemetria_rechazada++;
        pthread_mutex_unlock(&g_mutex);

        return TSP_ERR_NOT_REGISTERED;
    }

    time_t ahora = time(NULL);

    // --------------------------------------------------
    // Estimacion de datagramas perdidos a partir de SEQ
    // (metrica exigida por el punto 11)
    // --------------------------------------------------

    if (nodo->ultimo_seq >= 0 && seq > nodo->ultimo_seq + 1) {
        nodo->perdidos_est += (unsigned long)(seq - nodo->ultimo_seq - 1);
    }

    if (seq > nodo->ultimo_seq) {
        nodo->ultimo_seq = seq;
    }

    nodo->msgs_recibidos++;
    nodo->ultima_medicion = ahora;

    copiar_tal_cual(nodo->direccion, sizeof(nodo->direccion), direccion);

    // El nodo estaba caido y volvio
    if (!nodo->online) {
        nodo->online = 1;

        if (n_pendientes < MAX_ALERTS_PER_MSG) {
            alert_t *a = &pendientes[n_pendientes++];

            memset(a, 0, sizeof(*a));

            copiar_tal_cual(a->node_id,   sizeof(a->node_id),   nodo->id);
            copiar_tal_cual(a->tipo,      sizeof(a->tipo),      "NODE_ONLINE");
            copiar_tal_cual(a->var,       sizeof(a->var),       "-");
            copiar_tal_cual(a->severidad, sizeof(a->severidad), "INFO");

            a->valor = 0.0;
            a->ts    = ahora;

            guardar_alerta(a);
        }
    }

    // --------------------------------------------------
    // Actualizacion de variables y deteccion de anomalias
    // --------------------------------------------------

    for (int i = 0; i < nvars; i++) {
        registry_var_t *var = NULL;

        for (int j = 0; j < nodo->nvars; j++) {
            if (comparar_ident(nodo->vars[j].name, nombres[i])) {
                var = &nodo->vars[j];
                break;
            }
        }

        // Variable no declarada en el REGISTER: se acepta igualmente
        if (var == NULL && nodo->nvars < MAX_VARS_PER_NODE) {
            var = &nodo->vars[nodo->nvars++];

            memset(var, 0, sizeof(*var));

            copiar(var->name, sizeof(var->name), nombres[i]);
            copiar_tal_cual(var->unit, sizeof(var->unit), "-");
        }

        if (var == NULL) {
            continue;   // no cabe una variable mas en este nodo
        }

        var->valor       = valores[i];
        var->ts          = ahora;
        var->tiene_valor = 1;

        guardar_medicion(nodo->id, var->name, var->unit, valores[i], ahora);

        // ----------------------------------------------
        // Comparacion contra el umbral aplicable
        // ----------------------------------------------

        threshold_t *umbral = buscar_umbral(nodo->id, var->name);

        if (umbral == NULL) {
            continue;   // variable sin umbral: no se alerta
        }

        double valor = valores[i];

        if (valor >= umbral->minimo && valor <= umbral->maximo) {
            continue;   // valor normal
        }

        if (n_pendientes >= MAX_ALERTS_PER_MSG) {
            continue;
        }

        double exceso   = (valor > umbral->maximo)
                        ? valor - umbral->maximo
                        : umbral->minimo - valor;

        double amplitud = umbral->maximo - umbral->minimo;

        const char *severidad =
            (amplitud <= 0.0 || exceso >= 0.2 * amplitud) ? "CRITICAL" : "WARN";

        alert_t *a = &pendientes[n_pendientes++];

        memset(a, 0, sizeof(*a));

        copiar_tal_cual(a->node_id, sizeof(a->node_id), nodo->id);
        copiar_tal_cual(a->var,     sizeof(a->var),     var->name);
        copiar_tal_cual(a->severidad, sizeof(a->severidad), severidad);

        if (comparar_ident(var->name, "STATUS")) {
            copiar_tal_cual(a->tipo, sizeof(a->tipo), "STATUS_FAIL");
        } else {
            snprintf(
                a->tipo,
                sizeof(a->tipo),
                "%s_%s",
                var->name,
                (valor > umbral->maximo) ? "HIGH" : "LOW"
            );
        }

        a->valor = valor;
        a->ts    = ahora;

        guardar_alerta(a);
    }

    g_telemetria_ok++;

    pthread_mutex_unlock(&g_mutex);

    // El envio a los operadores se hace ya sin el mutex tomado
    difundir_alertas(pendientes, n_pendientes);

    *alertas = n_pendientes;

    return TSP_OK;
}

// ======================================================
// CONSULTAS DE LOS OPERADORES
// ======================================================

int registry_build_list_nodes(char *out, size_t cap) {
    tsp_sbuf_t sb;

    tsp_sbuf_init(&sb, out, cap);

    pthread_mutex_lock(&g_mutex);

    time_t ahora = time(NULL);
    int    total = 0;

    for (int i = 0; i < MAX_NODES; i++) {
        if (g_nodes[i].en_uso) {
            total++;
        }
    }

    tsp_sbuf_addf(&sb, "OK|LIST_NODES|%d\n", total);

    for (int i = 0; i < MAX_NODES; i++) {
        node_t *nodo = &g_nodes[i];

        if (!nodo->en_uso) {
            continue;
        }

        tsp_sbuf_addf(
            &sb,
            "NODE|%s|%s|%s|%s|%ld|%lu|%lu\n",
            nodo->id,
            nodo->online ? "ONLINE" : "OFFLINE",
            nodo->tipo,
            nodo->ubicacion,
            (long)(ahora - nodo->ultima_medicion),
            nodo->msgs_recibidos,
            nodo->perdidos_est
        );
    }

    pthread_mutex_unlock(&g_mutex);

    tsp_sbuf_addf(&sb, "END|LIST_NODES\n");

    return sb.overflow ? TSP_ERR_INTERNAL : TSP_OK;
}

int registry_build_node_status(const char *id, char *out, size_t cap) {
    tsp_sbuf_t sb;

    tsp_sbuf_init(&sb, out, cap);

    pthread_mutex_lock(&g_mutex);

    node_t *nodo = buscar_nodo(id);

    if (nodo == NULL) {
        pthread_mutex_unlock(&g_mutex);
        return TSP_ERR_NODE_NOT_FOUND;
    }

    time_t ahora = time(NULL);

    int con_valor = 0;

    for (int i = 0; i < nodo->nvars; i++) {
        if (nodo->vars[i].tiene_valor) {
            con_valor++;
        }
    }

    // El nodo esta dado de alta pero todavia no ha reportado nada
    if (con_valor == 0) {
        pthread_mutex_unlock(&g_mutex);
        return TSP_ERR_NO_DATA;
    }

    tsp_sbuf_addf(
        &sb,
        "OK|GET_STATUS|%s|%s|%ld|%d\n",
        nodo->id,
        nodo->online ? "ONLINE" : "OFFLINE",
        (long)(ahora - nodo->ultima_medicion),
        con_valor
    );

    for (int i = 0; i < nodo->nvars; i++) {
        if (!nodo->vars[i].tiene_valor) {
            continue;
        }

        tsp_sbuf_addf(
            &sb,
            "VAR|%s|%.2f|%s|%ld\n",
            nodo->vars[i].name,
            nodo->vars[i].valor,
            nodo->vars[i].unit,
            (long)nodo->vars[i].ts
        );
    }

    pthread_mutex_unlock(&g_mutex);

    tsp_sbuf_addf(&sb, "END|GET_STATUS\n");

    return sb.overflow ? TSP_ERR_INTERNAL : TSP_OK;
}

int registry_build_last(int n, char *out, size_t cap) {
    tsp_sbuf_t sb;

    tsp_sbuf_init(&sb, out, cap);

    pthread_mutex_lock(&g_mutex);

    if (n <= 0) {
        n = 10;
    }

    if (n > g_meas_count) {
        n = g_meas_count;
    }

    tsp_sbuf_addf(&sb, "OK|GET_LAST|%d\n", n);

    // Del mas reciente al mas antiguo
    for (int k = 0; k < n; k++) {
        int idx = (g_meas_head - 1 - k + MAX_MEASUREMENTS * 2) % MAX_MEASUREMENTS;

        measurement_t *m = &g_meas[idx];

        tsp_sbuf_addf(
            &sb,
            "MEAS|%s|%s|%.2f|%s|%ld\n",
            m->node_id,
            m->var,
            m->valor,
            m->unidad,
            (long)m->ts
        );
    }

    pthread_mutex_unlock(&g_mutex);

    tsp_sbuf_addf(&sb, "END|GET_LAST\n");

    return sb.overflow ? TSP_ERR_INTERNAL : TSP_OK;
}

int registry_build_alerts(int n, char *out, size_t cap) {
    tsp_sbuf_t sb;

    tsp_sbuf_init(&sb, out, cap);

    pthread_mutex_lock(&g_mutex);

    if (n <= 0) {
        n = 10;
    }

    if (n > g_alert_count) {
        n = g_alert_count;
    }

    tsp_sbuf_addf(&sb, "OK|GET_ALERTS|%d\n", n);

    for (int k = 0; k < n; k++) {
        int idx = (g_alert_head - 1 - k + MAX_ALERTS * 2) % MAX_ALERTS;

        alert_t *a = &g_alerts[idx];

        // Los registros del historial usan EVENT y no ALERT: una alerta
        // empujada puede llegar en mitad de esta respuesta, y el cliente
        // tiene que poder distinguirlas mirando una sola linea.
        tsp_sbuf_addf(
            &sb,
            "EVENT|%s|%s|%.2f|%ld|%s\n",
            a->node_id,
            a->tipo,
            a->valor,
            (long)a->ts,
            a->severidad
        );
    }

    pthread_mutex_unlock(&g_mutex);

    tsp_sbuf_addf(&sb, "END|GET_ALERTS\n");

    return sb.overflow ? TSP_ERR_INTERNAL : TSP_OK;
}

int registry_build_system(char *out, size_t cap) {
    tsp_sbuf_t sb;

    tsp_sbuf_init(&sb, out, cap);

    // Se cuenta primero a los operadores para no anidar los dos mutex
    int operadores = 0;

    pthread_mutex_lock(&g_op_mutex);

    for (int i = 0; i < MAX_OPERATORS; i++) {
        if (g_operators[i].en_uso && g_operators[i].es_operador) {
            operadores++;
        }
    }

    pthread_mutex_unlock(&g_op_mutex);

    pthread_mutex_lock(&g_mutex);

    int registrados = 0;
    int activos     = 0;

    unsigned long perdidos = 0;

    for (int i = 0; i < MAX_NODES; i++) {
        if (!g_nodes[i].en_uso) {
            continue;
        }

        registrados++;

        if (g_nodes[i].online) {
            activos++;
        }

        perdidos += g_nodes[i].perdidos_est;
    }

    long uptime = (long)(time(NULL) - g_inicio);

    tsp_sbuf_addf(&sb, "OK|GET_SYSTEM|9\n");
    tsp_sbuf_addf(&sb, "STAT|UPTIME_SEG|%ld\n",             uptime);
    tsp_sbuf_addf(&sb, "STAT|NODOS_REGISTRADOS|%d\n",       registrados);
    tsp_sbuf_addf(&sb, "STAT|NODOS_ACTIVOS|%d\n",           activos);
    tsp_sbuf_addf(&sb, "STAT|OPERADORES_CONECTADOS|%d\n",   operadores);
    tsp_sbuf_addf(&sb, "STAT|TELEMETRIA_RECIBIDA|%lu\n",    g_telemetria_ok);
    tsp_sbuf_addf(&sb, "STAT|TELEMETRIA_RECHAZADA|%lu\n",   g_telemetria_rechazada);
    tsp_sbuf_addf(&sb, "STAT|TELEMETRIA_PERDIDA_EST|%lu\n", perdidos);
    tsp_sbuf_addf(&sb, "STAT|COMANDOS_TCP|%lu\n",           g_comandos_tcp);
    tsp_sbuf_addf(&sb, "STAT|ALERTAS_GENERADAS|%lu\n",      g_alertas_generadas);

    pthread_mutex_unlock(&g_mutex);

    tsp_sbuf_addf(&sb, "END|GET_SYSTEM\n");

    return sb.overflow ? TSP_ERR_INTERNAL : TSP_OK;
}

int registry_set_threshold(const char *node_id,
                           const char *var,
                           double minimo,
                           double maximo) {

    if (minimo > maximo) {
        return TSP_ERR_INVALID_PARAM;
    }

    pthread_mutex_lock(&g_mutex);

    // Si el destino es un nodo concreto, debe existir
    if (strcmp(node_id, "*") != 0 && buscar_nodo(node_id) == NULL) {
        pthread_mutex_unlock(&g_mutex);
        return TSP_ERR_NODE_NOT_FOUND;
    }

    threshold_t *destino = NULL;

    for (int i = 0; i < MAX_THRESHOLDS; i++) {
        if (g_thresholds[i].en_uso &&
            comparar_ident(g_thresholds[i].var, var) &&
            comparar_ident(g_thresholds[i].node_id, node_id)) {

            destino = &g_thresholds[i];
            break;
        }
    }

    if (destino == NULL) {
        for (int i = 0; i < MAX_THRESHOLDS; i++) {
            if (!g_thresholds[i].en_uso) {
                destino = &g_thresholds[i];
                break;
            }
        }
    }

    if (destino == NULL) {
        pthread_mutex_unlock(&g_mutex);
        return TSP_ERR_LIMIT_REACHED;
    }

    destino->en_uso = 1;

    copiar(destino->node_id, sizeof(destino->node_id), node_id);
    copiar(destino->var,     sizeof(destino->var),     var);

    destino->minimo = minimo;
    destino->maximo = maximo;

    pthread_mutex_unlock(&g_mutex);

    printf(
        "[UMBRAL] %s / %s -> [%.2f , %.2f]\n",
        node_id,
        var,
        minimo,
        maximo
    );

    return TSP_OK;
}

// ======================================================
// OPERADORES CONECTADOS
// ======================================================

int registry_operator_add(int fd, const char *direccion) {
    pthread_mutex_lock(&g_op_mutex);

    int slot = -1;

    for (int i = 0; i < MAX_OPERATORS; i++) {
        if (!g_operators[i].en_uso) {
            slot = i;
            break;
        }
    }

    if (slot >= 0) {
        memset(&g_operators[slot], 0, sizeof(g_operators[slot]));

        g_operators[slot].en_uso       = 1;
        g_operators[slot].fd           = fd;
        g_operators[slot].suscrito     = 0;
        g_operators[slot].conectado_en = time(NULL);

        copiar_tal_cual(g_operators[slot].nombre,    sizeof(g_operators[slot].nombre),    "anonimo");
        copiar_tal_cual(g_operators[slot].direccion, sizeof(g_operators[slot].direccion), direccion);
    }

    pthread_mutex_unlock(&g_op_mutex);

    return slot;
}

void registry_operator_remove(int slot) {
    if (slot < 0 || slot >= MAX_OPERATORS) {
        return;
    }

    pthread_mutex_lock(&g_op_mutex);

    g_operators[slot].en_uso   = 0;
    g_operators[slot].suscrito = 0;
    g_operators[slot].fd       = -1;

    pthread_mutex_unlock(&g_op_mutex);
}

void registry_operator_set_name(int slot, const char *nombre) {
    if (slot < 0 || slot >= MAX_OPERATORS) {
        return;
    }

    pthread_mutex_lock(&g_op_mutex);

    if (g_operators[slot].en_uso) {
        copiar_tal_cual(g_operators[slot].nombre, sizeof(g_operators[slot].nombre), nombre);
    }

    pthread_mutex_unlock(&g_op_mutex);
}

void registry_operator_set_role(int slot, int es_operador) {
    if (slot < 0 || slot >= MAX_OPERATORS) {
        return;
    }

    pthread_mutex_lock(&g_op_mutex);

    if (g_operators[slot].en_uso) {
        g_operators[slot].es_operador = es_operador;
    }

    pthread_mutex_unlock(&g_op_mutex);
}

void registry_operator_subscribe(int slot, int activar) {
    if (slot < 0 || slot >= MAX_OPERATORS) {
        return;
    }

    pthread_mutex_lock(&g_op_mutex);

    if (g_operators[slot].en_uso) {
        g_operators[slot].suscrito = activar;
    }

    pthread_mutex_unlock(&g_op_mutex);
}

int registry_operator_send(int slot, const char *msg, size_t len) {
    if (slot < 0 || slot >= MAX_OPERATORS) {
        return -1;
    }

    pthread_mutex_lock(&g_op_mutex);

    if (!g_operators[slot].en_uso) {
        pthread_mutex_unlock(&g_op_mutex);
        return -1;
    }

    int fd = g_operators[slot].fd;

    // send() puede quedarse corto: se reintenta hasta vaciar el mensaje
    size_t enviados = 0;
    int    error    = 0;

    while (enviados < len) {
        ssize_t n = send(fd, msg + enviados, len - enviados, 0);

        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }

            perror("[OPERADOR] Error enviando respuesta");
            error = -1;
            break;
        }

        enviados += (size_t)n;
    }

    pthread_mutex_unlock(&g_op_mutex);

    return error;
}

// ======================================================
// ESTADISTICAS
// ======================================================

long registry_uptime(void) {
    pthread_mutex_lock(&g_mutex);
    long uptime = (long)(time(NULL) - g_inicio);
    pthread_mutex_unlock(&g_mutex);

    return uptime;
}

int registry_udp_port(void) {
    pthread_mutex_lock(&g_mutex);
    int puerto = g_udp_port;
    pthread_mutex_unlock(&g_mutex);

    return puerto;
}

void registry_stat_comando(void) {
    pthread_mutex_lock(&g_mutex);
    g_comandos_tcp++;
    pthread_mutex_unlock(&g_mutex);
}

void registry_stat_rechazo(void) {
    pthread_mutex_lock(&g_mutex);
    g_telemetria_rechazada++;
    pthread_mutex_unlock(&g_mutex);
}
