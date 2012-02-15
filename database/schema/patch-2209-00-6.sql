-- Copyright 2012 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE INDEX productreleasefile__productrelease__idx
    ON productreleasefile USING btree (productrelease); 

INSERT INTO LaunchpadDatabaseRevision VALUES (2209, 0, 6);
