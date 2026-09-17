#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <arpa/inet.h>
#include <sys/socket.h>

#define UDP_PORT 5000
#define BUFFER_SIZE 1024

int main(void) {
    int server_fd;

    struct sockaddr_in server_addr;
    struct sockaddr_in client_addr;

    socklen_t client_addr_len;
    char buffer[BUFFER_SIZE];

    // 1. Crear socket UDP
    server_fd = socket(AF_INET, SOCK_DGRAM, 0);

    if (server_fd < 0) {
        perror("Error creando socket UDP");
        return 1;
    }

    printf("[UDP] Socket creado correctamente\n");

    // 2. Configurar direccion del servidor
    memset(&server_addr, 0, sizeof(server_addr));

    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = INADDR_ANY;
    server_addr.sin_port = htons(UDP_PORT);

    // 3. Asociar el socket al puerto
    if (bind(
            server_fd,
            (struct sockaddr *)&server_addr,
            sizeof(server_addr)
        ) < 0) {

        perror("Error en bind");
        close(server_fd);
        return 1;
    }

    printf("[UDP] Servidor escuchando en el puerto %d\n", UDP_PORT);
    printf("[UDP] Esperando datagramas...\n");

    // 4. Mantener el servidor activo
    while (1) {
        memset(buffer, 0, sizeof(buffer));

        client_addr_len = sizeof(client_addr);

        // Recibir datagrama
        ssize_t bytes_received = recvfrom(
            server_fd,
            buffer,
            sizeof(buffer) - 1,
            0,
            (struct sockaddr *)&client_addr,
            &client_addr_len
        );

        if (bytes_received < 0) {
            perror("Error recibiendo datagrama");
            continue;
        }

        // Asegurar que el mensaje termine correctamente
        buffer[bytes_received] = '\0';

        printf("\n[UDP] Datagrama recibido desde %s:%d\n",
               inet_ntoa(client_addr.sin_addr),
               ntohs(client_addr.sin_port));

        printf("[UDP] Mensaje recibido: %s\n", buffer);

        // 5. Responder al cliente
        const char *response = "Datagrama recibido correctamente";

        ssize_t bytes_sent = sendto(
            server_fd,
            response,
            strlen(response),
            0,
            (struct sockaddr *)&client_addr,
            client_addr_len
        );

        if (bytes_sent < 0) {
            perror("Error enviando respuesta");
            continue;
        }

        printf("[UDP] Respuesta enviada correctamente\n");
    }

    // En condiciones normales no se alcanza porque el servidor queda activo.
    close(server_fd);

    return 0;
}