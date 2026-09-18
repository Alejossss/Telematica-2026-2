// ======================================================
// server_concurrent.c - Servidor central
//
// Sockets y concurrencia (puntos 4 y 6):
//   - un socket TCP que acepta operadores y registros
//   - un socket UDP que recibe la telemetria
//   - un hilo por cliente TCP (pthread)
//   - TCP y UDP funcionando simultaneamente
//
// Logica de aplicacion (puntos 3 y 5):
//   - protocol.c  analiza y construye mensajes TSP/1.0
//   - handlers.c  decide que hacer con cada mensaje
//   - registry.c  guarda nodos, mediciones y alertas
// ======================================================

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <errno.h>
#include <signal.h>

#include <arpa/inet.h>
#include <sys/socket.h>

#include "protocol.h"
#include "registry.h"
#include "handlers.h"

#define TCP_PORT_DEFECTO 6000
#define UDP_PORT_DEFECTO 5000
#define BUFFER_SIZE      1024

// Puertos efectivos: se leen del entorno para poder publicarlos
// desde Docker sin recompilar (punto 9)
static int g_tcp_port = TCP_PORT_DEFECTO;
static int g_udp_port = UDP_PORT_DEFECTO;

// Datos que recibe el hilo de cada cliente TCP
typedef struct {
    int  fd;
    char direccion[64];
} tcp_client_arg_t;

// ======================================================
// CONFIGURACION
// ======================================================

static int puerto_desde_entorno(const char *variable, int por_defecto) {
    const char *valor = getenv(variable);

    if (valor == NULL || *valor == '\0') {
        return por_defecto;
    }

    int puerto = atoi(valor);

    if (puerto <= 0 || puerto > 65535) {
        fprintf(
            stderr,
            "[CONFIG] %s='%s' no es un puerto valido, se usa %d\n",
            variable,
            valor,
            por_defecto
        );

        return por_defecto;
    }

    return puerto;
}

// inet_ntoa() usa un buffer estatico compartido: con el hilo UDP y el
// hilo principal resolviendo direcciones a la vez se corrompen entre si.
// inet_ntop() escribe en un buffer propio de cada hilo.
static void formatear_direccion(const struct sockaddr_in *addr,
                                char *out,
                                size_t cap) {

    char ip[INET_ADDRSTRLEN];

    if (inet_ntop(AF_INET, &addr->sin_addr, ip, sizeof(ip)) == NULL) {
        snprintf(ip, sizeof(ip), "?");
    }

    snprintf(out, cap, "%s:%d", ip, ntohs(addr->sin_port));
}

// ======================================================
// HILO PARA CADA CLIENTE TCP
//
// Atiende tanto a los operadores como al registro de los
// nodos. El rol lo decide el primer mensaje del cliente.
// ======================================================

void *handle_tcp_client(void *arg) {
    tcp_client_arg_t *info = (tcp_client_arg_t *)arg;

    int  client_fd = info->fd;
    char direccion[64];

    snprintf(direccion, sizeof(direccion), "%s", info->direccion);

    free(info);

    char buffer[BUFFER_SIZE];

    tsp_session_t sesion;
    tsp_linebuf_t entrada;

    tsp_linebuf_init(&entrada);

    int estado = handlers_session_init(&sesion, client_fd, direccion);

    // No quedan slots libres: se avisa al cliente y se cierra
    if (estado != TSP_OK) {
        char aviso[256];

        int n = tsp_format_error(
            aviso,
            sizeof(aviso),
            estado,
            "El servidor no admite mas conexiones simultaneas"
        );

        if (n > 0) {
            send(client_fd, aviso, (size_t)n, 0);
        }

        close(client_fd);

        printf("[TCP-HILO] Conexion rechazada desde %s\n", direccion);

        return NULL;
    }

    printf("[TCP-HILO] Sesion TSP abierta con %s\n", direccion);

    while (1) {
        ssize_t bytes_received = recv(client_fd, buffer, sizeof(buffer), 0);

        if (bytes_received < 0) {
            if (errno == EINTR) {
                continue;
            }

            perror("[TCP-HILO] Error recibiendo mensaje");
            break;
        }

        if (bytes_received == 0) {
            printf("[TCP-HILO] Cliente %s desconectado\n", direccion);
            break;
        }

        // TCP entrega un FLUJO de bytes, no mensajes: puede llegar
        // media linea o tres lineas juntas. El linebuf las reconstruye.
        int problema = tsp_linebuf_push(&entrada, buffer, (size_t)bytes_received);

        if (problema != TSP_OK) {
            size_t n = handlers_build_error(
                &sesion, problema, "El mensaje supera los 1024 bytes");

            if (n > 0) {
                registry_operator_send(sesion.slot, sesion.respuesta, n);
            }
        }

        char linea[TSP_MAX_MESSAGE];
        int  fallo_envio = 0;
        int  extraida;

        while ((extraida = tsp_linebuf_next(&entrada, linea, sizeof(linea))) != 0) {

            // La linea excedia el limite del protocolo: se responde
            // ERR|413 sin intentar interpretarla
            size_t n = (extraida == 2)
                ? handlers_build_error(&sesion,
                                       TSP_ERR_MESSAGE_TOO_LONG,
                                       "El mensaje supera los 1024 bytes")
                : handlers_process_tcp_line(&sesion, linea);

            if (n > 0) {
                if (registry_operator_send(sesion.slot, sesion.respuesta, n) < 0) {
                    fallo_envio = 1;
                    break;
                }
            }

            if (sesion.cerrar) {
                break;
            }
        }

        if (fallo_envio || sesion.cerrar) {
            break;
        }
    }

    handlers_session_end(&sesion);

    close(client_fd);

    printf("[TCP-HILO] Conexion con %s cerrada\n", direccion);

    return NULL;
}

// ======================================================
// HILO UDP - RECEPCION DE TELEMETRIA
// ======================================================

void *udp_server(void *arg) {
    (void)arg;

    int udp_fd;

    struct sockaddr_in server_addr;
    struct sockaddr_in client_addr;

    socklen_t client_addr_len;

    char buffer[BUFFER_SIZE];

    // Crear socket UDP
    udp_fd = socket(AF_INET, SOCK_DGRAM, 0);

    if (udp_fd < 0) {
        perror("[UDP] Error creando socket");
        return NULL;
    }

    memset(&server_addr, 0, sizeof(server_addr));

    server_addr.sin_family      = AF_INET;
    server_addr.sin_addr.s_addr = INADDR_ANY;
    server_addr.sin_port        = htons(g_udp_port);

    // Asociar puerto
    if (bind(
            udp_fd,
            (struct sockaddr *)&server_addr,
            sizeof(server_addr)
        ) < 0) {

        perror("[UDP] Error en bind");
        close(udp_fd);
        return NULL;
    }

    printf("[UDP] Escuchando telemetria en puerto %d\n", g_udp_port);

    while (1) {
        memset(buffer, 0, sizeof(buffer));

        client_addr_len = sizeof(client_addr);

        ssize_t bytes_received = recvfrom(
            udp_fd,
            buffer,
            sizeof(buffer) - 1,
            0,
            (struct sockaddr *)&client_addr,
            &client_addr_len
        );

        if (bytes_received < 0) {
            if (errno == EINTR) {
                continue;
            }

            // Un datagrama defectuoso no puede tumbar el servicio
            perror("[UDP] Error recibiendo datagrama");
            continue;
        }

        buffer[bytes_received] = '\0';

        // Un datagrama = un mensaje: el terminador es opcional
        char *salto = strchr(buffer, '\n');

        if (salto != NULL) {
            *salto = '\0';
        }

        size_t largo = strlen(buffer);

        if (largo > 0 && buffer[largo - 1] == '\r') {
            buffer[largo - 1] = '\0';
        }

        char direccion[64];

        formatear_direccion(&client_addr, direccion, sizeof(direccion));

        printf("[UDP] %s -> %s\n", direccion, buffer);

        // --------------------------------------------------
        // Procesamiento TSP: registro de la medicion,
        // deteccion de anomalias y generacion de alertas
        // --------------------------------------------------

        char respuesta[TSP_MAX_MESSAGE];

        size_t n = handlers_process_udp(
            buffer,
            direccion,
            respuesta,
            sizeof(respuesta)
        );

        if (n > 0) {
            if (sendto(
                    udp_fd,
                    respuesta,
                    n,
                    0,
                    (struct sockaddr *)&client_addr,
                    client_addr_len
                ) < 0) {

                perror("[UDP] Error enviando respuesta");
            }
        }
    }

    close(udp_fd);

    return NULL;
}

// ======================================================
// MAIN - SERVIDOR TCP
// ======================================================

int main(void) {
    int server_fd;

    struct sockaddr_in server_addr;
    struct sockaddr_in client_addr;

    socklen_t client_addr_len;

    // --------------------------------------------------
    // Si un operador desaparece a mitad de un envio, el
    // sistema manda SIGPIPE y el proceso moriria. Se ignora
    // para que send() devuelva EPIPE y podamos manejarlo.
    // --------------------------------------------------

    signal(SIGPIPE, SIG_IGN);

    setvbuf(stdout, NULL, _IOLBF, 0);

    g_tcp_port = puerto_desde_entorno("TSP_TCP_PORT", TCP_PORT_DEFECTO);
    g_udp_port = puerto_desde_entorno("TSP_UDP_PORT", UDP_PORT_DEFECTO);

    // --------------------------------------------------
    // Estado del servidor central y vigilancia de nodos
    // --------------------------------------------------

    registry_init(g_udp_port, g_tcp_port);

    if (registry_start_monitor() != 0) {
        fprintf(stderr, "[SERVIDOR] No se pudo iniciar el monitor de nodos\n");
        return 1;
    }

    // --------------------------------------------------
    // Crear hilo UDP
    // --------------------------------------------------

    pthread_t udp_thread;

    if (pthread_create(
            &udp_thread,
            NULL,
            udp_server,
            NULL
        ) != 0) {

        perror("Error creando hilo UDP");
        return 1;
    }

    pthread_detach(udp_thread);

    // --------------------------------------------------
    // Crear socket TCP
    // --------------------------------------------------

    server_fd = socket(AF_INET, SOCK_STREAM, 0);

    if (server_fd < 0) {
        perror("[TCP] Error creando socket");
        return 1;
    }

    printf("[TCP] Socket creado correctamente\n");

    // Permitir reutilizar puerto
    int option = 1;

    if (setsockopt(
            server_fd,
            SOL_SOCKET,
            SO_REUSEADDR,
            &option,
            sizeof(option)
        ) < 0) {

        perror("[TCP] Error configurando SO_REUSEADDR");
        close(server_fd);
        return 1;
    }

    memset(&server_addr, 0, sizeof(server_addr));

    server_addr.sin_family      = AF_INET;
    server_addr.sin_addr.s_addr = INADDR_ANY;
    server_addr.sin_port        = htons(g_tcp_port);

    // Bind TCP
    if (bind(
            server_fd,
            (struct sockaddr *)&server_addr,
            sizeof(server_addr)
        ) < 0) {

        perror("[TCP] Error en bind");
        close(server_fd);
        return 1;
    }

    // Escuchar conexiones
    if (listen(server_fd, 10) < 0) {
        perror("[TCP] Error en listen");
        close(server_fd);
        return 1;
    }

    printf("[TCP] Escuchando operadores en puerto %d\n", g_tcp_port);
    printf("[SERVIDOR] Protocolo %s\n", TSP_VERSION);
    printf("[SERVIDOR] TCP y UDP funcionando simultaneamente\n");
    printf("[SERVIDOR] Esperando conexiones y telemetria...\n");

    // --------------------------------------------------
    // Aceptar clientes TCP
    // --------------------------------------------------

    while (1) {
        client_addr_len = sizeof(client_addr);

        int client_fd = accept(
            server_fd,
            (struct sockaddr *)&client_addr,
            &client_addr_len
        );

        if (client_fd < 0) {
            if (errno == EINTR) {
                continue;
            }

            perror("[TCP] Error en accept");
            continue;
        }

        tcp_client_arg_t *info = malloc(sizeof(tcp_client_arg_t));

        if (info == NULL) {
            perror("[TCP] Error reservando memoria");
            close(client_fd);
            continue;
        }

        info->fd = client_fd;

        formatear_direccion(&client_addr, info->direccion, sizeof(info->direccion));

        printf("\n[TCP] Nueva conexion desde %s\n", info->direccion);

        pthread_t client_thread;

        if (pthread_create(
                &client_thread,
                NULL,
                handle_tcp_client,
                info
            ) != 0) {

            perror("[TCP] Error creando hilo");
            close(client_fd);
            free(info);
            continue;
        }

        pthread_detach(client_thread);

        printf("[TCP] Cliente asignado a hilo independiente\n");
    }

    close(server_fd);

    return 0;
}
