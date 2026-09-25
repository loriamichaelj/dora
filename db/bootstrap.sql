-- Roles and schema for the DORA tracker (§6.4).
--
-- Idempotent, and portable: the same file runs locally (as the postgres
-- superuser, via db/init/01-bootstrap.sh) and on Amazon RDS (as the master
-- user, which has rds_superuser but is not a true superuser).
--
-- Run against database `dora` with two psql variables:
--   psql -v ON_ERROR_STOP=1 -v owner_password=... -v app_password=... -f bootstrap.sql
--
-- A second run changes nothing: existing roles keep their passwords.

\set ON_ERROR_STOP on

-- psql variables are not interpolated inside dollar-quoted DO bodies, so hand
-- the passwords to the DO block through session-local settings.
SELECT set_config('dora_bootstrap.owner_password', :'owner_password', false),
       set_config('dora_bootstrap.app_password', :'app_password', false) \g /dev/null

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dora_owner') THEN
        EXECUTE format('CREATE ROLE dora_owner LOGIN PASSWORD %L',
                       current_setting('dora_bootstrap.owner_password'));
    END IF;

    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dora_app') THEN
        EXECUTE format('CREATE ROLE dora_app LOGIN PASSWORD %L',
                       current_setting('dora_bootstrap.app_password'));
    END IF;

    -- CREATE SCHEMA ... AUTHORIZATION requires the caller to be able to SET ROLE
    -- to the owner. A superuser always can; the RDS master user needs membership.
    IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)
       AND NOT pg_has_role(current_user, 'dora_owner', 'SET') THEN
        EXECUTE format('GRANT dora_owner TO %I WITH INHERIT FALSE, SET TRUE', current_user);
    END IF;
END
$$;

SELECT set_config('dora_bootstrap.owner_password', '', false),
       set_config('dora_bootstrap.app_password', '', false) \g /dev/null

CREATE SCHEMA IF NOT EXISTS dora AUTHORIZATION dora_owner;

-- Grant as the schema owner: the RDS master user holds no grant option on a
-- schema it doesn't own.
SET ROLE dora_owner;
GRANT USAGE ON SCHEMA dora TO dora_app;
RESET ROLE;

ALTER ROLE dora_owner SET search_path = dora;
ALTER ROLE dora_app SET search_path = dora;
