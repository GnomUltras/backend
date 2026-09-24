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


## MQTT integration guide for station groups

This section describes the protocol implemented by [gameController/gameLogic.py](gameController/gameLogic.py),
the [broker permissions](mosquitto/config/mosquitto.acl), and the separate
[server-time service](mqtt-test/servertime/servertime.py). All examples use station 1.
Replace `station01` with your group's assigned station ID everywhere, including the MQTT username.

### 1. Connect to the broker

| Setting | Value |
| --- | --- |
| Broker on the server Pi | `192.168.1.11` |
| Broker on your own computer, including local Docker | `localhost` |
| Port / transport | `1883`, MQTT over TCP, without TLS |
| MQTT version used by the example clients | MQTT 3.1.1 |
| Username | Your station ID: `station01`, `station02`, ..., `station05` |
| Password in the supplied broker image | `testen123` |
| Client ID | A unique ID for each connected client, e.g. `station01-game` |
| Publish / subscribe QoS | Use `1` |
| Retain flag | Always publish requests with `retain=false` |

`localhost` means the machine running your client. A station Pi connecting to the
server Pi must use `192.168.1.11`, even if the station software itself runs locally.
The Docker service name `mosquitto` works inside the backend's Compose network.
The Compose stack exposes port 1883; its configured WebSocket listener on 9001 is
not published to other machines by the current Compose file.

The username determines topic permissions. For example, `station02` can publish
actions for `station/station02/...` and read its own replies. Use the exact spelling:
`station01`, not `station1`, `1`, or `station-01`. Stations do not need the `backend`
account or a subscription to `station/#`.

### 2. Topic reference

`<station_id>` below is a placeholder, for example `station01`. Topic names are case-sensitive.
Action requests are UTF-8 plain text. Do not wrap an NFC UUID in JSON or send a team name.

| Topic | What the station does | Request payload example | Where the reply arrives |
| --- | --- | --- | --- |
| `station/<station_id>/login` | Publish to register a team at the station | `AA BB CC 01` | `station/<station_id>/status` |
| `station/<station_id>/start` | Publish when that team's game starts | `AA BB CC 01` | `station/<station_id>/status` |
| `station/<station_id>/complete` | Publish when that team's game finishes | `AA BB CC 01` | `station/<station_id>/status` |
| `station/<station_id>/review` | Publish the team's review score after completion | `AA BB CC 01;2` | `station/<station_id>/status` |
| `station/<station_id>/status` | Subscribe for action replies; publish `1` to query current state | `1` | Same topic, as JSON |
| `station/<station_id>/servertime` | Subscribe for time replies; publish a JSON time request | `{"request":"GET"}` | Same topic, as JSON |

Stations have publish permission on the four action topics, and publish/subscribe
permission on their own `status` and `servertime` topics. There are no replies on
the action topics themselves.

### 3. Game actions and their required order

Each station has its own state. A newly started controller initializes all stations
to `idle`. Only the next action shown below is accepted:

```mermaid
stateDiagram-v2
    [*] --> idle
    idle --> login: login + NFC UUID
    login --> start: start + NFC UUID
    start --> complete: complete + NFC UUID
    complete --> review: review + NFC UUID;score
    review --> login: login + next team's NFC UUID
```

| Publish action | Allowed current state | Meaning and payload |
| --- | --- | --- |
| `login` | `idle` or `review` | Send the scanned NFC UUID to register the team. The controller resolves the team name. |
| `start` | `login` | Send an NFC UUID belonging to the logged-in team when your station starts its game. |
| `complete` | `start` | Send an NFC UUID belonging to the same team when the game finishes. |
| `review` | `complete` | Send `<NFC UUID>;<score>`, e.g. `AA BB CC 01;2`. The score must be exactly `0`, `1`, or `2`. |

The protocol defines the numeric review values but does not assign them UI labels.
Agree on the meaning of 0, 1, and 2 with the project team. The score is saved in the
database; it is not included in the MQTT status reply.

After a successful review, the state remains `review` with the previous team's ID
until the next login. There is no automatic return to `idle`, logout topic, cancel
topic, or next-station command in the current game controller.

NFC UUIDs must match entries in [gameController/config.py](gameController/config.py)
under `NFC_TEAMS`. The current test mappings are:

| NFC UUID sent by the station | Team ID returned by the controller |
| --- | --- |
| `AA BB CC 01` | `Team-01` |
| `AA BB CC 02` | `Team-02` |
| `AA BB CC 03` | `Team-03` |
| `AA BB CC 04` | `Team-04` |
| `AA BB CC 05` | `Team-05` |

These are example chip IDs. Give your real NFC UUIDs to the backend group so they
can configure the mapping. Matching is case-sensitive and internal spaces matter;
the controller only removes surrounding whitespace. A station number and a team
number are independent: any configured team can log in at any available station.

### 4. Status replies and read-only queries

Subscribe to `station/<station_id>/status` **before publishing an action**. Wait for
the broker's subscription acknowledgement (SUBACK), then send the request. After
accepting an action and saving it in the database, the controller publishes a JSON reply:

```json
{"status":"login","team_id":"Team-01"}
```

| Field | Meaning |
| --- | --- |
| `status` | `idle`, `login`, `start`, `complete`, `review`, or `error` |
| `team_id` | The resolved team name, or JSON `null` if no team is assigned/identified |

The topic identifies the station. The reply has no `station_id`, NFC UUID,
request ID, timestamp, review score, or detailed error message.

To ask for the current state without changing it, publish the single character
`1` to `station/<station_id>/status`. This is plain text, not the JSON string `"1"`
and not `{"request":"GET"}`. For an unused station, the reply is:

```json
{"status":"idle","team_id":null}
```

Because queries and replies use the same topic, your subscription can receive your
own `1` message. Ignore it. Accept only JSON objects with the expected `status` and
`team_id` fields, and ignore retained messages. The controller's status replies use
QoS 1 and `retain=false`; subscribing alone does not request a fresh status.

### 5. Example: one complete station visit

The message flow for a successful login is:

```mermaid
sequenceDiagram
    participant S as Station station01
    participant B as MQTT broker
    participant C as Game controller
    participant D as PostgreSQL

    Note over B,C: Controller is running and subscribed to station/#
    S->>B: SUBSCRIBE station/station01/status (QoS 1)
    B-->>S: SUBACK
    S->>B: PUBLISH station/station01/login: AA BB CC 01
    B->>C: Deliver login request
    C->>C: Check state and resolve NFC UUID
    C->>D: Save login event for Team-01
    D-->>C: Saved successfully
    C->>C: Set station state to login
    C->>B: PUBLISH station/station01/status
    B-->>S: {"status":"login","team_id":"Team-01"}
    Note over S,C: Station can now start the game and send the start action
```

Connect as `station01`, subscribe to `station/station01/status`, and wait for SUBACK.
Then perform these steps, waiting for the matching JSON reply before advancing:

| Step | Publish topic | Exact request payload | Expected JSON reply on `station/station01/status` |
| --- | --- | --- | --- |
| Check initial state | `station/station01/status` | `1` | `{"status":"idle","team_id":null}` on a fresh controller |
| Scan the team's chip | `station/station01/login` | `AA BB CC 01` | `{"status":"login","team_id":"Team-01"}` |
| Start the game | `station/station01/start` | `AA BB CC 01` | `{"status":"start","team_id":"Team-01"}` |
| Finish the game | `station/station01/complete` | `AA BB CC 01` | `{"status":"complete","team_id":"Team-01"}` |
| Submit the review | `station/station01/review` | `AA BB CC 01;2` | `{"status":"review","team_id":"Team-01"}` |

The next team can now send `login`. Run one action at a time for each station:
there are no request IDs to distinguish concurrent requests. Check both the status
and team ID when matching an action reply. An MQTT publish acknowledgement confirms
broker delivery; use the JSON reply to confirm that the controller accepted the action.

### 6. Errors, timeouts, and reconnects

An error reply looks like this:

```json
{"status":"error","team_id":null}
```

A database failure can instead include the resolved team ID. `error` is a reply,
not a stored station state: failed actions leave the previous state unchanged.

| Situation | Current controller behavior | What the station should do |
| --- | --- | --- |
| Unknown NFC UUID during an allowed login | Replies with `error` and `team_id: null` | Check the scanned UUID and backend mapping. |
| Invalid UTF-8 or malformed review/score during the expected action | Replies with `error` and `team_id: null` | Correct the payload format. |
| Database write fails | Replies with `error` and the resolved team ID | Keep the previous local state and contact the backend group if it persists. |
| Wrong action order, or a repeated action that is no longer the expected next action | Silently ignored; no reply | Query `status` to recover the actual state. |
| A different or unmapped team sends `start`, `complete`, or `review` with an otherwise valid payload | Silently ignored; no reply | Use the team that logged in. |
| Invalid station ID/topic, unsupported action, or a message delivered with its retained flag set | Ignored by the controller; permissions may also prevent delivery | Check the topic, credentials, and `retain=false`. |
| Broker is reachable but controller is unavailable | No game status reply | Check controller availability with the backend group. |

Start a reply timeout after sending a request; the provided clients use five seconds.
If no reply arrives, query `status` before deciding whether to retry: the controller
may have accepted the action even if your client missed its reply. Handle duplicate
deliveries without repeating physical game effects.

After reconnecting, subscribe again, wait for SUBACK, and query `status`. Current
station states live only in controller memory. Restarting the controller resets
them to `idle`; database history is not loaded back into the state machine.

### 7. Server time (optional, separate service)

The time topic is handled by [mqtt-test/servertime/servertime.py](mqtt-test/servertime/servertime.py),
not by the game controller. **The current Docker Compose stack does not start this
service.** Ask the backend group to start it if your station needs server time.
On the broker host, with `paho-mqtt` installed and `BROKER_IP` configured in that script:

```sh
python mqtt-test/servertime/servertime.py
```

Subscribe to `station/station01/servertime`, wait for SUBACK, and publish this JSON
object to the same topic with QoS 1 and `retain=false`:

```json
{"request":"GET"}
```

The service replies on that same topic with JSON in this form (example timestamp):

```json
{"request":"POST","server_time":"2026-01-01T00:00:00Z","unix":1767225600}
```

`server_time` is a UTC date/time string; `unix` is seconds since the Unix epoch.
Ignore your echoed `GET` request and only process objects with `request: "POST"`.
Time queries do not change game state and do not produce a reply on `/status`.
This service expects JSON objects, so do not send the plain `1` used by status queries.

### 8. Try the protocol with the supplied clients

The game clients provide working examples of subscribing before publishing,
formatting action payloads, filtering replies, and waiting for a response.
From the repository root, install their dependency:

```sh
python -m pip install paho-mqtt==2.1.0
```

Set `MQTT_HOST` near the top of both [clientStatus.py](gameClient/clientStatus.py)
and [clientLogin.py](gameClient/clientLogin.py) to `"192.168.1.11"` for the server Pi,
or `"localhost"` for a broker on your own machine. Then run:

```sh
# Read current state; enter your station ID when prompted.
python gameClient/clientStatus.py

# Send one action; prompts ask for station ID, action, NFC UUID, and review score if needed.
python gameClient/clientLogin.py
```

Run the action client once per step in the example visit. Its default NFC UUID is
`AA BB CC 01`; use a UUID registered by the backend group for real hardware.
For a time-client example, see [servertimeReq.py](mqtt-test/servertime/servertimeReq.py).

The older [mqtt-test/main.py](mqtt-test/main.py) and [mqtt-test/test_pub.py](mqtt-test/test_pub.py)
use a different JSON action format. Their `backend/timestamp` routing topic and
`next_station` messages are not part of the current game-controller protocol or
station ACL. Use the topics and plain-text action payloads documented above for
new station implementations.

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
