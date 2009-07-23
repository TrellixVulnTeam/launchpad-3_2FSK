-- Copyright 2009 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE VIEW HWDriverPackageNames AS
    SELECT DISTINCT ON (package_name) id, package_name from HWDriver
        ORDER BY package_name, id;

CREATE VIEW HWDriverNames AS
    SELECT DISTINCT ON (name) id, name from HWDriver
        ORDER BY name, id;

INSERT INTO LaunchpadDatabaseRevision VALUES (2109, 53, 0);
