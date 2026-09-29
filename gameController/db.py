from contextlib import closing, contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

import config


STATE_COLUMNS = 'station_id, team_id, status, updated_at'


def init_db():
    """Add missing state rows for database-managed stations, preserving their catalog."""
    try:
        with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
            with conn, conn.cursor() as cur:
                cur.execute('SELECT started_at, completed_at FROM results LIMIT 0')
                cur.execute('SELECT status FROM station_state LIMIT 0')
                cur.execute('SELECT station_id, team_name, time FROM high_score LIMIT 0')
                cur.execute('SELECT "round" FROM station_events LIMIT 0')
                cur.execute('SELECT id, name FROM team LIMIT 0')
                cur.execute('SELECT station_id, name, routing_order FROM station LIMIT 0')
                cur.execute(
                    "INSERT INTO station_state (station_id) SELECT station_id FROM station "
                    "ON CONFLICT (station_id) DO NOTHING"
                )
        print("[DB] PostgreSQL ready. Existing station states preserved.", flush=True)
        return True
    except psycopg2.Error as exc:
        print(f"[DB ERROR] Initialization failed. Apply Alembic migrations first: {exc}", flush=True)
        return False


def get_station_ids(cur=None):
    """Read valid station IDs in routing order, optionally within a game transaction."""
    if cur is None:
        with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
                return get_station_ids(cursor)
    cur.execute("SELECT station_id FROM station ORDER BY routing_order, station_id")
    return [row["station_id"] for row in cur.fetchall()]


def get_team_name(chip_id):
    """Resolve team.id (scanned chip) to team.name, used by all game records."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT name FROM team WHERE id = %s", (chip_id,))
            row = cur.fetchone()
            return row[0] if row else None


def get_station_state(station_id):
    """Read the current committed state; no local state cache is used."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT {STATE_COLUMNS} FROM station_state WHERE station_id = %s", (station_id,))
            return cur.fetchone()


def get_station_states(status, station_ids):
    """Find stations in a given state, such as reviews awaiting a handoff on reconnect."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {STATE_COLUMNS} FROM station_state "
                "WHERE status = %s AND station_id = ANY(%s) ORDER BY station_id",
                (status, station_ids),
            )
            return cur.fetchall()


def get_routing_snapshot(team_id):
    """Read station occupancy and this team's results from one database snapshot."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        conn.set_session(isolation_level="REPEATABLE READ", readonly=True)
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT name FROM team WHERE name = %s", (team_id,))
            if cur.fetchone() is None:
                return None
            cur.execute(
                """SELECT s.station_id, ss.status, ss.team_id,
                          r.status AS result_status, r.completed_at
                   FROM station AS s
                   LEFT JOIN station_state AS ss ON ss.station_id = s.station_id
                   LEFT JOIN results AS r ON r.station_id = s.station_id
                       AND r.team_id = %s
                   ORDER BY s.routing_order, s.station_id""",
                (team_id,),
            )
            stations = cur.fetchall()
            return {"stations": stations, "last_event": get_latest_team_event(cur, team_id)}


@contextmanager
def station_transaction(station_id):
    """Hold the row lock while gameLogic checks and writes a transition.

    Commit only after the caller leaves this block successfully. Any exception
    rolls back all writes; concurrent station requests wait for the row lock.
    """
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {STATE_COLUMNS} FROM station_state WHERE station_id = %s FOR UPDATE",
                (station_id,),
            )
            yield cur, cur.fetchone()


def lock_team(cur, team_id):
    """Serialize a team's transitions and final reset across stations."""
    cur.execute("SELECT 1 FROM team WHERE name = %s FOR UPDATE", (team_id,))
    return cur.fetchone() is not None


def get_team_station(cur, team_id):
    """Find an existing assignment after locking the team, including pending handoffs."""
    # Read without locking other station rows: their transactions may be waiting
    # for our team lock. The team lock already serializes assignment changes.
    cur.execute(
        "SELECT station_id FROM station_state WHERE team_id = %s ORDER BY station_id LIMIT 1",
        (team_id,),
    )
    row = cur.fetchone()
    return row["station_id"] if row else None


def get_latest_team_event(cur, team_id):
    """Read event-only game numbering; live tables have no round column."""
    cur.execute(
        'SELECT "round", event_type FROM station_events WHERE team_id = %s '
        'ORDER BY "round" DESC, id DESC LIMIT 1', (team_id,),
    )
    return cur.fetchone()


def get_reviewed_stations(cur, team_id):
    """Read the team's reviewed stations in its current, resettable results."""
    cur.execute(
        "SELECT station_id FROM results WHERE team_id = %s "
        "AND status = 'review' AND completed_at IS NOT NULL", (team_id,),
    )
    return {row["station_id"] for row in cur.fetchall()}


def clear_team_results(cur, team_id):
    """Restore an unplayed team: no result rows; event history is untouched."""
    cur.execute("DELETE FROM results WHERE team_id = %s", (team_id,))


def save_high_score(cur, station_id, team_id, duration):
    """Atomically keep the fastest duration; an equal time keeps the first winner."""
    cur.execute(
        """INSERT INTO high_score (station_id, team_name, time) VALUES (%s, %s, %s)
           ON CONFLICT (station_id) DO UPDATE SET
               team_name = EXCLUDED.team_name, time = EXCLUDED.time
           WHERE high_score.time IS NULL OR EXCLUDED.time < high_score.time""",
        (station_id, team_id, duration),
    )


def get_timestamp(cur):
    """Use the database clock for game timestamps."""
    cur.execute("SELECT clock_timestamp() AS now")
    return cur.fetchone()["now"]


def get_result(cur, team_id, station_id):
    """Read a team's current progress at one station."""
    if cur is None:
        with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
                return get_result(cursor, team_id, station_id)
    cur.execute(
        "SELECT created_at, status, started_at, completed_at, review FROM results "
        "WHERE team_id = %s AND station_id = %s",
        (team_id, station_id),
    )
    return cur.fetchone()


def save_result(cur, team_id, station_id, result):
    """Save the current visit, keyed by team name and station."""
    cur.execute(
        """INSERT INTO results
               (team_id, station_id, created_at, status, started_at, completed_at, review)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (team_id, station_id) DO UPDATE SET
               created_at = EXCLUDED.created_at, status = EXCLUDED.status,
               started_at = EXCLUDED.started_at, completed_at = EXCLUDED.completed_at,
               review = EXCLUDED.review""",
        (team_id, station_id, result["created_at"], result["status"],
         result["started_at"], result["completed_at"], result["review"]),
    )


def save_station_state(cur, station_id, team_id, status, timestamp):
    """Update the station's current occupancy and return its new state."""
    cur.execute(
        f"""UPDATE station_state SET team_id = %s, status = %s,
               updated_at = %s
               WHERE station_id = %s RETURNING {STATE_COLUMNS}""",
        (team_id, status, timestamp, station_id),
    )
    return cur.fetchone()


def log_event(cur, station_id, team_id, event_type, review_score, timestamp, round_number):
    """Append a transition with its team and round for the dashboard."""
    cur.execute(
        """INSERT INTO station_events (created_at, station_id, team_id, event_type, review_score, "round")
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (timestamp, station_id, team_id, event_type, review_score, round_number),
    )
