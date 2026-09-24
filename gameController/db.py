from contextlib import closing, contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

import config


STATE_COLUMNS = "station_id, team_id, status, review_score, updated_at"


def init_db(team_ids, station_ids):
    """Insert supplied catalog entries and missing state rows after Alembic."""
    try:
        with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
            with conn, conn.cursor() as cur:
                cur.execute("SELECT started_at, completed_at FROM results LIMIT 0")
                for team_id in team_ids:
                    cur.execute(
                        "INSERT INTO team (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                        (team_id, team_id),
                    )
                for station_id in station_ids:
                    cur.execute(
                        "INSERT INTO station (station_id, name) VALUES (%s, %s) "
                        "ON CONFLICT (station_id) DO UPDATE SET name = EXCLUDED.name",
                        (station_id, station_id),
                    )
                    cur.execute(
                        "INSERT INTO station_state (station_id) VALUES (%s) "
                        "ON CONFLICT (station_id) DO NOTHING",
                        (station_id,),
                    )
        print("[DB] PostgreSQL ready. Existing station states preserved.", flush=True)
        return True
    except psycopg2.Error as exc:
        print(f"[DB ERROR] Initialization failed. Apply Alembic migrations first: {exc}", flush=True)
        return False


def get_station_state(station_id):
    """Read the current committed state; no local state cache is used."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT {STATE_COLUMNS} FROM station_state WHERE station_id = %s", (station_id,))
            return cur.fetchone()


def get_station_states(status, station_ids):
    """Read station rows matching the supplied filter."""
    with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {STATE_COLUMNS} FROM station_state "
                "WHERE status = %s AND station_id = ANY(%s) ORDER BY station_id",
                (status, station_ids),
            )
            return cur.fetchall()


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


def team_exists(cur, team_id):
    cur.execute("SELECT 1 FROM team WHERE id = %s", (team_id,))
    return cur.fetchone() is not None


def get_timestamp(cur):
    cur.execute("SELECT clock_timestamp() AS now")
    return cur.fetchone()["now"]


def get_result(cur, team_id, station_id):
    cur.execute(
        "SELECT created_at, status, started_at, completed_at, review FROM results "
        "WHERE team_id = %s AND station_id = %s",
        (team_id, station_id),
    )
    return cur.fetchone()


def save_result(cur, team_id, station_id, result):
    """Persist the result values chosen by gameLogic."""
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


def save_station_state(cur, station_id, team_id, status, review_score, timestamp):
    cur.execute(
        f"""UPDATE station_state SET team_id = %s, status = %s,
               review_score = %s, updated_at = %s
               WHERE station_id = %s RETURNING {STATE_COLUMNS}""",
        (team_id, status, review_score, timestamp, station_id),
    )
    return cur.fetchone()


def log_event(cur, station_id, team_id, event_type, review_score, timestamp):
    cur.execute(
        """INSERT INTO station_events (created_at, station_id, team_id, event_type, review_score)
           VALUES (%s, %s, %s, %s, %s)""",
        (timestamp, station_id, team_id, event_type, review_score),
    )
