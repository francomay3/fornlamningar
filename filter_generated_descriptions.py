#!/usr/bin/env python3
"""
Script to create a new database derived from the 20km filtered database,
containing only entries where generatedDescription is not null.
"""

import sqlite3
import os
from pathlib import Path

def create_filtered_database():
    """Create a new database with only entries that have generatedDescription."""
    
    # Define paths
    src_dir = Path("src/data")
    input_db = src_dir / "fornlamningar_filtered_20km.sqlite"
    output_db = src_dir / "fornlamningar_with_descriptions.sqlite"
    
    # Check if input database exists
    if not input_db.exists():
        print(f"Error: Input database not found at {input_db}")
        return False
    
    print(f"Reading from: {input_db}")
    print(f"Writing to: {output_db}")
    
    try:
        # Connect to input database
        with sqlite3.connect(input_db) as conn_in:
            # Get table schema
            cursor = conn_in.cursor()
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fornlamningar'")
            table_schema = cursor.fetchone()[0]
            
            # Count total entries
            cursor.execute("SELECT COUNT(*) FROM fornlamningar")
            total_count = cursor.fetchone()[0]
            
            # Count entries with generatedDescription
            cursor.execute("SELECT COUNT(*) FROM fornlamningar WHERE generatedDescription IS NOT NULL")
            with_description_count = cursor.fetchone()[0]
            
            print(f"Total entries in source database: {total_count}")
            print(f"Entries with generatedDescription: {with_description_count}")
            
            # Create new database and copy filtered data
            with sqlite3.connect(output_db) as conn_out:
                # Create table with same schema
                conn_out.execute(table_schema)
                
                # Copy data where generatedDescription is not null
                cursor.execute("""
                    SELECT * FROM fornlamningar 
                    WHERE generatedDescription IS NOT NULL
                """)
                
                rows = cursor.fetchall()
                
                # Get column names
                column_names = [description[0] for description in cursor.description]
                placeholders = ', '.join(['?' for _ in column_names])
                insert_sql = f"INSERT INTO fornlamningar ({', '.join(column_names)}) VALUES ({placeholders})"
                
                # Insert filtered data
                conn_out.executemany(insert_sql, rows)
                conn_out.commit()
                
                print(f"Successfully created new database with {len(rows)} entries")
                print(f"New database saved to: {output_db}")
                
                # Verify the new database
                cursor_out = conn_out.cursor()
                cursor_out.execute("SELECT COUNT(*) FROM fornlamningar")
                final_count = cursor_out.fetchone()[0]
                print(f"Verification: New database contains {final_count} entries")
                
                # Check that all entries have generatedDescription
                cursor_out.execute("SELECT COUNT(*) FROM fornlamningar WHERE generatedDescription IS NULL")
                null_count = cursor_out.fetchone()[0]
                print(f"Entries without generatedDescription in new database: {null_count}")
                
                return True
                
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    success = create_filtered_database()
    if success:
        print("\n✅ Database filtering completed successfully!")
    else:
        print("\n❌ Database filtering failed!")



