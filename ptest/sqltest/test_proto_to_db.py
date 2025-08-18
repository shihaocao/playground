import pytest
import sqlite3
import tempfile
import os
from typing import Dict, Any, List
from google.protobuf import message
from google.protobuf.json_format import MessageToDict
import json


class ProtoToDBHandler:
    """Handles conversion of protobuf messages to database records."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
    
    def close(self):
        """Close database connection."""
        self.conn.close()
    
    def proto_to_dict(self, proto_msg: message.Message) -> Dict[str, Any]:
        """Convert protobuf message to dictionary."""
        return MessageToDict(proto_msg, preserving_proto_field_name=True)
    
    def create_table_from_dict(self, table_name: str, data_dict: Dict[str, Any]) -> str:
        """Dynamically create table based on dictionary structure."""
        cursor = self.conn.cursor()
        
        # Generate CREATE TABLE statement
        columns = []
        for key, value in data_dict.items():
            if isinstance(value, int):
                col_type = "INTEGER"
            elif isinstance(value, float):
                col_type = "REAL"
            elif isinstance(value, bool):
                col_type = "INTEGER"  # SQLite doesn't have BOOLEAN
            elif isinstance(value, str):
                col_type = "TEXT"
            elif value is None:
                col_type = "TEXT"  # Default to TEXT for None values
            else:
                col_type = "TEXT"  # Default fallback
            
            columns.append(f"{key} {col_type}")
        
        # Add id column for primary key
        columns.insert(0, "id INTEGER PRIMARY KEY AUTOINCREMENT")
        
        create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(columns)})"
        cursor.execute(create_sql)
        self.conn.commit()
        
        return create_sql
    
    def insert_dict_data(self, table_name: str, data_dict: Dict[str, Any]) -> int:
        """Insert dictionary data into specified table."""
        cursor = self.conn.cursor()
        
        # Filter out None values and prepare for insertion
        filtered_data = {k: v for k, v in data_dict.items() if v is not None}
        
        if not filtered_data:
            return 0
        
        columns = list(filtered_data.keys())
        placeholders = ', '.join(['?' for _ in columns])
        values = list(filtered_data.values())
        
        insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        cursor.execute(insert_sql, values)
        self.conn.commit()
        
        return cursor.lastrowid
    
    def process_proto_message(self, proto_msg: message.Message, table_name: str = None) -> Dict[str, Any]:
        """Process a protobuf message: convert to dict, create table, insert data."""
        # Convert proto to dict
        data_dict = self.proto_to_dict(proto_msg)
        
        # Generate table name if not provided
        if table_name is None:
            table_name = proto_msg.__class__.__name__.lower()
        
        # Create table dynamically
        self.create_table_from_dict(table_name, data_dict)
        
        # Insert data
        row_id = self.insert_dict_data(table_name, data_dict)
        
        return {
            'table_name': table_name,
            'row_id': row_id,
            'data': data_dict
        }


# Mock protobuf message classes for testing
class MockProtoMessage:
    """Mock protobuf message for testing."""
    
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __class__(self):
        return type('MockProto', (), {'__name__': 'MockProto'})
    
    def __getattr__(self, name):
        return None


class TestProtoToDB:
    """Test protobuf to database conversion."""
    
    def test_proto_to_dict_conversion(self):
        """Test converting protobuf message to dictionary."""
        # Create mock proto message
        proto_msg = MockProtoMessage(
            user_id=123,
            username="test_user",
            email="test@example.com",
            is_active=True,
            score=95.5
        )
        
        # Test conversion
        handler = ProtoToDBHandler(":memory:")
        result_dict = handler.proto_to_dict(proto_msg)
        
        assert result_dict['user_id'] == 123
        assert result_dict['username'] == "test_user"
        assert result_dict['email'] == "test@example.com"
        assert result_dict['is_active'] is True
        assert result_dict['score'] == 95.5
        
        handler.close()
    
    def test_dynamic_table_creation(self):
        """Test dynamic table creation from dictionary."""
        # Create temporary database
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_db.close()
        
        try:
            handler = ProtoToDBHandler(temp_db.name)
            
            # Test data
            test_data = {
                'name': 'John Doe',
                'age': 30,
                'salary': 75000.50,
                'is_manager': True
            }
            
            # Create table
            create_sql = handler.create_table_from_dict('employees', test_data)
            
            # Verify table was created
            cursor = handler.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='employees'")
            table_exists = cursor.fetchone() is not None
            assert table_exists
            
            # Verify schema
            cursor.execute("PRAGMA table_info(employees)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            
            assert columns['id'] == 'INTEGER'
            assert columns['name'] == 'TEXT'
            assert columns['age'] == 'INTEGER'
            assert columns['salary'] == 'REAL'
            assert columns['is_manager'] == 'INTEGER'
            
            handler.close()
            
        finally:
            os.unlink(temp_db.name)
    
    def test_end_to_end_proto_processing(self):
        """Test complete flow: proto -> dict -> table -> insert."""
        # Create temporary database
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_db.close()
        
        try:
            handler = ProtoToDBHandler(temp_db.name)
            
            # Create multiple mock proto messages
            proto_messages = [
                MockProtoMessage(
                    user_id=1,
                    username="alice",
                    email="alice@example.com",
                    age=25
                ),
                MockProtoMessage(
                    user_id=2,
                    username="bob",
                    email="bob@example.com",
                    age=30
                ),
                MockProtoMessage(
                    user_id=3,
                    username="charlie",
                    email="charlie@example.com",
                    age=35
                )
            ]
            
            # Process each proto message
            results = []
            for proto_msg in proto_messages:
                result = handler.process_proto_message(proto_msg, 'users')
                results.append(result)
            
            # Verify data was inserted
            cursor = handler.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            row_count = cursor.fetchone()[0]
            assert row_count == 3
            
            # Verify specific data
            cursor.execute("SELECT username, age FROM users WHERE user_id = 2")
            user_data = cursor.fetchone()
            assert user_data[0] == "bob"
            assert user_data[1] == 30
            
            # Verify all usernames
            cursor.execute("SELECT username FROM users ORDER BY user_id")
            usernames = [row[0] for row in cursor.fetchall()]
            assert usernames == ["alice", "bob", "charlie"]
            
            handler.close()
            
        finally:
            os.unlink(temp_db.name)
    
    def test_different_proto_types(self):
        """Test handling different types of protobuf messages."""
        # Create temporary database
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_db.close()
        
        try:
            handler = ProtoToDBHandler(temp_db.name)
            
            # Different proto message types
            user_proto = MockProtoMessage(
                user_id=100,
                name="John Smith",
                email="john@example.com"
            )
            
            order_proto = MockProtoMessage(
                order_id=200,
                customer_id=100,
                total_amount=299.99,
                is_paid=True
            )
            
            product_proto = MockProtoMessage(
                product_id=300,
                name="Widget",
                price=19.99,
                in_stock=True,
                category="Electronics"
            )
            
            # Process each type
            handler.process_proto_message(user_proto, 'users')
            handler.process_proto_message(order_proto, 'orders')
            handler.process_proto_message(product_proto, 'products')
            
            # Verify tables were created
            cursor = handler.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            assert 'users' in tables
            assert 'orders' in tables
            assert 'products' in tables
            
            # Verify data counts
            cursor.execute("SELECT COUNT(*) FROM users")
            assert cursor.fetchone()[0] == 1
            
            cursor.execute("SELECT COUNT(*) FROM orders")
            assert cursor.fetchone()[0] == 1
            
            cursor.execute("SELECT COUNT(*) FROM products")
            assert cursor.fetchone()[0] == 1
            
            handler.close()
            
        finally:
            os.unlink(temp_db.name)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
