# Backend service
Backend for the school project

MQTT-Broker/Backend Server: **192.168.1.11:1883** <br>
Station 1 - xxxxxxxxxxxxxx: **192.168.1.21**<br>
Station 2 - xxxxxxxxxxxxxx: **192.168.1.22**<br>
Station 3 - xxxxxxxxxxxxxx: **192.168.1.23**<br>
Station 4 - xxxxxxxxxxxxxx: **192.168.1.24**<br>
Station 5 - xxxxxxxxxxxxxx: **192.168.1.25**<br>

Dashboard: Grafana<br>
Database: PostgreSQL (Time series database for grafana)<br>
Backend Service: Python (handles events & database handling)<br>
MQTT-broker: mosquitto


```mermaid
flowchart TD
    %% Styling Definitionen
    classDef station fill:#1168bd,stroke:#0b4884,stroke-width:2px,color:#fff,rx:5px,ry:5px;
    classDef broker fill:#8c1b48,stroke:#5c102f,stroke-width:2px,color:#fff,rx:5px,ry:5px;
    classDef backend fill:#f6d04d,stroke:#3776ab,stroke-width:2px,color:#000,rx:5px,ry:5px;
    classDef database fill:#336791,stroke:#20405b,stroke-width:2px,color:#fff,rx:5px,ry:5px;
    classDef dashboard fill:#f47f20,stroke:#d16512,stroke-width:2px,color:#fff,rx:5px,ry:5px;
    classDef user fill:#2e3440,stroke:#d8dee9,stroke-width:2px,color:#fff,rx:20px,ry:20px;

    %% Externe Clients / Stationen
    subgraph Edge [Stationen - Raspberry PIs]
        direction LR
        S1["Station 1: <br/>192.168.1.21"]:::station
        S2["Station 2: <br/>192.168.1.22"]:::station
        S3["Station 3: <br/>192.168.1.23"]:::station
        S4["Station 4: <br/>192.168.1.24"]:::station
        S5["Station 5: <br/>192.168.1.25"]:::station
    end

    %% Zentraler Server
    subgraph Server [Backend Server Pi - 192.168.1.11]
        direction TB
        MQTT{"Mosquitto Broker<br/>Port: 1883"}:::broker
        PY(("Python Backend<br/>Event & DB Handler")):::backend
        DB[("PostgreSQL<br/>(Time-Series DB)")]:::database
        GF["Grafana<br/>Dashboard"]:::dashboard
    end

    Client(("Benutzer / Admin<br/>(Browser)")):::user

    %% Verbindungen (Exakte ursprüngliche Struktur)
    S1 & S2 & S3 & S4 & S5 -- "MQTT Publish (Status)
    Subscribe (commands)" --> MQTT
    MQTT <-- "MQTT Subscribe /<br/>Routing-Anweisungen" --> PY
    PY -- "SQL (INSERT / UPDATE)" --> DB
    GF -- "SQL (SELECT)" --> DB
    Client -- "HTTP (Port 3000)" --> GF
```


# grafana

## datasource setup
- Grafana website -> http://localhost:3000/ <br>
- Connections -> Add new Datasource <br>
```
Host URL:   'postgres:5432'
DB name:    'stations'
Username:   'stationuser'
Password:   'changeme'
TLS/SSL:     disable
```
<br>
After that import the test dashboard (or any other from us) <br>
(you may have to click on every panel and click 'run query' once for it to show default data) <br>



# Flowchart for one Station

```mermaid  
flowchart TD
    A["L&R Login"] --> B["station/x/login<br/>{ Tag_UID: '1A 2B 3C 4D' }"]

    B --> C{"Login möglich?<br/>Station online<br/>AND state = free<br/>AND groupId = null"}

    C -->|Nein| D["Login abgelehnt"]
    C -->|Ja| E["Backend legt Zuordnung fest<br/>stationId = x<br/>userId = 1<br/>state = waiting<br/>groupId = 1"]

    E --> F["station/x/status<br/>{<br/>stationId: 'x',<br/>state: 'waiting',<br/>groupId: '1'<br/>}"]

    F --> G["Nutzer startet Spiel"]
    G --> H["station/x/start<br/>{ groupId: '1' }"]

    H --> I{"Start möglich?<br/>state = waiting"}

    I -->|Nein| J["Start abgelehnt"]
    I -->|Ja| K["Status wird auf playing gesetzt"]

    K --> L["station/x/status<br/>{<br/>stationId: 'x',<br/>state: 'playing',<br/>groupId: '1'<br/>}"]

    L --> M["L&R weiß:<br/>Station x läuft mit User/Gruppe 1"]

    M --> N["Spiel wird beendet"]
    N --> O["station/x/complete<br/>{ groupId: '1' }"]

    O --> P["Backend setzt Status auf completed"]

    P --> Q["station/x/status<br/>{<br/>stationId: 'x',<br/>state: 'completed',<br/>groupId: '1'<br/>}"]

    Q --> R["L&R zeigt Review an"]
    R --> S["Gruppe gibt Bewertung ab"]

    S --> T["station/x/review<br/>{<br/>groupId: '1',<br/>rating: 0<br/>}"]

    T --> U["Backend speichert Review in DB"]
    U --> V["Backend setzt Station auf free"]

    V --> W["station/x/status<br/>{<br/>stationId: 'x',<br/>state: 'free',<br/>groupId: null<br/>}"]

    W --> X["Station wieder verfügbar"]

    style F fill:#fff3cd
    style L fill:#cfe2ff
    style Q fill:#d1e7dd
    style W fill:#d1e7dd

    style D fill:#f8d7da
    style J fill:#f8d7da

```
