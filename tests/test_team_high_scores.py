"""Integration check for an isolated DB_NAME=team_scores_test database."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gameController"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gameClient"))
import config
import db
import gameLogic as logic
import resetGame


@unittest.skipUnless(os.getenv("DB_NAME") == "team_scores_test", "Requires isolated database")
class TeamScoreTests(unittest.TestCase):
    def query(self, sql, params=()):
        with closing(psycopg2.connect(**config.DB_CONFIG)) as conn:
            with conn, conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else None

    def play(self, multiplier, expected_existing):
        clock = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=multiplier)
        for index, station in enumerate(logic.configured_station_ids(), 1):
            with patch.object(db, "get_timestamp", return_value=clock):
                logic.change_station_state(station, 'Team-01', 'login')
            start = clock + timedelta(seconds=20)
            end = start + timedelta(seconds=index * multiplier)
            for action, timestamp in (('start', start), ('complete', end), ('review', end + timedelta(seconds=50))):
                with patch.object(db, "get_timestamp", return_value=timestamp):
                    state = logic.change_station_state(station, 'Team-01', action, 0 if action == 'review' else None)
            self.assertEqual(self.query('SELECT COUNT(*) FROM high_score_team')[0][0], expected_existing)
            if index == 5:
                before = self.query("SELECT status, updated_at FROM station_state WHERE station_id=%s", (station,))
                with patch.object(db, 'save_team_high_score', side_effect=psycopg2.IntegrityError('write failure')):
                    with self.assertRaises(psycopg2.IntegrityError):
                        logic.change_station_state(station, 'Team-01', 'idle', expected_updated_at=state['updated_at'])
                self.assertEqual(self.query("SELECT status, updated_at FROM station_state WHERE station_id=%s", (station,)), before)
            logic.change_station_state(station, 'Team-01', 'idle', expected_updated_at=state['updated_at'])
            self.assertIsNone(logic.change_station_state(station, 'Team-01', 'idle', expected_updated_at=state['updated_at']))
            clock = end + timedelta(seconds=200)  # Walking and reviews must not count.

    def test_backfill_new_games_and_reset(self):
        migration = Config('alembic.ini')
        command.upgrade(migration, '0011_high_score_team')
        self.assertTrue(logic.init_game())
        self.play(1, 0)
        self.query('DELETE FROM high_score_team')  # Simulate the old controller's missing score write.
        command.upgrade(migration, 'head')
        self.assertEqual(self.query('SELECT team_name, "round", time FROM high_score_team'),
                         [('Team-01', 1, timedelta(seconds=15))])
        self.assertEqual(self.query('SELECT COUNT(*) FROM results'), [(5,)])
        self.play(2, 1)
        self.assertEqual(self.query('SELECT "round", time FROM high_score_team ORDER BY "round"'),
                         [(1, timedelta(seconds=15)), (2, timedelta(seconds=30))])
        self.assertEqual(self.query('SELECT time FROM high_score ORDER BY station_id'),
                         [(timedelta(seconds=i),) for i in range(1, 6)])
        resetGame.reset_database()
        self.assertEqual(self.query('SELECT COUNT(*) FROM high_score_team'), [(2,)])
        logic.change_station_state('station_4', 'Team-01', 'login')
        self.assertEqual(self.query('SELECT "round" FROM station_events'), [(3,)])
        for invalid_time, invalid_round in ((None, 1), (timedelta(seconds=-1), 1), (timedelta(seconds=1), 0)):
            with self.assertRaises(psycopg2.IntegrityError):
                self.query('INSERT INTO high_score_team (team_name, "round", time) VALUES (%s,%s,%s)',
                           ('invalid', invalid_round, invalid_time))
        self.query('INSERT INTO high_score_team (team_name, "round", time) VALUES (%s,1,%s)',
                   ('x' * 255, timedelta(hours=25)))


if __name__ == '__main__':
    unittest.main()
