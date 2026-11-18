-- Run once as the MySQL root user. It creates the app database, a test database and an
-- app account. Change 'change-me' to your own password and put the same one in .env.
--   mysql -u root -p < backend/sql/setup_db.sql
CREATE DATABASE IF NOT EXISTS nutrimate_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS nutrimate_ai_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'nutrimate_ai'@'localhost' IDENTIFIED BY 'change-me';
CREATE USER IF NOT EXISTS 'nutrimate_ai'@'127.0.0.1' IDENTIFIED BY 'change-me';
GRANT ALL PRIVILEGES ON nutrimate_ai.* TO 'nutrimate_ai'@'localhost';
GRANT ALL PRIVILEGES ON nutrimate_ai_test.* TO 'nutrimate_ai'@'localhost';
GRANT ALL PRIVILEGES ON nutrimate_ai.* TO 'nutrimate_ai'@'127.0.0.1';
GRANT ALL PRIVILEGES ON nutrimate_ai_test.* TO 'nutrimate_ai'@'127.0.0.1';
FLUSH PRIVILEGES;
