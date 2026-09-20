# Despliegue en la nube y DNS (Punto 8)

Guía paso a paso para desplegar la **Plataforma Distribuida de Telemetría** en
una instancia **Ubuntu Server de AWS EC2** usando Docker + Docker Compose, y
para configurar un **nombre DNS** que apunte a la IP pública de la instancia.

> No se modifica ningún código fuente. El sistema ya está contenerizado
> (`server/Dockerfile`, `web/Dockerfile`, `docker-compose.yml`) y localiza los
> servicios internos por **nombre DNS de Compose**, nunca por IP fija. Los
> clientes externos localizan el servidor por el **nombre DNS público** que se
> configura en este documento.

---

## 0. Puertos del sistema

Estos son los tres puertos que deben quedar accesibles desde Internet. El
script `setup_ec2.sh` y las reglas del Grupo de Seguridad se basan en ellos.

| Puerto     | Protocolo | Servicio          | Uso                                        |
|------------|-----------|-------------------|--------------------------------------------|
| `6000/tcp` | TCP       | Servidor_Central  | `REGISTER`, consultas y comandos, alertas  |
| `5000/udp` | UDP       | Servidor_Central  | Telemetría (`TELEMETRY` / `ACK`)           |
| `8080/tcp` | TCP       | Servicio_Web      | Interfaz web HTTP                          |
| `22/tcp`   | TCP       | SSH               | Acceso remoto de administración            |

---

## 1. Crear la instancia EC2

1. Consola de AWS → **EC2** → **Launch instance**.
2. **Nombre**: `telemetria-servidor` (o el que prefieras).
3. **AMI**: *Ubuntu Server 24.04 LTS* (x86_64). También sirve 22.04 LTS.
4. **Tipo de instancia**: `t3.micro` o `t2.micro` es suficiente para la
   demostración (elegible para capa gratuita).
5. **Par de claves (key pair)**: crea o selecciona uno; descarga el `.pem`.
   Es lo que usarás para entrar por SSH.
6. **Almacenamiento**: 8–10 GB gp3 basta.
7. **Configuración de red / Grupo de seguridad**: ver la sección 2.
8. Lanza la instancia y anota su **IPv4 pública** y su **DNS público**
   (algo como `ec2-3-91-x-x.compute-1.amazonaws.com`).

> **IP pública dinámica vs. Elastic IP.** La IP pública por defecto **cambia**
> cada vez que la instancia se detiene y se vuelve a iniciar. Para un registro
> DNS estable, asigna una **Elastic IP** (EC2 → *Elastic IPs* → *Allocate* →
> *Associate* a la instancia). La Elastic IP es la que apuntarás desde el DNS.

---

## 2. Reglas de acceso (Grupo de Seguridad)

El **Grupo de Seguridad** es el firewall a nivel de AWS (control de tráfico
*inbound/outbound* para la instancia). Debe permitir tráfico de entrada a los
cuatro puertos. Se puede configurar en la consola o con AWS CLI.

### Opción A — Consola de AWS

En el Grupo de Seguridad de la instancia, añade estas reglas **inbound**:

| Tipo         | Protocolo | Rango de puertos | Origen        | Descripción            |
|--------------|-----------|------------------|---------------|------------------------|
| Custom TCP   | TCP       | `6000`           | `0.0.0.0/0`   | TSP registro/comandos  |
| Custom UDP   | UDP       | `5000`           | `0.0.0.0/0`   | TSP telemetría         |
| Custom TCP   | TCP       | `8080`           | `0.0.0.0/0`   | Servicio_Web HTTP      |
| SSH          | TCP       | `22`             | *tu IP/32*    | Administración         |

> **Buena práctica de seguridad.** Restringe `22/tcp` a tu propia IP
> (`x.x.x.x/32`) en lugar de `0.0.0.0/0`. Los puertos del servicio
> (`6000`, `5000`, `8080`) sí necesitan `0.0.0.0/0` para que la práctica sea
> accesible desde Internet, como exige el enunciado.

### Opción B — AWS CLI

```bash
# Reemplaza sg-xxxxxxxx por el ID de tu Grupo de Seguridad
aws ec2 authorize-security-group-ingress --group-id sg-xxxxxxxx \
  --ip-permissions \
  'IpProtocol=tcp,FromPort=6000,ToPort=6000,IpRanges=[{CidrIp=0.0.0.0/0,Description=TSP-TCP}]' \
  'IpProtocol=udp,FromPort=5000,ToPort=5000,IpRanges=[{CidrIp=0.0.0.0/0,Description=TSP-UDP}]' \
  'IpProtocol=tcp,FromPort=8080,ToPort=8080,IpRanges=[{CidrIp=0.0.0.0/0,Description=Web-HTTP}]'
```

> **Doble capa de firewall.** El Grupo de Seguridad de AWS y el firewall del
> sistema operativo (UFW) son independientes. El tráfico debe pasar **ambos**.
> El script `setup_ec2.sh` configura UFW dentro de la instancia; el Grupo de
> Seguridad se configura aquí, en el plano de AWS. Si un puerto falla, revisa
> los dos.

---

## 3. Acceso remoto por SSH

Desde tu equipo, con el `.pem` descargado:

```bash
chmod 400 telemetria-key.pem
ssh -i telemetria-key.pem ubuntu@<IP_O_DNS_PUBLICO>
```

El usuario por defecto de las AMI de Ubuntu es `ubuntu`.

---

## 4. Desplegar con el script `setup_ec2.sh`

Una vez dentro de la instancia, clona el repositorio y ejecuta el script de
aprovisionamiento incluido en la raíz del proyecto:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone <URL_DEL_REPOSITORIO_PRIVADO> telemetria
cd telemetria
chmod +x setup_ec2.sh
./setup_ec2.sh
```

El script `setup_ec2.sh`:

1. Instala Docker Engine y el complemento Docker Compose (repositorio oficial
   de Docker).
2. Habilita y arranca el servicio `docker`.
3. Añade el usuario `ubuntu` al grupo `docker` (uso sin `sudo`).
4. Configura el firewall **UFW** abriendo `22/tcp`, `6000/tcp`, `5000/udp`
   y `8080/tcp`.
5. Construye y levanta `docker compose up --build -d` desde la raíz del repo.
6. Muestra el estado de los contenedores y un resumen de verificación.

> El script es **idempotente**: se puede volver a ejecutar sin romper nada. Si
> Docker ya está instalado, no lo reinstala; si UFW ya tiene las reglas, no las
> duplica.

### Aplicar el grupo `docker` sin cerrar sesión

Tras la primera ejecución, para usar `docker` sin `sudo` en la sesión actual:

```bash
newgrp docker      # o cierra sesión y vuelve a entrar por SSH
```

### Gestión posterior

```bash
docker compose ps          # estado de los servicios
docker compose logs -f     # logs en vivo
docker compose down        # detener
docker compose up --build -d   # redeploy tras un git pull
```

---

## 5. Configuración del DNS

El enunciado exige que **el código no contenga IPs públicas fijas** y que los
clientes localicen el servidor por **nombre DNS**. Esta sección explica cómo
lograrlo.

### 5.1. Concepto

El **DNS (Domain Name System)** traduce nombres legibles
(`telemetria.midominio.com`) a direcciones IP (`3.91.x.x`). Al publicar el
servidor bajo un nombre, los nodos y operadores usan ese nombre y no necesitan
conocer la IP; si la IP cambia, basta actualizar el registro DNS sin tocar el
código ni los clientes.

La resolución la hace el sistema operativo del cliente: cuando
`telemetry_node.py` u `operator_cli.py` llaman a `socket.getaddrinfo(host, ...)`,
el resolver del SO consulta la jerarquía DNS y obtiene la IP a la que conectarse.

### 5.2. Tipos de registro relevantes

| Registro | Qué hace                                  | Cuándo usarlo                                       |
|----------|-------------------------------------------|-----------------------------------------------------|
| **A**    | Nombre → dirección **IPv4**               | Apuntar el nombre a la **Elastic IP** de EC2        |
| **AAAA** | Nombre → dirección **IPv6**               | Solo si la instancia tiene IPv6 y quieres soportarlo|
| **CNAME**| Nombre → **otro nombre**                  | Apuntar a la DNS pública de EC2 (que ya resuelve)   |

Dos formas equivalentes de publicar el servicio:

- **Registro A → Elastic IP (recomendado).** Es estable y directo. La Elastic
  IP no cambia mientras esté asociada a la instancia.

  ```
  telemetria.midominio.com.   A   300   3.91.10.20
  ```

- **Registro CNAME → DNS público de EC2.** El nombre de tu dominio apunta al
  nombre DNS que AWS ya asigna a la instancia. Evita hardcodear la IP, pero
  ese nombre de EC2 también cambia si la IP pública cambia (salvo con
  Elastic IP).

  ```
  telemetria.midominio.com.   CNAME   300   ec2-3-91-10-20.compute-1.amazonaws.com.
  ```

> El **TTL** (p. ej. 300 s) indica cuánto puede cachear el registro un
> resolver. Un TTL bajo hace que un cambio de IP se propague rápido; uno alto
> reduce consultas. Para la práctica, 300 s es un buen equilibrio.

### 5.3. Dónde crear el registro

Se configura en el panel del proveedor DNS donde administres la zona del
dominio. Opciones típicas:

- **Amazon Route 53** (dentro de AWS): crea una *Hosted Zone* para tu dominio
  y un *record set* tipo **A** apuntando a la Elastic IP. Es lo más coherente
  si todo está en AWS.
- **Proveedor del dominio** (Namecheap, GoDaddy, Cloudflare, No-IP, DuckDNS,
  etc.): entra a la gestión de DNS del dominio y crea el registro A o CNAME.

Para una demostración sin comprar dominio, un servicio de **DNS dinámico
gratuito** (DuckDNS, No-IP) da un nombre como `telemetria.duckdns.org` que
puedes apuntar a la Elastic IP: cumple igual el requisito de localizar por
nombre DNS.

### 5.4. Verificar la resolución

Desde cualquier equipo, comprueba que el nombre resuelve a la IP esperada:

```bash
nslookup telemetria.midominio.com
# o
dig +short telemetria.midominio.com
```

Debe devolver la IP pública / Elastic IP de la instancia. Si no, espera a que
propague (según el TTL) y revisa que el registro esté bien creado.

### 5.5. Usar el nombre DNS en los clientes

Con el DNS configurado, los clientes se lanzan **sin ninguna IP**, solo con el
nombre — que es exactamente lo que pide el Punto 8:

```bash
# Variable de entorno para no repetir el host en cada comando
export TSP_SERVER_HOST=telemetria.midominio.com

# Nodos de telemetría (5 o más), localizando el servidor por DNS
python3 clients/run_nodes.py --count 5 --host telemetria.midominio.com

# Cliente operador
python3 clients/operator_cli.py --host telemetria.midominio.com

# Servicio Web en el navegador
# http://telemetria.midominio.com:8080/
```

---

## 6. Verificación desde un equipo externo

La prueba debe hacerse **desde fuera de la instancia** (no `localhost`), contra
el **nombre DNS público**, para demostrar accesibilidad real por Internet.

```bash
# 1. El DNS resuelve a la IP de EC2
dig +short telemetria.midominio.com

# 2. TCP 6000 — un comando TSP recibe respuesta
#    (escribe LIST_NODES y luego BYE dentro de nc)
nc telemetria.midominio.com 6000

# 3. UDP 5000 — un nodo real envía telemetría y recibe ACK
python3 clients/telemetry_node.py --id NODO01 --host telemetria.midominio.com

# 4. HTTP 8080 — el Servicio_Web responde
curl http://telemetria.midominio.com:8080/
```

Si los cuatro pasos responden, el sistema está desplegado en la nube,
accesible por Internet y localizable por DNS. Esto cubre los requisitos del
Punto 8 (instancia de cómputo, puertos y reglas de acceso, DNS, acceso remoto
y conectividad desde equipos externos).

---

## 7. Solución de problemas

| Síntoma                                    | Causa probable y solución                                                                 |
|--------------------------------------------|-------------------------------------------------------------------------------------------|
| `nc`/`curl` se queda colgado sin responder | Falta la regla en el **Grupo de Seguridad** de AWS, o UFW no abrió el puerto.             |
| El puerto UDP 5000 no llega                | Verifica que la regla del Grupo de Seguridad sea **UDP**, no TCP, y que UFW abra `5000/udp`. |
| `docker: permission denied`                | Ejecuta `newgrp docker` o reconéctate por SSH para aplicar el grupo `docker`.             |
| El nombre DNS no resuelve                   | El registro aún propaga (espera el TTL) o apunta a una IP incorrecta. Revisa con `dig`.   |
| Tras reiniciar la instancia cambió la IP    | No asignaste **Elastic IP**. Asígnala y actualiza el registro A.                          |
| `docker compose` no existe                  | Usa el complemento moderno (`docker compose`, sin guion), que el script ya instala.       |
```

