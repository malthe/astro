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
from airflow.models import DagRun, TaskInstance


class Table:
    def __init__(
        self, table_name="", conn_id=None, database=None, schema=None, warehouse=None
    ):
        self.table_name = table_name
        self.conn_id = conn_id
        self.database = database
        self.schema = schema
        self.warehouse = warehouse

    def identifier_args(self):
        return (self.schema, self.table_name) if self.schema else (self.table_name,)

    def qualified_name(self):
        return self.schema + "." + self.table_name if self.schema else self.table_name

    def __str__(self):
        return f"Table(table_name={self.table_name}, database={self.database}, schema={self.schema}, conn_id={self.conn_id}, warehouse={self.warehouse})"


class TempTable(Table):
    def __init__(self, conn_id, database, warehouse=""):
        super().__init__(
            table_name="", conn_id=conn_id, database=database, warehouse=warehouse
        )

    def to_table(self, table_name: str, schema: str) -> Table:
        return Table(
            table_name=table_name,
            conn_id=self.conn_id,
            database=self.database,
            warehouse=self.warehouse,
            schema=schema,
        )


def create_table_name(context, schema_id=None):
    ti: TaskInstance = context["ti"]
    dag_run: DagRun = ti.get_dagrun()
    return f"{dag_run.dag_id}_{ti.task_id}_{dag_run.id}"
