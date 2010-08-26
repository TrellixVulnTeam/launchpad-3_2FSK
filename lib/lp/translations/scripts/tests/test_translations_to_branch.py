# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Acceptance test for the translations-export-to-branch script."""

import re
from textwrap import dedent
import unittest

from bzrlib.errors import NotBranchError
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.launchpad.scripts.logger import QuietFakeLogger
from canonical.launchpad.scripts.tests import run_script
from canonical.testing import ZopelessAppServerLayer
from lp.registry.interfaces.teammembership import (
    ITeamMembershipSet,
    TeamMembershipStatus,
    )
from lp.testing import (
    map_branch_contents,
    TestCaseWithFactory,
    )
from lp.testing.fakemethod import FakeMethod
from lp.translations.scripts.translations_to_branch import (
    ExportTranslationsToBranch,
    )


class GruesomeException(Exception):
    """CPU on fire.  Or some other kind of failure."""


class TestExportTranslationsToBranch(TestCaseWithFactory):

    layer = ZopelessAppServerLayer

    def _filterOutput(self, output):
        """Remove DEBUG lines from output."""
        return '\n'.join([
            line for line in output.splitlines()
            if not line.startswith('DEBUG')])

    def test_translations_export_to_branch(self):
        # End-to-end test of the script doing its work.

        # Set up a server for hosted branches.
        self.useBzrBranches(direct_database=False)

        # Set up a product and translatable series.
        product = self.factory.makeProduct(name='committobranch')
        product = removeSecurityProxy(product)
        series = product.getSeries('trunk')

        # Set up a translations_branch for the series.
        db_branch, tree = self.create_branch_and_tree(product=product)
        removeSecurityProxy(db_branch).last_scanned_id = 'null:'
        product.official_rosetta = True
        series.translations_branch = db_branch

        # Set up a template & Dutch translation for the series.
        template = self.factory.makePOTemplate(
            productseries=series, owner=product.owner, name='foo',
            path='po/messages.pot')
        template = removeSecurityProxy(template)
        potmsgset = self.factory.makePOTMsgSet(
            template, singular='Hello World', sequence=1)
        pofile = self.factory.makePOFile(
            'nl', potemplate=template, owner=product.owner)
        self.factory.makeTranslationMessage(
            pofile=pofile, potmsgset=potmsgset,
            translator=product.owner, reviewer=product.owner,
            translations=['Hallo Wereld'])

        # Make all this visible to the script we're about to run.
        transaction.commit()

        # Run The Script.
        retcode, stdout, stderr = run_script(
            'cronscripts/translations-export-to-branch.py', ['-vvv'])

        self.assertEqual('', stdout)
        self.assertEqual(
            'INFO    '
            'Creating lockfile: '
            '/var/lock/launchpad-translations-export-to-branch.lock\n'
            'INFO    Exporting to translations branches.\n'
            'INFO    Exporting Committobranch trunk series.\n'
            'INFO    '
            'Processed 1 item(s); 0 failure(s), 0 unpushed branch(es).',
            self._filterOutput(stderr))
        self.assertIn('No previous translations commit found.', stderr)
        self.assertEqual(0, retcode)

        # The branch now contains a snapshot of the translation.  (Only
        # one file: the Dutch translation we set up earlier).
        branch_contents = map_branch_contents(db_branch.getBzrBranch())
        expected_contents = {
            'po/nl.po': """
                # Dutch translation for .*
                # Copyright .*
                (?:#.*$
                )*msgid ""
                msgstr ""
                (?:"[^"]*"
                )*
                msgid "Hello World"
                msgstr "Hallo Wereld"\n""",
        }

        branch_filenames = set(branch_contents.iterkeys())
        expected_filenames = set(expected_contents.iterkeys())

        unexpected_filenames = branch_filenames - expected_filenames
        self.assertEqual(set(), unexpected_filenames)

        missing_filenames = expected_filenames - branch_filenames
        self.assertEqual(set(), missing_filenames)

        for filename, expected in expected_contents.iteritems():
            contents = branch_contents[filename].lstrip('\n')
            pattern = dedent(expected.lstrip('\n'))
            if not re.match(pattern, contents, re.MULTILINE):
                self.assertEqual(pattern, contents)

        # If we run the script again at this point, it won't export
        # anything because it sees that the POFile has not been changed
        # since the last export.
        retcode, stdout, stderr = run_script(
            'cronscripts/translations-export-to-branch.py',
            ['-vvv', '--no-fudge'])
        self.assertEqual(0, retcode)
        self.assertIn('Last commit was at', stderr)
        self.assertIn(
            "Processed 1 item(s); 0 failure(s), 0 unpushed branch(es).",
            stderr)
        self.assertEqual(
            None, re.search("INFO\s+Committed [0-9]+ file", stderr))

    def test_exportToBranches_handles_nonascii_exceptions(self):
        # There's an exception handler in _exportToBranches that must
        # cope well with non-ASCII exception strings.
        productseries = self.factory.makeProductSeries()
        exporter = ExportTranslationsToBranch(test_args=[])
        exporter.logger = QuietFakeLogger()
        boom = u'\u2639'
        exporter._exportToBranch = FakeMethod(failure=GruesomeException(boom))

        self.becomeDbUser('translationstobranch')

        exporter._exportToBranches([productseries])

        self.assertEqual(1, exporter._exportToBranch.call_count)

        exporter.logger.output_file.seek(0)
        message = exporter.logger.output_file.read()
        self.assertTrue(message.startswith("ERROR"))
        self.assertTrue("GruesomeException" in message)

    def test_exportToBranches_handles_unpushed_branches(self):
        # bzrlib raises NotBranchError when accessing a nonexistent
        # branch.  The exporter deals with that by calling
        # _handleUnpushedBranch.
        exporter = ExportTranslationsToBranch(test_args=[])
        exporter.logger = QuietFakeLogger()
        productseries = self.factory.makeProductSeries()
        productseries.translations_branch = self.factory.makeBranch()

        self.becomeDbUser('translationstobranch')

        # _handleUnpushedBranch is called if _exportToBranch raises
        # NotBranchError.
        exporter._handleUnpushedBranch = FakeMethod()
        exporter._exportToBranch = FakeMethod(failure=NotBranchError("No!"))
        exporter._exportToBranches([productseries])
        self.assertEqual(1, exporter._handleUnpushedBranch.call_count)

        # This does not happen if the export succeeds.
        exporter._handleUnpushedBranch = FakeMethod()
        exporter._exportToBranch = FakeMethod()
        exporter._exportToBranches([productseries])
        self.assertEqual(0, exporter._handleUnpushedBranch.call_count)

        # Nor does it happen if the export fails in some other way.
        exporter._handleUnpushedBranch = FakeMethod()
        exporter._exportToBranch = FakeMethod(failure=IndexError("Ayyeee!"))
        exporter._exportToBranches([productseries])
        self.assertEqual(0, exporter._handleUnpushedBranch.call_count)

    def test_handleUnpushedBranch_mails_branch_owner(self):
        exporter = ExportTranslationsToBranch(test_args=[])
        exporter.logger = QuietFakeLogger()
        productseries = self.factory.makeProductSeries()
        email = self.factory.getUniqueEmailAddress()
        branch_owner = self.factory.makePerson(email=email)
        productseries.translations_branch = self.factory.makeBranch(
            owner=branch_owner)
        exporter._exportToBranch = FakeMethod(failure=NotBranchError("Ow"))
        exporter._sendMail = FakeMethod()

        self.becomeDbUser('translationstobranch')

        exporter._exportToBranches([productseries])

        self.assertEqual(1, exporter._sendMail.call_count)
        (sender, recipients, subject, text), kwargs = (
            exporter._sendMail.calls[-1])
        self.assertIn(config.canonical.noreply_from_address, sender)
        self.assertIn(email, recipients)
        self.assertEqual(
            "Launchpad: translations branch has not been set up.", subject)

        self.assertIn(
            "problem with translations branch synchronization", text)
        self.assertIn(productseries.title, text)
        self.assertIn(productseries.translations_branch.bzr_identity, text)
        self.assertIn('bzr push lp://', text)

    def test_handleUnpushedBranch_has_required_privileges(self):
        # Dealing with an unpushed branch is a special code path that
        # was not exercised by the full-script test.  Ensure that it has
        # the database privileges that it requires.
        exporter = ExportTranslationsToBranch(test_args=[])
        exporter.logger = QuietFakeLogger()
        productseries = self.factory.makeProductSeries()
        email = self.factory.getUniqueEmailAddress()
        branch_owner = self.factory.makePerson(email=email)
        productseries.translations_branch = self.factory.makeBranch(
            owner=branch_owner)
        exporter._exportToBranch = FakeMethod(failure=NotBranchError("Ow"))

        self.becomeDbUser('translationstobranch')

        exporter._handleUnpushedBranch(productseries)

        # _handleUnpushedBranch completes successfully.  There are no
        # database changes still pending in the ORM that are going to
        # fail either.
        transaction.commit()

    def test_handleUnpushedBranch_is_privileged_to_contact_team(self):
        # Notifying a branch owner that is a team can require other
        # database privileges.  The script also has these privileges.
        exporter = ExportTranslationsToBranch(test_args=[])
        exporter.logger = QuietFakeLogger()
        productseries = self.factory.makeProductSeries()
        email = self.factory.getUniqueEmailAddress()
        team_member = self.factory.makePerson(email=email)
        branch_owner = self.factory.makeTeam()
        getUtility(ITeamMembershipSet).new(
            team_member, branch_owner, TeamMembershipStatus.APPROVED,
            branch_owner.teamowner)
        productseries.translations_branch = self.factory.makeBranch(
            owner=branch_owner)
        exporter._exportToBranch = FakeMethod(failure=NotBranchError("Ow"))

        self.becomeDbUser('translationstobranch')

        exporter._handleUnpushedBranch(productseries)

        # _handleUnpushedBranch completes successfully.  There are no
        # database changes still pending in the ORM that are going to
        # fail either.
        transaction.commit()


class TestExportToStackedBranch(TestCaseWithFactory):
    """Test workaround for bzr bug 375013."""
    # XXX JeroenVermeulen 2009-10-02 bug=375013: Once bug 375013 is
    # fixed, this entire test can go.
    layer = ZopelessAppServerLayer

    def _setUpBranch(self, db_branch, tree, message):
        """Set the given branch and tree up for use."""
        bzr_branch = tree.branch
        last_revno, last_revision_id = bzr_branch.last_revision_info()
        removeSecurityProxy(db_branch).last_scanned_id = last_revision_id

    def setUp(self):
        super(TestExportToStackedBranch, self).setUp()
        self.useBzrBranches()

        base_branch, base_tree = self.create_branch_and_tree(
            'base', name='base')
        self._setUpBranch(base_branch, base_tree, "Base branch.")

        stacked_branch, stacked_tree = self.create_branch_and_tree(
            'stacked', name='stacked')
        stacked_tree.branch.set_stacked_on_url('/' + base_branch.unique_name)
        stacked_branch.stacked_on = base_branch
        self._setUpBranch(stacked_branch, stacked_tree, "Stacked branch.")

        self.stacked_branch = stacked_branch

    def test_export_to_shared_branch(self):
        # The script knows how to deal with stacked branches.
        # Otherwise, this would fail.
        script = ExportTranslationsToBranch('reupload', test_args=['-q'])
        committer = script._prepareBranchCommit(self.stacked_branch)
        try:
            self.assertNotEqual(None, committer)
            committer.writeFile('x.txt', 'x')
            committer.commit("x!")
        finally:
            committer.unlock()


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
