-- Create the least-privilege orashift role and its database.
--
-- Requires a superuser connection. Run it yourself; the application never holds
-- admin credentials. Idempotent: re-running resets the password.
--
--   psql -d postgres -f sql/postgres/00_create_orashift_role.sql
--
-- psql will prompt for the password. To pass it non-interactively instead:
--
--   psql -d postgres -v orashift_password='YourPassword' -f sql/postgres/00_create_orashift_role.sql

\set ON_ERROR_STOP on

\if :{?orashift_password}
\else
\prompt 'Password for the new orashift role: ' orashift_password
\endif

-- CREATE ROLE has no IF NOT EXISTS, so build the statement and run it only when
-- the role is missing. \gexec executes the text returned by the query.
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'orashift', :'orashift_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orashift')
\gexec

-- Applied every run, so the role can never drift into holding more than this.
SELECT format(
    'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L',
    'orashift', :'orashift_password'
)
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', 'orashift', 'orashift')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'orashift')
\gexec

\connect orashift

-- The role owns its own schema; nobody else gets to create objects in it.
ALTER SCHEMA public OWNER TO orashift;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO orashift;

\echo
\echo 'Role attributes:'
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin
FROM pg_roles WHERE rolname = 'orashift';

\echo 'Database owner:'
SELECT d.datname, pg_catalog.pg_get_userbyid(d.datdba) AS owner
FROM pg_database d WHERE d.datname = 'orashift';
