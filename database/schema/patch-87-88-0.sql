SET client_min_messages=ERROR;

CREATE TABLE CodeImport (
    id SERIAL PRIMARY KEY,
    date_created TIMESTAMP WITHOUT TIME ZONE
        DEFAULT timezone('UTC', now()) NOT NULL,
    name text NOT NULL UNIQUE,
    branch integer REFERENCES Branch UNIQUE NOT NULL,
    registrant integer REFERENCES Person UNIQUE NOT NULL,

    review_status integer DEFAULT 1 NOT NULL,

    rcs_type integer NOT NULL,
    svn_branch_url text UNIQUE,
    cvs_root text,
    cvs_module text,

    UNIQUE (cvs_root, cvs_module),

    CONSTRAINT valid_name CHECK (valid_name(name)),
    CONSTRAINT valid_cvs CHECK ((rcs_type <> 1) OR (
        (cvs_root IS NOT NULL) AND (cvs_root <> '') AND
        (cvs_module IS NOT NULL) AND (cvs_module <> ''))),
    CONSTRAINT null_cvs CHECK ((rcs_type = 1) OR (
        (cvs_root IS NULL) AND (cvs_module IS NULL))),
    CONSTRAINT valid_svn CHECK ((rcs_type <> 2) OR (
        (svn_branch_url IS NOT NULL) AND (svn_branch_url <> ''))),
    CONSTRAINT null_svn CHECK ((rcs_type = 2) OR (svn_branch_url IS NULL))


);

-- XXX: This should be fixed once we get a real patch number:
-- MichaelHudson, 2007-05-15
INSERT INTO LaunchpadDatabaseRevision VALUES (87, 88, 0);
