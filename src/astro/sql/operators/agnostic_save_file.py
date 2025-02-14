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

import os
from typing import Optional

import boto3
import pandas as pd
from airflow.hooks.base import BaseHook
from airflow.models import BaseOperator, DagRun, TaskInstance

from astro.sql.operators.temp_hooks import TempPostgresHook, TempSnowflakeHook
from astro.sql.table import Table
from astro.utils.task_id_helper import get_task_id


class SaveFile(BaseOperator):
    """Write SQL table to csv/parquet on local/S3/GCS.

    :param output_file_path: Path and name of table to create.
    :type output_file_path: str
    :param table: Input table name.
    :type table: str
    :param input_conn_id: Database connection id.
    :type input_conn_id: str
    :param output_conn_id: File system connection id (if S3 or GCS).
    :type output_conn_id: str
    :param overwrite: Overwrite file if exists. Default False.
    :type overwrite: bool
    :param output_file_format: file formats, valid values csv/parquet. Default: 'csv'.
    :type output_file_format: str
    """

    def __init__(
        self,
        table="",
        output_file_path="",
        input_table: Table = None,
        output_conn_id=None,
        output_file_format="csv",
        overwrite=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.table = table
        self.output_file_path = output_file_path
        self.input_table = input_table
        self.output_conn_id = output_conn_id
        self.overwrite = overwrite
        self.output_file_format = output_file_format
        self.kwargs = kwargs

    def execute(self, context):
        """Write SQL table to csv/parquet on local/S3/GCS.

        Infers SQL database type based on connection.
        """

        # Infer db type from `input_conn_id`.
        input_table = self.input_table
        conn_type = BaseHook.get_connection(input_table.conn_id).conn_type

        # Select database Hook based on `conn` type
        input_hook = {
            "postgres": TempPostgresHook(
                postgres_conn_id=input_table.conn_id, schema=input_table.database
            ),
            "snowflake": TempSnowflakeHook(
                snowflake_conn_id=input_table.conn_id,
                database=input_table.database,
                schema=input_table.schema,
                warehouse=input_table.warehouse,
            ),
        }.get(conn_type, None)

        eng = input_hook.get_sqlalchemy_engine()
        # Load table from SQL db.
        df = pd.read_sql(
            f"SELECT * FROM {input_table.table_name}",
            con=input_hook.get_sqlalchemy_engine(),
        )

        # Write file if overwrite == True or if file doesn't exist.
        if self.overwrite == True or not self.file_exists(
            self.output_file_path, self.output_conn_id
        ):
            self.agnostic_write_file(df, self.output_file_path, self.output_conn_id)
        else:
            raise FileExistsError

    def file_exists(self, output_file_path, output_conn_id=None):
        if "s3://" in output_file_path:

            bucket_name, object_path = output_file_path.replace("s3://", "").split(
                "/", 1
            )

            # Check if object exists in S3.
            _creds = self._s3fs_creds()
            s3 = boto3.Session(_creds["key"], _creds["secret"]).resource("s3")

            # Return True if file in S3, else False.
            try:
                s3.Object(bucket_name, object_path).load()
                return True
            except:
                return False

        else:
            # Return True if file in local fs, else False.
            return os.path.isfile(output_file_path)

    def agnostic_write_file(self, df, output_file_path, output_conn_id=None):
        """Write dataframe to csv/parquet files formats

        Select output file format based on param output_file_format to class.
        """
        storage_options = self._s3fs_creds() if "s3://" in output_file_path else None
        {"csv": df.to_csv, "parquet": df.to_parquet}[self.output_file_format](
            output_file_path, storage_options=storage_options
        )

    def _load_dataframe(self, path):
        """Read file with Pandas.

        Select method based on `file_type` (S3 or local).
        """
        file_type = path.split(".")[-1]
        storage_options = self._s3fs_creds() if "s3://" in path else None
        return {"parquet": pd.read_parquet, "csv": pd.read_csv}[file_type](
            path, storage_options=storage_options
        )

    def _s3fs_creds(self):
        # To-do: reuse this method from sql decorator
        """Structure s3fs credentials from Airflow connection.
        s3fs enables pandas to write to s3
        """
        # To-do: clean-up how S3 creds are passed to s3fs
        k, v = (
            os.environ["AIRFLOW__ASTRO__CONN_AWS_DEFAULT"]
            .replace("%2F", "/")
            .replace("aws://", "")
            .replace("@", "")
            .split(":")
        )

        return {"key": k, "secret": v}

    @staticmethod
    def create_table_name(context):
        ti: TaskInstance = context["ti"]
        dag_run: DagRun = ti.get_dagrun()
        return f"{dag_run.dag_id}_{ti.task_id}_{dag_run.id}"


def save_file(
    output_file_path,
    table=None,
    input_table=None,
    output_conn_id=None,
    overwrite=False,
    output_file_format="csv",
    task_id=None,
    **kwargs,
):
    """Convert SaveFile into a function. Returns XComArg.

    Returns an XComArg object.

    :param output_file_path: Path and name of table to create.
    :type output_file_path: str
    :param table: Input table name.
    :type table: str
    :param input_conn_id: Database connection id.
    :type input_conn_id: str
    :param output_conn_id: File system connection id (if S3 or GCS).
    :type output_conn_id: str
    :param overwrite: Overwrite file if exists. Default False.
    :type overwrite: bool
    :param task_id: task id, optional.
    :type task_id: str
    """

    task_id = (
        task_id if task_id is not None else get_task_id("save_file", output_file_path)
    )

    return SaveFile(
        task_id=task_id,
        output_file_path=output_file_path,
        table=table,
        input_table=input_table,
        output_conn_id=output_conn_id,
        overwrite=overwrite,
        output_file_format=output_file_format,
    ).output
