-- Create the least-privilege ORASHIFT account in the FREEPDB1 pluggable database.
--
-- Requires SYSDBA. Run it yourself; the application never holds admin credentials.
-- Idempotent: re-running resets the password and re-applies the grants.
--
--   docker cp sql/oracle/00_create_orashift_user.sql <container>:/tmp/
--   docker exec -it <container> sqlplus -s / as sysdba @/tmp/00_create_orashift_user.sql
--
-- SQL*Plus will prompt for the password. To pass it non-interactively instead,
-- append it as an argument (it will land in your shell history):
--
--   ... @/tmp/00_create_orashift_user.sql 'YourPassword'

SET VERIFY OFF
WHENEVER SQLERROR EXIT FAILURE

DEFINE pdb_name     = FREEPDB1
DEFINE app_user     = ORASHIFT
DEFINE app_password = &1

ALTER SESSION SET CONTAINER = &pdb_name;

-- Switching container resets session state, so enable output after the switch.
SET SERVEROUTPUT ON

DECLARE
    v_exists PLS_INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_exists FROM dba_users WHERE username = '&app_user';

    IF v_exists = 0 THEN
        EXECUTE IMMEDIATE 'CREATE USER &app_user IDENTIFIED BY "&app_password"';
        DBMS_OUTPUT.PUT_LINE('Created user &app_user.');
    ELSE
        EXECUTE IMMEDIATE 'ALTER USER &app_user IDENTIFIED BY "&app_password"';
        DBMS_OUTPUT.PUT_LINE('User &app_user already existed; password reset.');
    END IF;
END;
/

-- Exactly the privileges the pipeline needs to build and tear down its own objects.
-- Deliberately NOT granted: DBA, RESOURCE, UNLIMITED TABLESPACE, SELECT ANY TABLE.
GRANT CREATE SESSION   TO &app_user;
GRANT CREATE TABLE     TO &app_user;
GRANT CREATE VIEW      TO &app_user;
GRANT CREATE SEQUENCE  TO &app_user;
GRANT CREATE PROCEDURE TO &app_user;
GRANT CREATE TYPE      TO &app_user;

-- A bounded quota rather than UNLIMITED TABLESPACE, so a runaway generation
-- job cannot fill the datafile.
ALTER USER &app_user QUOTA 2G ON USERS;

COLUMN granted_role FORMAT A30
COLUMN privilege    FORMAT A30

PROMPT
PROMPT System privileges now held by &app_user:
SELECT privilege FROM dba_sys_privs WHERE grantee = '&app_user' ORDER BY privilege;

PROMPT Tablespace quota:
SELECT tablespace_name, max_bytes FROM dba_ts_quotas WHERE username = '&app_user';

EXIT SUCCESS
