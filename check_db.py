import sqlite3
import os

def check_database():
    db_path = 'instance/database.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Afficher la structure de la table class
    c.execute("PRAGMA table_info(class)")
    columns = c.fetchall()
    print("\nStructure de la table 'class':")
    for column in columns:
        print(f"- {column[1]} ({column[2]})")
    
    conn.close()

if __name__ == '__main__':
    check_database()
