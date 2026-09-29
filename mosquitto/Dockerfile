FROM eclipse-mosquitto:2

COPY config /mosquitto/config

USER root

# 1. Windows-Zeilenumbrüche (CRLF) in Linux-Zeilenumbrüche (LF) umwandeln
RUN sed -i 's/\r$//' /mosquitto/config/mosquitto.conf && \
    sed -i 's/\r$//' /mosquitto/config/mosquitto.acl

# 2. Alte passwd-Datei löschen und hart im Image neu generieren
RUN rm -f /mosquitto/config/passwd && \
    mosquitto_passwd -c -b /mosquitto/config/passwd backend testen123 && \
    mosquitto_passwd -b /mosquitto/config/passwd station_2 testen123 && \
    mosquitto_passwd -b /mosquitto/config/passwd station_3 testen123 && \
    mosquitto_passwd -b /mosquitto/config/passwd station_4 testen123 && \
    mosquitto_passwd -b /mosquitto/config/passwd station_5 testen123 && \
    mosquitto_passwd -b /mosquitto/config/passwd station_6 testen123 && \
    chown -R mosquitto:mosquitto /mosquitto/config && \
    chmod 0700 /mosquitto/config/passwd && \
    chmod 0700 /mosquitto/config/mosquitto.acl

USER mosquitto