-- Copyright 2014 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE binarypackagebuild ADD COLUMN arch_indep boolean;

INSERT INTO LaunchpadDatabaseRevision VALUES (2209, 59, 0);
