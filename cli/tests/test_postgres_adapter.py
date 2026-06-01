import pytest
from modelable.runtime.adapter.postgres import PostgresAdapter
from modelable.parser.ir import FieldDef, PrimitiveType, FieldType

def test_postgres_ddl_generation():
    adapter = PostgresAdapter()
    
    # Create mock fields
    fields = [
        FieldDef(name="id", type=PrimitiveType(kind="uuid")),
        FieldDef(name="name", type=PrimitiveType(kind="string")),
        FieldDef(name="amount", type=PrimitiveType(kind="int")),
    ]
    
    ddl = adapter.generate_table_ddl("my_table", fields)
    
    # Verify SQL structure
    assert "CREATE TABLE IF NOT EXISTS my_table" in ddl
    assert "id UUID" in ddl
    assert "name TEXT" in ddl
    assert "amount INTEGER" in ddl
    assert ")" in ddl

def test_postgres_upsert_query_construction():
    adapter = PostgresAdapter()
    
    projection_plan = {
        "table_name": "my_table",
        "keys": ["id"],
        "connection_string": "dbname=test user=test"
    }
    
    data = [
        {"id": "uuid1", "name": "test1", "amount": 100},
        {"id": "uuid2", "name": "test2", "amount": 200}
    ]
    
    # We can test query generation by mocking psycopg.connect
    from unittest.mock import MagicMock, patch
    
    with patch("psycopg.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        
        adapter.materialize(projection_plan, data)
        
        # Verify call count
        assert mock_conn.cursor.return_value.__enter__.return_value.execute.call_count == 2
        
        # Check one of the executed queries
        args, _ = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args
        query = args[0]
        assert "INSERT INTO my_table (id, name, amount)" in query
        assert "ON CONFLICT (id)" in query
        assert "name = EXCLUDED.name" in query
        assert "amount = EXCLUDED.amount" in query
