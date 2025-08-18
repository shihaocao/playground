import pytest
import sqlite3
import tempfile
import os


class TestSimpleSQLite:
    """Simple SQLite test example."""
    
    def test_create_and_query_database(self):
        """Create a SQLite database, add data, and query it."""
        # Create temporary database file
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_db.close()
        
        try:
            # Connect to database
            conn = sqlite3.connect(temp_db.name)
            cursor = conn.cursor()
            
            # Create a simple table
            cursor.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    age INTEGER
                )
            """)
            
            # Insert some data
            users = [
                (1, 'Alice', 25),
                (2, 'Bob', 30),
                (3, 'Charlie', 35)
            ]
            cursor.executemany("INSERT INTO users VALUES (?, ?, ?)", users)
            
            # Commit changes
            conn.commit()
            
            # Query the data
            cursor.execute("SELECT name, age FROM users WHERE age > 25")
            results = cursor.fetchall()
            
            # Verify results
            assert len(results) == 2
            assert ('Bob', 30) in results
            assert ('Charlie', 35) in results
            
            # Close connection
            conn.close()
            
        finally:
            # Clean up temporary file
            os.unlink(temp_db.name)
