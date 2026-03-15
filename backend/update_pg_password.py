import psycopg2

try:
    conn = psycopg2.connect('postgresql://postgres:postgres123@127.0.0.1:5432/postgres')
    cur = conn.cursor()
    cur.execute("ALTER USER postgres WITH PASSWORD 'Lk106504'")
    conn.commit()
    print('PostgreSQL password updated to: Lk106504')
    conn.close()
except Exception as e:
    print(f'Error: {e}')
