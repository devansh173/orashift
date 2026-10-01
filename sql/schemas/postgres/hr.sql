-- Schema: hr (employees, jobs, management hierarchy)
-- Dialect: PostgreSQL. Hand-written REFERENCE translation of
-- sql/schemas/oracle/hr.sql.
--
-- CHAR(2) maps to char(2) rather than varchar(2) on purpose: both engines pad
-- fixed-width character data with spaces, and preserving that keeps comparison
-- behaviour identical instead of quietly fixing it.

CREATE TABLE hr_departments (
    department_id   smallint        NOT NULL,
    department_name varchar(60)     NOT NULL,
    location        varchar(60),
    CONSTRAINT hr_departments_pk PRIMARY KEY (department_id),
    CONSTRAINT hr_departments_uq_name UNIQUE (department_name)
);

CREATE TABLE hr_jobs (
    job_id      varchar(12)     NOT NULL,
    job_title   varchar(60)     NOT NULL,
    min_salary  numeric(9,2)    NOT NULL,
    max_salary  numeric(9,2)    NOT NULL,
    CONSTRAINT hr_jobs_pk PRIMARY KEY (job_id),
    CONSTRAINT hr_jobs_ck_range CHECK (max_salary >= min_salary)
);

CREATE TABLE hr_pay_grades (
    grade_code  char(2)         NOT NULL,
    min_salary  numeric(9,2)    NOT NULL,
    max_salary  numeric(9,2)    NOT NULL,
    CONSTRAINT hr_pay_grades_pk PRIMARY KEY (grade_code),
    CONSTRAINT hr_pay_grades_ck_range CHECK (max_salary >= min_salary)
);

CREATE TABLE hr_employees (
    employee_id     integer         NOT NULL,
    first_name      varchar(40)     NOT NULL,
    last_name       varchar(40)     NOT NULL,
    email           varchar(120)    NOT NULL,
    hire_date       timestamp(0)    NOT NULL,
    job_id          varchar(12)     NOT NULL,
    salary          numeric(9,2)    NOT NULL,
    commission_pct  numeric(4,3),
    manager_id      integer,
    department_id   smallint,
    CONSTRAINT hr_employees_pk PRIMARY KEY (employee_id),
    CONSTRAINT hr_employees_uq_email UNIQUE (email),
    CONSTRAINT hr_employees_fk_job FOREIGN KEY (job_id)
        REFERENCES hr_jobs (job_id),
    CONSTRAINT hr_employees_fk_manager FOREIGN KEY (manager_id)
        REFERENCES hr_employees (employee_id),
    CONSTRAINT hr_employees_fk_dept FOREIGN KEY (department_id)
        REFERENCES hr_departments (department_id),
    CONSTRAINT hr_employees_ck_salary CHECK (salary > 0),
    CONSTRAINT hr_employees_ck_comm CHECK (commission_pct >= 0 AND commission_pct <= 1)
);

CREATE TABLE hr_job_history (
    employee_id     integer         NOT NULL,
    start_date      timestamp(0)    NOT NULL,
    end_date        timestamp(0),
    job_id          varchar(12)     NOT NULL,
    department_id   smallint,
    CONSTRAINT hr_job_history_pk PRIMARY KEY (employee_id, start_date),
    CONSTRAINT hr_job_history_fk_emp FOREIGN KEY (employee_id)
        REFERENCES hr_employees (employee_id),
    CONSTRAINT hr_job_history_fk_job FOREIGN KEY (job_id)
        REFERENCES hr_jobs (job_id),
    CONSTRAINT hr_job_history_fk_dept FOREIGN KEY (department_id)
        REFERENCES hr_departments (department_id),
    CONSTRAINT hr_job_history_ck_dates CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX hr_employees_ix_manager ON hr_employees (manager_id);

CREATE INDEX hr_employees_ix_dept ON hr_employees (department_id);

CREATE SEQUENCE hr_employee_seq START WITH 200 INCREMENT BY 1 CACHE 1 NO CYCLE;

-- The || concatenation is safe to carry over unchanged only because both
-- name columns are NOT NULL. With a nullable column, Oracle would return the
-- other operand and PostgreSQL would return NULL. See docs/dialect-notes.md.
CREATE VIEW hr_employee_directory AS
SELECT e.employee_id,
       e.first_name || ' ' || e.last_name                   AS full_name,
       e.email,
       j.job_title,
       d.department_name,
       e.salary,
       COALESCE(e.commission_pct, 0)                        AS commission_pct,
       e.salary * (1 + COALESCE(e.commission_pct, 0))       AS total_comp
FROM hr_employees e
     JOIN hr_jobs j ON j.job_id = e.job_id
     LEFT JOIN hr_departments d ON d.department_id = e.department_id;
