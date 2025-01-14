"""
Copyright Astronomer, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
"""
Unittest module to test Operators.

Requires the unittest, pytest, and requests-mock Python libraries.

Run test:

    python3 -m unittest tests.operators.test_snowflake_decorator.TestSnowflakeOperator

"""

import logging
import os
import pathlib
import unittest.mock

import utils as test_utils
from airflow.models import DAG, DagRun
from airflow.models import TaskInstance as TI
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook
from airflow.utils import timezone
from airflow.utils.session import create_session
from airflow.utils.state import State
from airflow.utils.types import DagRunType

# Import Operator
from astro import sql as aql
from astro.sql.table import Table

log = logging.getLogger(__name__)
DEFAULT_DATE = timezone.datetime(2016, 1, 1)


def drop_table(table_name, snowflake_conn):
    cursor = snowflake_conn.cursor()
    cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
    snowflake_conn.commit()
    cursor.close()
    snowflake_conn.close()


def get_snowflake_hook():
    hook = SnowflakeHook(
        snowflake_conn_id="snowflake_conn",
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
    )
    return hook


class TestSnowflakeOperator(unittest.TestCase):
    """
    Test Sample Operator.
    """

    cwd = pathlib.Path(__file__).parent

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.snowflake_table = test_utils.get_table_name(
            "SNOWFLAKE_TRANSFORM_TEST_TABLE"
        )
        cls.snowflake_table_raw_sql = test_utils.get_table_name(
            "SNOWFLAKE_TRANSFORM_RAW_SQL_TEST_TABLE"
        )

    @classmethod
    def tearDownClass(cls):
        test_utils.drop_table_snowflake(
            table_name=cls.snowflake_table,
            schema=os.getenv("SNOWFLAKE_SCHEMA"),
            database=os.getenv("SNOWFLAKE_DATABASE"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
            conn_id="snowflake_conn",
        )
        test_utils.drop_table_snowflake(
            table_name=cls.snowflake_table_raw_sql,
            schema=os.getenv("SNOWFLAKE_SCHEMA"),
            database=os.getenv("SNOWFLAKE_DATABASE"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
            conn_id="snowflake_conn",
        )

    def setUp(self):
        cwd = pathlib.Path(__file__).parent
        self.input_table_name = test_utils.get_table_name("snowflake_decorator_test")
        aql.load_file(
            path=str(cwd) + "/../data/homes.csv",
            output_table=Table(
                self.input_table_name,
                conn_id="snowflake_conn",
                schema=os.getenv("SNOWFLAKE_SCHEMA"),
                database=os.getenv("SNOWFLAKE_DATABASE"),
                warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
            ),
        ).operator.execute({"run_id": "foo"})
        super().setUp()
        self.dag = DAG(
            "test_dag",
            default_args={
                "owner": "airflow",
                "start_date": DEFAULT_DATE,
            },
        )
        self.addCleanup(self.dag.clear)
        self.clear_run()
        self.addCleanup(self.clear_run)

    def clear_run(self):
        self.run = False

    def tearDown(self):
        super().tearDown()

        with create_session() as session:
            session.query(DagRun).delete()
            session.query(TI).delete()

        test_utils.drop_table_snowflake(
            table_name=self.input_table_name,
            schema=os.getenv("SNOWFLAKE_SCHEMA"),
            database=os.getenv("SNOWFLAKE_DATABASE"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
            conn_id="snowflake_conn",
        )

    def wait_for_task_finish(self, dr, task_id):
        import time

        task = dr.get_task_instance(task_id)
        while task.state not in ["success", "failed"]:
            time.sleep(1)
            task = dr.get_task_instance(task_id)

    def test_snowflake_query(self):
        @aql.transform
        def sample_snow(input_table: Table):
            return f"SELECT * FROM {input_table.table_name} LIMIT 10"

        hook = get_snowflake_hook()
        drop_table(
            snowflake_conn=hook.get_conn(),
            table_name=self.snowflake_table,
        )
        with self.dag:
            f = sample_snow(
                input_table=Table(
                    self.input_table_name,
                    conn_id="snowflake_conn",
                    schema=os.getenv("SNOWFLAKE_SCHEMA"),
                    database=os.getenv("SNOWFLAKE_DATABASE"),
                    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
                ),
                output_table=Table(
                    self.snowflake_table,
                    conn_id="snowflake_conn",
                    schema=os.getenv("SNOWFLAKE_SCHEMA"),
                    database=os.getenv("SNOWFLAKE_DATABASE"),
                    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
                ),
            )

        dr = self.dag.create_dagrun(
            run_id=DagRunType.MANUAL.value,
            start_date=timezone.utcnow(),
            execution_date=DEFAULT_DATE,
            state=State.RUNNING,
        )
        f.operator.run(start_date=DEFAULT_DATE, end_date=DEFAULT_DATE)

        df = hook.get_pandas_df(
            f'SELECT * FROM "{os.getenv("SNOWFLAKE_DATABASE")}"."{os.getenv("SNOWFLAKE_SCHEMA")}"."{self.snowflake_table}"'
        )
        assert len(df) == 10

    def test_raw_sql(self):
        hook = get_snowflake_hook()
        drop_table(
            snowflake_conn=hook.get_conn(),
            table_name=self.snowflake_table_raw_sql,
        )

        @aql.run_raw_sql(
            conn_id="snowflake_conn",
        )
        def sample_snow(my_input_table: Table, snowflake_table_raw_sql: str):
            return f"CREATE TABLE {snowflake_table_raw_sql} AS (SELECT * FROM {my_input_table.table_name} LIMIT 5)"

        with self.dag:
            f = sample_snow(
                my_input_table=Table(
                    self.input_table_name,
                    conn_id="snowflake_conn",
                    schema=os.getenv("SNOWFLAKE_SCHEMA"),
                    database=os.getenv("SNOWFLAKE_DATABASE"),
                    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
                ),
                snowflake_table_raw_sql=self.snowflake_table_raw_sql,
            )

        dr = self.dag.create_dagrun(
            run_id=DagRunType.MANUAL.value,
            start_date=timezone.utcnow(),
            execution_date=DEFAULT_DATE,
            state=State.RUNNING,
        )
        f.operator.run(start_date=DEFAULT_DATE, end_date=DEFAULT_DATE)

        # Read table from db
        df = hook.get_pandas_df(
            f'SELECT * FROM "{os.getenv("SNOWFLAKE_DATABASE")}"."{os.getenv("SNOWFLAKE_SCHEMA")}"."{self.snowflake_table_raw_sql}"'
        )
        assert len(df) == 5
