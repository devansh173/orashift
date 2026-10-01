-- Schema: library (lending library)
-- Dialect: PostgreSQL. Hand-written REFERENCE translation of
-- sql/schemas/oracle/library.sql.

CREATE TABLE library_authors (
    author_id       integer         NOT NULL,
    full_name       varchar(120)    NOT NULL,
    birth_year      smallint,
    country_code    char(2),
    CONSTRAINT library_authors_pk PRIMARY KEY (author_id),
    CONSTRAINT library_authors_ck_year CHECK (birth_year BETWEEN 1400 AND 2100)
);

CREATE TABLE library_books (
    book_id         integer         NOT NULL,
    isbn13          varchar(13)     NOT NULL,
    title           varchar(200)    NOT NULL,
    author_id       integer         NOT NULL,
    published_on    timestamp(0),
    page_count      integer,
    summary         text,
    CONSTRAINT library_books_pk PRIMARY KEY (book_id),
    CONSTRAINT library_books_uq_isbn UNIQUE (isbn13),
    CONSTRAINT library_books_fk_author FOREIGN KEY (author_id)
        REFERENCES library_authors (author_id),
    CONSTRAINT library_books_ck_pages CHECK (page_count > 0)
);

CREATE TABLE library_copies (
    copy_id             bigint          NOT NULL,
    book_id             integer         NOT NULL,
    acquired_on         timestamp(0)    NOT NULL,
    shelf_code          varchar(12)     NOT NULL,
    condition_rating    smallint,
    CONSTRAINT library_copies_pk PRIMARY KEY (copy_id),
    CONSTRAINT library_copies_fk_book FOREIGN KEY (book_id)
        REFERENCES library_books (book_id),
    CONSTRAINT library_copies_ck_condition CHECK (condition_rating BETWEEN 1 AND 5)
);

CREATE TABLE library_members (
    member_id       integer         NOT NULL,
    member_name     varchar(120)    NOT NULL,
    joined_on       timestamp(0)    NOT NULL,
    email           varchar(120),
    membership_type varchar(10)     NOT NULL,
    CONSTRAINT library_members_pk PRIMARY KEY (member_id),
    CONSTRAINT library_members_uq_email UNIQUE (email),
    CONSTRAINT library_members_ck_type
        CHECK (membership_type IN ('ADULT', 'CHILD', 'STUDENT', 'STAFF'))
);

CREATE TABLE library_loans (
    loan_id     bigint                      NOT NULL,
    copy_id     bigint                      NOT NULL,
    member_id   integer                     NOT NULL,
    borrowed_at timestamp(0)                NOT NULL,
    due_date    timestamp(0)                NOT NULL,
    returned_at timestamp(0),
    late_fee    numeric(8,2)    DEFAULT 0   NOT NULL,
    CONSTRAINT library_loans_pk PRIMARY KEY (loan_id),
    CONSTRAINT library_loans_fk_copy FOREIGN KEY (copy_id)
        REFERENCES library_copies (copy_id),
    CONSTRAINT library_loans_fk_member FOREIGN KEY (member_id)
        REFERENCES library_members (member_id),
    CONSTRAINT library_loans_ck_due CHECK (due_date >= borrowed_at),
    CONSTRAINT library_loans_ck_fee CHECK (late_fee >= 0)
);

CREATE INDEX library_loans_ix_member ON library_loans (member_id, borrowed_at);

CREATE INDEX library_copies_ix_book ON library_copies (book_id);

CREATE SEQUENCE library_loan_seq START WITH 90000 INCREMENT BY 1 CACHE 1 NO CYCLE;

-- TRUNC(SYSDATE) -> CURRENT_DATE, and TRUNC(due_date) -> a cast to date.
-- Subtracting two dates yields an integer day count in PostgreSQL, which
-- matches what Oracle's DATE arithmetic returns here.
CREATE VIEW library_active_loans AS
SELECT l.loan_id,
       l.member_id,
       m.member_name,
       b.title,
       l.borrowed_at,
       l.due_date,
       CURRENT_DATE - CAST(l.due_date AS date) AS days_overdue
FROM library_loans l
     JOIN library_copies c ON c.copy_id = l.copy_id
     JOIN library_books b ON b.book_id = c.book_id
     JOIN library_members m ON m.member_id = l.member_id
WHERE l.returned_at IS NULL;
