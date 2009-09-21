# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Scrub a Launchpad database of private data."""

import _pythonpath

__metaclass__ = type
__all__ = []

import re
import subprocess
import sys

import transaction
from zope.component import getUtility

from canonical.database.sqlbase import cursor
from canonical.database.postgresql import ConnectionString, listReferences
from canonical.launchpad.interfaces import IMasterStore
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MAIN_STORE, MASTER_FLAVOR)
from canonical.lp import initZopeless
from lp.services.scripts.base import LaunchpadScript


class SanitizeDb(LaunchpadScript):
    usage = "%prog [options] pg_connection_string"
    description = "Destroy private information in a Launchpad database."

    def add_my_options(self):
        self.parser.add_option(
            "-f", "--force", action="store_true", default=False,
            help="Force running against a possible production database.")

    def _init_db(self, implicit_begin, isolation):
        if len(self.args) == 0:
            self.parser.error("PostgreSQL connection string required.")
        elif len(self.args) > 1:
            self.parser.error("Too many arguments.")

        self.pg_connection_string = ConnectionString(self.args[0])

        if ('prod' in str(self.pg_connection_string)
            and not self.options.force):
            self.parser.error(
            "Attempting to sanitize a potential production database '%s'. "
            "--force required." % pg_connection_string.dbname)

        self.logger.debug("Connect using '%s'." % self.pg_connection_string)

        self.txn = initZopeless(
            dbname=self.pg_connection_string.dbname,
            dbhost=self.pg_connection_string.host,
            dbuser=self.pg_connection_string.user,
            implicitBegin=implicit_begin,
            isolation=isolation)

        self.store = getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)

    def main(self):
        self.allForeignKeysCascade()

        tables_to_empty = [
            'accountpassword',
            'archiveauthtoken',
            'authtoken',
            'commercialsubscription',
            'entitlement',
            'openidassociation',
            'openidauthorization',
            'openidconsumerassociation',
            'openidconsumernonce',
            'openidnonce',
            'openidrpsummary',
            'temporaryblobstorage',
            ]
        for table in tables_to_empty:
            self.removeTable(table)

        self.removeInactivePeople()
        self.removePrivatePeople()
        self.removePrivateBugs()
        self.removePrivateBranches()
        self.removePrivateHwSubmissions()

        # Remove unlinked records. These might contain private data.
        self.removeUnlinkedAccounts()
        self.removeUnlinkedEmailAddresses()
        self.removeUnlinked('revision', [
            ('revisioncache', 'revision'),
            ('revisionparent', 'revision'),
            ('revisionproperty', 'revision'),
            ])
        self.removeUnlinked('libraryfilealias', [
            ('libraryfiledownloadcount', 'libraryfilealias')])
        self.removeUnlinked('libraryfilecontent')
        self.removeUnlinked('message', [('messagechunk', 'message')])

        # Scrub data after removing all the records we are going to.
        # No point scrubbing data that is going to get removed later.
        columns_to_scrub = [
            ('person', 'personal_standing_reason'),
            ('account', 'status_comment'),
            ('distributionmirror', 'whiteboard'),
            ]
        for table, column in columns_to_scrub:
            self.scrubColumn(table, column)

        # Not implemented yet. These will fail.
        self.scrambleHiddenEmailAddresses()
        self.removePrivateTeams()

        self.resetForeignKeysCascade()
        transaction.commit()

    def removeInactivePeople(self):
        """Remove all suspended and deactivated people."""
        from lp.registry.model.person import Person
        from canonical.launchpad.interfaces.account import AccountStatus
        count = self.store.find(
            Person, Person.account_status != AccountStatus.ACTIVE).remove()
        self.logger.info("Removed %d inactive people.", count)

    def removePrivatePeople(self):
        """Remove all private people."""
        from lp.registry.interfaces.person import PersonVisibility
        from lp.registry.model.person import Person
        count = self.store.find(
            Person,
            Person.teamowner == None,
            Person.visibility != PersonVisibility.PUBLIC).remove()
        self.logger.info("Removed %d private people.", count)

    def removePrivateBugs(self):
        """Remove all private bugs."""
        from lp.bugs.model.bug import Bug
        count = self.store.find(Bug, Bug.private == True).remove()
        self.logger.info("Removed %d private bugs.", count)

    def removePrivateBranches(self):
        """Remove all private branches."""
        from lp.code.model.branch import Branch
        count = self.store.find(Branch, Branch.private == True).remove()
        self.logger.info("Removed %d private branches.", count)

    def removePrivateHwSubmissions(self):
        """Remove all private hardware submissions."""
        from canonical.launchpad.database.hwdb import HWSubmission
        count = self.store.find(
            HWSubmission, HWSubmission.private == True).remove()
        self.logger.info(
            "Removed %d private hardware submissions.", count)

    def removeTable(self, table):
        """Remove all data from a table."""
        count = self.store.execute("DELETE FROM %s" % table).rowcount
        self.logger.info("Removed %d %s rows (all).", count, table)

    def removeUnlinked(self, table, ignores=()):
        """Remove all unlinked entries in the table.

        References from the ignores list are ignored.

        :param table: table name.

        :param ignores: list of (table, column) references to ignore.
        """
        references = []
        for result in listReferences(cursor(), table, 'id'):
            (from_table, from_column, to_table,
                to_column, update, delete) = result
            if (to_table == table and to_column == 'id'
                and (from_table, from_column) not in ignores):
                references.append(
                    "SELECT %s FROM %s" % (from_column, from_table))
        subquery = " UNION ".join(references)
        query = "DELETE FROM %s WHERE id NOT IN (%s)" % (table, subquery)
        self.logger.debug(query)
        count = self.store.execute(query).rowcount
        self.logger.info("Removed %d unlinked %s rows.", count, table)

    def removePrivateTeams(self):
        """Remove all private teams."""
        raise NotImplementedError

    def scrambleHiddenEmailAddresses(self):
        """Hide email addresses users have requested to not be public.

        This replaces the email addresses of all people with
        hide_email_addresses set with an @example.com email address.
        """
        raise NotImplementedError

    def removeUnlinkedAccounts(self):
        """Remove Accounts not linked to a Person."""
        count = self.store.execute("""
            DELETE FROM Account
            USING EmailAddress
            WHERE Account.id = EmailAddress.account
                AND EmailAddress.person IS NULL
            """).rowcount
        self.logger.info("Removed %d accounts not linked to a person", count)

    def removeUnlinkedEmailAddresses(self):
        """Remove EmailAddresses not linked to a Person.

        This needs to be called after all the Person records have been
        removed.
        """
        from canonical.launchpad.database.emailaddress import EmailAddress
        count =-self.store.find(
            EmailAddress, EmailAddress.person == None).remove()
        self.logger.info(
            "Removed %d email addresses not linked to people.", count)

    def scrubColumn(self, table, column):
        """Remove production admin related notes."""
        count = self.store.execute("""
            UPDATE %s SET %s = NULL
            WHERE %s IS NOT NULL
            """ % (table, column, column)).rowcount
        self.logger.info(
            "Scrubbed %d %s.%s entries." % (count, table, column))

    def allForeignKeysCascade(self):
        """Set all foreign key constraints to ON DELETE CASCADE.

        The current state is recorded first so resetForeignKeysCascade
        can repair the changes.

        Only tables in the public schema are modified.
        """
        # Get the SQL needed to create the foreign key constraints.
        # pg_dump seems the only sane way of getting this. We could
        # generate the SQL ourselves using the pg_constraints table,
        # but that can change between PostgreSQL releases.
        # Ideally we could use ALTER CONSTRAINT, but that doesn't exist.
        # Or modify pg_constraints, but that doesn't work.
        cmd = [
            'pg_dump', '--no-privileges', '--no-owner', '--schema-only',
            '--schema=public']
        cmd.extend(
            self.pg_connection_string.asPGCommandLineArgs().split(' '))
        self.logger.debug("Running %s", ' '.join(cmd))
        pg_dump = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE)
        (pg_dump_out, pg_dump_err) = pg_dump.communicate()
        if pg_dump.returncode != 0:
            self.fail("pg_dump returned %d" % pg_dump.returncode)

        cascade_sql = []
        restore_sql = []
        pattern = r"""
            (?x) ALTER \s+ TABLE \s+ ONLY \s+ (".*?"|\w+?) \s+
            ADD \s+ CONSTRAINT \s+ (".*?"|\w+?) \s+ FOREIGN \s+ KEY [^;]+;
            """
        for match in re.finditer(pattern, pg_dump_out):
            table = match.group(1)
            constraint = match.group(2)

            sql = match.group(0)

            # Drop the existing constraint so we can recreate it.
            drop_sql =  'ALTER TABLE %s DROP CONSTRAINT %s;' % (
                table, constraint)
            restore_sql.append(drop_sql)
            cascade_sql.append(drop_sql)

            # Store the SQL needed to restore the constraint.
            restore_sql.append(sql)

            # Recreate the constraint as ON DELETE CASCADE
            sql = re.sub(r"""(?xs)^
                (.*?)
                (?:ON \s+ DELETE \s+ (?:NO\s+|SET\s+)?\w+)? \s*
                ((?:NOT\s+)? DEFERRABLE|) \s*
                (INITIALLY\s+(?:DEFERRED|IMMEDIATE)|) \s*;
                """, r"\1 ON DELETE CASCADE \2 \3;", sql)
            cascade_sql.append(sql)

        # Set all the foreign key constraints to ON DELETE CASCADE, really.
        self.logger.info(
            "Setting %d constraints to ON DELETE CASCADE",
            len(cascade_sql) / 2)
        self.store.execute('\n'.join(cascade_sql))

        # Store the recovery SQL.
        self._reset_foreign_key_sql = restore_sql

    def resetForeignKeysCascade(self):
        """Reset the foreign key constraints' ON DELETE mode."""
        self.logger.info(
            "Resetting %d foreign key constraints to initial state.",
            len(self._reset_foreign_key_sql)/2)
        self.store.execute('\n'.join(self._reset_foreign_key_sql))

    def _fail(self, error_message):
        self.logger.fatal(error_message)
        sys.exit(1)

