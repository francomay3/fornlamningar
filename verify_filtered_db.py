#!/usr/bin/env python3
"""
Verification script to show sample data from the filtered database.
"""

import sqlite3
from pathlib import Path

def verify_filtered_database():
    """Show sample data from the filtered database."""
    
    db_path = Path("src/data/fornlamningar_with_descriptions.sqlite")
    
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Get total count
            cursor.execute("SELECT COUNT(*) FROM fornlamningar")
            total = cursor.fetchone()[0]
            print(f"Total entries in filtered database: {total}")
            
            # Show sample entries with generatedDescription
            cursor.execute("""
                SELECT sitename, class, generatedDescription 
                FROM fornlamningar 
                LIMIT 5
            """)
            
            rows = cursor.fetchall()
            print(f"\nSample entries with generatedDescription:")
            print("-" * 80)
            
            for i, (sitename, class_type, description) in enumerate(rows, 1):
                print(f"{i}. Site: {sitename}")
                print(f"   Class: {class_type}")
                print(f"   Generated Description: {description}")
                print()
            
            # Show some statistics
            cursor.execute("SELECT class, COUNT(*) FROM fornlamningar GROUP BY class ORDER BY COUNT(*) DESC LIMIT 5")
            class_stats = cursor.fetchall()
            
            print("Top 5 site classes in filtered database:")
            print("-" * 40)
            for class_type, count in class_stats:
                print(f"{class_type}: {count} sites")
                
    except sqlite3.Error as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    verify_filtered_database()



