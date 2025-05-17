# app/db.py
import psycopg2
import psycopg2.extras
import os
import sys # For better error output to stderr

def get_db_connection():
    """
    Establishes a connection to the PostgreSQL database.
    Uses the DATABASE_URL environment variable.
    The cursor factory is set to DictCursor to return rows as dictionaries.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("FATAL: DATABASE_URL environment variable not set.", file=sys.stderr)
        # In a real app, you might raise an exception or exit
        # For now, to prevent immediate crash during setup if not set,
        # we'll let psycopg2.connect handle the None case (which will fail).
        # Better to raise an explicit error:
        raise ValueError("DATABASE_URL environment variable is not set. Application cannot connect to the database.")

    try:
        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.DictCursor)
        return conn
    except psycopg2.Error as e:
        # Log the error more descriptively
        # Avoid printing sensitive parts of DB_URL in production logs if possible
        db_url_display = db_url[:db_url.find('@')] + "@..." if '@' in db_url else "URL (details hidden)"
        print(f"FATAL: Database connection failed. DB_URL might be incorrect or database not accessible.", file=sys.stderr)
        print(f"Used DB_URL: {db_url_display}", file=sys.stderr)
        print(f"Error details: {e}", file=sys.stderr)
        # Re-raise the exception so the application knows something went wrong
        raise 
