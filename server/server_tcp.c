#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <arpa/inet.h>
#include <sys/socket.h>

#define TCP_PORT 6000
#define BUFFER_SIZE 1024

int main(void) {
    int server_fd;
    int client_fd;

    struct sockaddr_in server_addr;
    struct sockaddr_in client_addr;

    socklen_t client_addr_len;
    char buffer[BUFFER_SIZE];

    // 1. Crear socket TCP
    server_fd = socket(AF_INET, SOCK_STREAM, 0);

    if (server_fd < 0) {
        perror("Error creando socket TCP");
        return 1;
    }

    printf("[TCP] Socket creado correctamente\n");

    // 2. Permitir reutilizar el puerto
    int option = 1;

    if (setsockopt(
            server_fd,
            SOL_SOCKET,
            SO_REUSEADDR,
            &option,
            sizeof(option)
        ) < 0) {

        perror("Error configurando SO_REUSEADDR");
        close(server_fd);
        return 1;
    }

    // 3. Configurar direccion del servidor
    memset(&server_addr, 0, sizeof(server_addr));

    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = INADDR_ANY;
    server_addr.sin_port = htons(TCP_PORT);

    // 4. Asociar socket al puerto
    if (bind(
            server_fd,
            (struct sockaddr *)&server_addr,
            sizeof(server_addr)
        ) < 0) {

        perror("Error en bind");
        close(server_fd);
        return 1;
    }

    printf("[TCP] Servidor asociado al puerto %d\n", TCP_PORT);

    // 5. Escuchar conexiones
    if (listen(server_fd, 10) < 0) {
        perror("Error en listen");
        close(server_fd);
        return 1;
    }

    printf("[TCP] Esperando conexiones...\n");

    // 6. Mantener servidor activo
    while (1) {

        client_addr_len = sizeof(client_addr);

        client_fd = accept(
            server_fd,
            (struct sockaddr *)&client_addr,
            &client_addr_len
        );

        if (client_fd < 0) {
            perror("Error en accept");
            continue;
        }

        printf(
            "\n[TCP] Cliente conectado desde %s:%d\n",
            inet_ntoa(client_addr.sin_addr),
            ntohs(client_addr.sin_port)
        );

        // 7. Recibir mensaje del cliente
        memset(buffer, 0, sizeof(buffer));

        ssize_t bytes_received = recv(
            client_fd,
            buffer,
            sizeof(buffer) - 1,
            0
        );

        if (bytes_received < 0) {
            perror("Error recibiendo mensaje");
            close(client_fd);
            continue;
        }

        if (bytes_received == 0) {
            printf("[TCP] Cliente cerro la conexion\n");
            close(client_fd);
            continue;
        }

        buffer[bytes_received] = '\0';

        printf("[TCP] Mensaje recibido: %s\n", buffer);

        // 8. Responder al cliente
        const char *response = "Mensaje recibido correctamente";

        ssize_t bytes_sent = send(
            client_fd,
            response,
            strlen(response),
            0
        );

        if (bytes_sent < 0) {
            perror("Error enviando respuesta");
        } else {
            printf("[TCP] Respuesta enviada correctamente\n");
        }

        // 9. Cerrar solamente la conexion del cliente
        close(client_fd);

        printf("[TCP] Cliente desconectado\n");
        printf("[TCP] Esperando siguiente cliente...\n");
    }

    // En condiciones normales no se alcanza.
    close(server_fd);

    return 0;
}