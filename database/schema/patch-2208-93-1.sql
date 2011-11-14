-- Copyright 2011 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).
SET client_min_messages=ERROR;

CREATE TABLE AccessPolicy (
    id serial PRIMARY KEY,
    product integer REFERENCES Product,
    distribution integer REFERENCES Distribution,
    type integer NOT NULL,
    CONSTRAINT has_target CHECK (product IS NULL != distribution IS NULL)
);

CREATE UNIQUE INDEX accesspolicy__product__type__key
    ON AccessPolicy(product, type) WHERE product IS NOT NULL;
CREATE UNIQUE INDEX accesspolicy__distribution__type__key
    ON AccessPolicy(distribution, type) WHERE distribution IS NOT NULL;

CREATE TABLE AccessPolicyArtifact (
    id serial PRIMARY KEY,
    bug integer REFERENCES Bug,
    branch integer REFERENCES Branch,
    policy integer REFERENCES AccessPolicy,
    CONSTRAINT has_artifact CHECK (bug IS NULL != branch IS NULL)
);

CREATE UNIQUE INDEX accesspolicyartifact__bug__key
    ON AccessPolicyArtifact(bug) WHERE branch IS NULL;
CREATE UNIQUE INDEX accesspolicyartifact__branch__key
    ON AccessPolicyArtifact(branch) WHERE bug IS NULL;
CREATE INDEX accesspolicyartifact__policy__key
    ON AccessPolicyArtifact(policy);

CREATE TABLE AccessPolicyGrant (
    id serial PRIMARY KEY,
    person integer NOT NULL REFERENCES Person,
    policy integer REFERENCES AccessPolicy,
    artifact integer REFERENCES AccessPolicyArtifact,
    creator integer NOT NULL REFERENCES Person,
    date_created timestamp without time zone
        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    CONSTRAINT has_target CHECK (policy IS NULL != artifact IS NULL)
);

CREATE UNIQUE INDEX accesspolicygrant__policy__person__key
    ON AccessPolicyGrant(policy, person) WHERE policy IS NOT NULL;
CREATE UNIQUE INDEX accessartifactgrant__artifact__person__key
    ON AccessPolicyGrant(artifact, person) WHERE artifact IS NOT NULL;
CREATE INDEX accesspolicygrant__person__idx ON AccessPolicyGrant(person);

ALTER TABLE bug
    ADD COLUMN access_policy integer REFERENCES AccessPolicy;
CREATE INDEX bug__access_policy__idx ON bug(access_policy);

ALTER TABLE branch
    ADD COLUMN access_policy integer REFERENCES AccessPolicy;
CREATE INDEX branch__access_policy__idx ON branch(access_policy);

INSERT INTO LaunchpadDatabaseRevision VALUES (2208, 93, 1);
