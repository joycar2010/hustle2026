-- Create database and user for Hustle XAU
CREATE DATABASE hustle_db;
CREATE USER hustle_user WITH PASSWORD 'hustle_password';
GRANT ALL PRIVILEGES ON DATABASE hustle_db TO hustle_user;
ALTER DATABASE hustle_db OWNER TO hustle_user;
