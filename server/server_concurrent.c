#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>

#include <arpa/inet.h>
#include <sys/socket.h>

#define TCP_PORT 6000
#define UDP_PORT 5000
#define BUFFER_SIZE 1024

// ======================================================
// HILO PARA CADA CLIENTE TCP
// ======================================================

void *handle_tcp_client(void *arg) {
    int client_fd = *((int *)arg);
    free(arg);

    char buffer[BUFFER_SIZE];

    printf("[TCP-HILO] Cliente listo para enviar mensajes\n");

    while (1) {
        memset(buffer, 0, sizeof(buffer));

        ssize_t bytes_received = recv(
            client_fd,
            buffer,
            sizeof(buffer) - 1,
            0
        );

        if (bytes_received < 0) {
            perror("[TCP-HILO] Error recibiendo mensaje");
            break;
        }

        if (bytes_received == 0) {
            printf("[TCP-HILO] Cliente desconectado\n");
            break;
        }

        buffer[bytes_received] = '\0';

        printf("[TCP-HILO] Mensaje recibido: %s\n", buffer);

        // Comando temporal para cerrar conexion
        if (strcmp(buffer, "EXIT") == 0) {
            const char *response = "Conexion finalizada";

            send(
                client_fd,
                response,
                strlen(response),
                0
            );

            printf("[TCP-HILO] Cliente solicito cerrar conexion\n");
            break;
        }

        // Respuesta temporal
        const char *response =
            "Mensaje recibido por servidor TCP";

        if (send(
                client_fd,
                response,
                strlen(response),
                0
            ) < 0) {

            perror("[TCP-HILO] Error enviando respuesta");
            break;
        }

        printf("[TCP-HILO] Respuesta enviada\n");
    }

    close(client_fd);

    printf("[TCP-HILO] Conexion cerrada\n");

    return NULL;
}

// ======================================================
// HILO UDP
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

    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = INADDR_ANY;
    server_addr.sin_port = htons(UDP_PORT);

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

    printf("[UDP] Escuchando telemetria en puerto %d\n", UDP_PORT);

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
            perror("[UDP] Error recibiendo datagrama");
            continue;
        }

        buffer[bytes_received] = '\0';

        printf(
            "\n[UDP] Datagrama desde %s:%d\n",
            inet_ntoa(client_addr.sin_addr),
            ntohs(client_addr.sin_port)
        );

        printf("[UDP] Telemetria recibida: %s\n", buffer);

        // Respuesta temporal
        const char *response =
            "Datagrama recibido correctamente";

        if (sendto(
                udp_fd,
                response,
                strlen(response),
                0,
                (struct sockaddr *)&client_addr,
                client_addr_len
            ) < 0) {

            perror("[UDP] Error enviando respuesta");
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

    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = INADDR_ANY;
    server_addr.sin_port = htons(TCP_PORT);

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

    printf("[TCP] Escuchando operadores en puerto %d\n", TCP_PORT);
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
            perror("[TCP] Error en accept");
            continue;
        }

        printf(
            "\n[TCP] Nuevo operador conectado desde %s:%d\n",
            inet_ntoa(client_addr.sin_addr),
            ntohs(client_addr.sin_port)
        );

        int *client_ptr = malloc(sizeof(int));

        if (client_ptr == NULL) {
            perror("[TCP] Error reservando memoria");
            close(client_fd);
            continue;
        }

        *client_ptr = client_fd;

        pthread_t client_thread;

        if (pthread_create(
                &client_thread,
                NULL,
                handle_tcp_client,
                client_ptr
            ) != 0) {

            perror("[TCP] Error creando hilo");
            close(client_fd);
            free(client_ptr);
            continue;
        }

        pthread_detach(client_thread);

        printf("[TCP] Operador asignado a hilo independiente\n");
    }

    close(server_fd);

    return 0;
}