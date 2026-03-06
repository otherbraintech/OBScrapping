import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Add parent directory to path to import from database.py if needed, 
# although we'll use raw SQL for the migration to be safe.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    print("Error: DATABASE_URL not found in .env")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

def run_migration():
    print(f"Connecting to database...")
    try:
        with engine.connect() as conn:
            # Check if column exists
            check_sql = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='scrape_results' AND column_name='full_html';
            """)
            result = conn.execute(check_sql).fetchone()
            
            if result:
                print("Column 'full_html' already exists in 'scrape_results'.")
            else:
                print("Adding 'full_html' column to 'scrape_results'...")
                add_sql = text("ALTER TABLE scrape_results ADD COLUMN full_html TEXT;")
                conn.execute(add_sql)
                conn.commit()
                print("Column 'full_html' added successfully.")
                
    except Exception as e:
        print(f"Error during migration: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
