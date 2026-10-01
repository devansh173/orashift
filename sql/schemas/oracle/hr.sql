-- Schema: hr (employees, jobs, management hierarchy)
-- Dialect: Oracle. SOURCE material.
-- grade_code is CHAR(2) on purpose: fixed-width CHAR pads with spaces, which is
-- a comparison trap that survives translation into PostgreSQL char(2).

CREATE TABLE hr_departments (
    department_id   NUMBER(4)       NOT NULL,
    department_name VARCHAR2(60)    NOT NULL,
    location        VARCHAR2(60),
    CONSTRAINT hr_departments_pk PRIMARY KEY (department_id),
    CONSTRAINT hr_departments_uq_name UNIQUE (department_name)
);

CREATE TABLE hr_jobs (
    job_id      VARCHAR2(12)    NOT NULL,
    job_title   VARCHAR2(60)    NOT NULL,
    min_salary  NUMBER(9,2)     NOT NULL,
    max_salary  NUMBER(9,2)     NOT NULL,
    CONSTRAINT hr_jobs_pk PRIMARY KEY (job_id),
    CONSTRAINT hr_jobs_ck_range CHECK (max_salary >= min_salary)
);

CREATE TABLE hr_pay_grades (
    grade_code  CHAR(2)         NOT NULL,
    min_salary  NUMBER(9,2)     NOT NULL,
    max_salary  NUMBER(9,2)     NOT NULL,
    CONSTRAINT hr_pay_grades_pk PRIMARY KEY (grade_code),
    CONSTRAINT hr_pay_grades_ck_range CHECK (max_salary >= min_salary)
);

CREATE TABLE hr_employees (
    employee_id     NUMBER(8)       NOT NULL,
    first_name      VARCHAR2(40)    NOT NULL,
    last_name       VARCHAR2(40)    NOT NULL,
    email           VARCHAR2(120)   NOT NULL,
    hire_date       DATE            NOT NULL,
    job_id          VARCHAR2(12)    NOT NULL,
    salary          NUMBER(9,2)     NOT NULL,
    commission_pct  NUMBER(4,3),
    manager_id      NUMBER(8),
    department_id   NUMBER(4),
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
    employee_id     NUMBER(8)       NOT NULL,
    start_date      DATE            NOT NULL,
    end_date        DATE,
    job_id          VARCHAR2(12)    NOT NULL,
    department_id   NUMBER(4),
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

CREATE SEQUENCE hr_employee_seq START WITH 200 INCREMENT BY 1 NOCACHE NOCYCLE;

CREATE VIEW hr_employee_directory AS
SELECT e.employee_id,
       e.first_name || ' ' || e.last_name                AS full_name,
       e.email,
       j.job_title,
       d.department_name,
       e.salary,
       NVL(e.commission_pct, 0)                          AS commission_pct,
       e.salary * (1 + NVL(e.commission_pct, 0))         AS total_comp
FROM hr_employees e
     JOIN hr_jobs j ON j.job_id = e.job_id
     LEFT JOIN hr_departments d ON d.department_id = e.department_id;
