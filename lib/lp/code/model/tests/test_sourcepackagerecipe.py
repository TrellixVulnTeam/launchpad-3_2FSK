# Copyright 2009, 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the SourcePackageRecipe content type."""

from __future__ import with_statement

__metaclass__ = type

from datetime import datetime, timedelta
import textwrap
import unittest

from bzrlib.plugins.builder.recipe import RecipeParser

from pytz import UTC
from storm.locals import Store

import transaction
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from canonical.testing.layers import DatabaseFunctionalLayer, AppServerLayer

from canonical.launchpad.webapp.authorization import check_permission
from lp.soyuz.interfaces.archive import (
    ArchiveDisabled, ArchivePurpose, CannotUploadToArchive,
    InvalidPocketForPPA)
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.code.interfaces.sourcepackagerecipe import (
    ForbiddenInstruction, ISourcePackageRecipe, ISourcePackageRecipeSource,
    TooNewRecipeFormat, MINIMAL_RECIPE_TEXT)
from lp.code.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuild, ISourcePackageRecipeBuildJob)
from lp.code.model.sourcepackagerecipebuild import (
    SourcePackageRecipeBuildJob)
from lp.code.model.sourcepackagerecipe import (
    NonPPABuildRequest)
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.job.interfaces.job import (
    IJob, JobStatus)
from lp.soyuz.model.processor import ProcessorFamily
from lp.testing import (
    ANONYMOUS, launchpadlib_for, login, login_person, person_logged_in,
    TestCaseWithFactory, ws_object)


class TestSourcePackageRecipe(TestCaseWithFactory):
    """Tests for `SourcePackageRecipe` objects."""

    layer = DatabaseFunctionalLayer

    def makeSourcePackageRecipeFromBuilderRecipe(self, builder_recipe):
        """Make a SourcePackageRecipe from a recipe with arbitrary other data.
        """
        registrant = self.factory.makePerson()
        owner = self.factory.makeTeam(owner=registrant)
        distroseries = self.factory.makeDistroSeries()
        sourcepackagename = self.factory.makeSourcePackageName()
        name = self.factory.getUniqueString(u'recipe-name')
        description = self.factory.getUniqueString(u'recipe-description')
        return getUtility(ISourcePackageRecipeSource).new(
            registrant=registrant, owner=owner, distroseries=[distroseries],
            sourcepackagename=sourcepackagename, name=name,
            description=description, builder_recipe=builder_recipe)

    def test_creation(self):
        # The metadata supplied when a SourcePackageRecipe is created is
        # present on the new object.
        registrant = self.factory.makePerson()
        owner = self.factory.makeTeam(owner=registrant)
        distroseries = self.factory.makeDistroSeries()
        sourcepackagename = self.factory.makeSourcePackageName()
        name = self.factory.getUniqueString(u'recipe-name')
        description = self.factory.getUniqueString(u'recipe-description')
        builder_recipe = self.factory.makeRecipe()
        recipe = getUtility(ISourcePackageRecipeSource).new(
            registrant=registrant, owner=owner, distroseries=[distroseries],
            sourcepackagename=sourcepackagename, name=name,
            description=description, builder_recipe=builder_recipe)
        self.assertEquals(
            (registrant, owner, set([distroseries]), sourcepackagename, name),
            (recipe.registrant, recipe.owner, set(recipe.distroseries),
             recipe.sourcepackagename, recipe.name))

    def test_exists(self):
        # Test ISourcePackageRecipeSource.exists
        recipe = self.factory.makeSourcePackageRecipe()

        self.assertTrue(
            getUtility(ISourcePackageRecipeSource).exists(
                recipe.owner, recipe.name))

        self.assertFalse(
            getUtility(ISourcePackageRecipeSource).exists(
                recipe.owner, u'daily'))

    def test_source_implements_interface(self):
        # The SourcePackageRecipe class implements ISourcePackageRecipeSource.
        self.assertProvides(
            getUtility(ISourcePackageRecipeSource),
            ISourcePackageRecipeSource)

    def test_recipe_implements_interface(self):
        # SourcePackageRecipe objects implement ISourcePackageRecipe.
        recipe = self.makeSourcePackageRecipeFromBuilderRecipe(
            self.factory.makeRecipe())
        self.assertProvides(recipe, ISourcePackageRecipe)

    def test_base_branch(self):
        # When a recipe is created, we can access its base branch.
        branch = self.factory.makeAnyBranch()
        builder_recipe = self.factory.makeRecipe(branch)
        sp_recipe = self.makeSourcePackageRecipeFromBuilderRecipe(
            builder_recipe)
        self.assertEquals(branch, sp_recipe.base_branch)

    def test_branch_links_created(self):
        # When a recipe is created, we can query it for links to the branch
        # it references.
        branch = self.factory.makeAnyBranch()
        builder_recipe = self.factory.makeRecipe(branch)
        sp_recipe = self.makeSourcePackageRecipeFromBuilderRecipe(
            builder_recipe)
        self.assertEquals([branch], list(sp_recipe.getReferencedBranches()))

    def test_multiple_branch_links_created(self):
        # If a recipe links to more than one branch, getReferencedBranches()
        # returns all of them.
        branch1 = self.factory.makeAnyBranch()
        branch2 = self.factory.makeAnyBranch()
        builder_recipe = self.factory.makeRecipe(branch1, branch2)
        sp_recipe = self.makeSourcePackageRecipeFromBuilderRecipe(
            builder_recipe)
        self.assertEquals(
            sorted([branch1, branch2]),
            sorted(sp_recipe.getReferencedBranches()))

    def test_random_user_cant_edit(self):
        # An arbitrary user can't set attributes.
        branch1 = self.factory.makeAnyBranch()
        builder_recipe1 = self.factory.makeRecipe(branch1)
        sp_recipe = self.makeSourcePackageRecipeFromBuilderRecipe(
            builder_recipe1)
        branch2 = self.factory.makeAnyBranch()
        builder_recipe2 = self.factory.makeRecipe(branch2)
        login_person(self.factory.makePerson())
        self.assertRaises(
            Unauthorized, setattr, sp_recipe, 'builder_recipe',
            builder_recipe2)

    def test_set_recipe_text_resets_branch_references(self):
        # When the recipe_text is replaced, getReferencedBranches returns
        # (only) the branches referenced by the new recipe.
        branch1 = self.factory.makeAnyBranch()
        builder_recipe1 = self.factory.makeRecipe(branch1)
        sp_recipe = self.makeSourcePackageRecipeFromBuilderRecipe(
            builder_recipe1)
        branch2 = self.factory.makeAnyBranch()
        builder_recipe2 = self.factory.makeRecipe(branch2)
        login_person(sp_recipe.owner.teamowner)
        #import pdb; pdb.set_trace()
        sp_recipe.builder_recipe = builder_recipe2
        self.assertEquals([branch2], list(sp_recipe.getReferencedBranches()))

    def test_rejects_run_command(self):
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s
        run touch test
        ''' % dict(base=self.factory.makeAnyBranch().bzr_identity)
        parser = RecipeParser(textwrap.dedent(recipe_text))
        builder_recipe = parser.parse()
        self.assertRaises(
            ForbiddenInstruction,
            self.makeSourcePackageRecipeFromBuilderRecipe, builder_recipe)

    def test_run_rejected_without_mangling_recipe(self):
        branch1 = self.factory.makeAnyBranch()
        builder_recipe1 = self.factory.makeRecipe(branch1)
        sp_recipe = self.makeSourcePackageRecipeFromBuilderRecipe(
            builder_recipe1)
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s
        run touch test
        ''' % dict(base=self.factory.makeAnyBranch().bzr_identity)
        parser = RecipeParser(textwrap.dedent(recipe_text))
        builder_recipe2 = parser.parse()
        login_person(sp_recipe.owner.teamowner)
        self.assertRaises(
            ForbiddenInstruction, setattr, sp_recipe, 'builder_recipe',
            builder_recipe2)
        self.assertEquals([branch1], list(sp_recipe.getReferencedBranches()))

    def test_reject_newer_formats(self):
        builder_recipe = self.factory.makeRecipe()
        builder_recipe.format = 0.3
        self.assertRaises(
            TooNewRecipeFormat,
            self.makeSourcePackageRecipeFromBuilderRecipe, builder_recipe)

    def test_requestBuild(self):
        recipe = self.factory.makeSourcePackageRecipe()
        (distroseries,) = list(recipe.distroseries)
        ppa = self.factory.makeArchive()
        build = recipe.requestBuild(ppa, ppa.owner, distroseries,
                PackagePublishingPocket.RELEASE)
        self.assertProvides(build, ISourcePackageRecipeBuild)
        self.assertEqual(build.archive, ppa)
        self.assertEqual(build.distroseries, distroseries)
        self.assertEqual(build.requester, ppa.owner)
        store = Store.of(build)
        store.flush()
        build_job = store.find(SourcePackageRecipeBuildJob,
                SourcePackageRecipeBuildJob.build_id==build.id).one()
        self.assertProvides(build_job, ISourcePackageRecipeBuildJob)
        self.assertTrue(build_job.virtualized)
        job = build_job.job
        self.assertProvides(job, IJob)
        self.assertEquals(job.status, JobStatus.WAITING)
        build_queue = store.find(BuildQueue, BuildQueue.job==job.id).one()
        self.assertProvides(build_queue, IBuildQueue)
        self.assertTrue(build_queue.virtualized)

    def test_requestBuildRejectsNotPPA(self):
        recipe = self.factory.makeSourcePackageRecipe()
        not_ppa = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        (distroseries,) = list(recipe.distroseries)
        self.assertRaises(NonPPABuildRequest, recipe.requestBuild, not_ppa,
                not_ppa.owner, distroseries, PackagePublishingPocket.RELEASE)

    def test_requestBuildRejectsNoPermission(self):
        recipe = self.factory.makeSourcePackageRecipe()
        ppa = self.factory.makeArchive()
        requester = self.factory.makePerson()
        (distroseries,) = list(recipe.distroseries)
        self.assertRaises(CannotUploadToArchive, recipe.requestBuild, ppa,
                requester, distroseries, PackagePublishingPocket.RELEASE)

    def test_requestBuildRejectsInvalidPocket(self):
        recipe = self.factory.makeSourcePackageRecipe()
        ppa = self.factory.makeArchive()
        (distroseries,) = list(recipe.distroseries)
        self.assertRaises(InvalidPocketForPPA, recipe.requestBuild, ppa,
                ppa.owner, distroseries, PackagePublishingPocket.BACKPORTS)

    def test_requestBuildRejectsDisabledArchive(self):
        recipe = self.factory.makeSourcePackageRecipe()
        ppa = self.factory.makeArchive()
        removeSecurityProxy(ppa).disable()
        (distroseries,) = list(recipe.distroseries)
        self.assertRaises(ArchiveDisabled, recipe.requestBuild, ppa,
                ppa.owner, distroseries, PackagePublishingPocket.RELEASE)

    def test_sourcepackagerecipe_description(self):
        """Ensure that the SourcePackageRecipe has a proper description."""
        description = u'The whoozits and whatzits.'
        source_package_recipe = self.factory.makeSourcePackageRecipe(
            description=description)
        self.assertEqual(description, source_package_recipe.description)

    def test_distroseries(self):
        """Test that the distroseries behaves as a set."""
        recipe = self.factory.makeSourcePackageRecipe()
        distroseries = self.factory.makeDistroSeries()
        (old_distroseries,) = recipe.distroseries
        recipe.distroseries.add(distroseries)
        self.assertEqual(
            set([distroseries, old_distroseries]), set(recipe.distroseries))
        recipe.distroseries.remove(distroseries)
        self.assertEqual([old_distroseries], list(recipe.distroseries))
        recipe.distroseries.clear()
        self.assertEqual([], list(recipe.distroseries))

    def test_build_daily(self):
        """Test that build_daily behaves as a bool."""
        recipe = self.factory.makeSourcePackageRecipe()
        self.assertFalse(recipe.build_daily)
        login_person(recipe.owner)
        recipe.build_daily = True
        self.assertTrue(recipe.build_daily)

    def test_view_public(self):
        """Anyone can view a recipe with public branches."""
        owner = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(owner=owner)
        with person_logged_in(owner):
            recipe = self.factory.makeSourcePackageRecipe(branches=[branch])
            self.assertTrue(check_permission('launchpad.View', recipe))
        with person_logged_in(self.factory.makePerson()):
            self.assertTrue(check_permission('launchpad.View', recipe))
        self.assertTrue(check_permission('launchpad.View', recipe))

    def test_view_private(self):
        """Recipes with private branches are restricted."""
        owner = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(owner=owner, private=True)
        with person_logged_in(owner):
            recipe = self.factory.makeSourcePackageRecipe(branches=[branch])
            self.assertTrue(check_permission('launchpad.View', recipe))
        with person_logged_in(self.factory.makePerson()):
            self.assertFalse(check_permission('launchpad.View', recipe))
        self.assertFalse(check_permission('launchpad.View', recipe))

    def test_edit(self):
        """Only the owner can edit a sourcepackagerecipe."""
        recipe = self.factory.makeSourcePackageRecipe()
        self.assertFalse(check_permission('launchpad.Edit', recipe))
        with person_logged_in(self.factory.makePerson()):
            self.assertFalse(check_permission('launchpad.Edit', recipe))
        with person_logged_in(recipe.owner):
            self.assertTrue(check_permission('launchpad.Edit', recipe))

    def test_destroySelf(self):
        """Should destroy associated builds, distroseries, etc."""
        # Recipe should have at least one datainstruction.
        branches = [self.factory.makeBranch() for count in range(2)]
        recipe = self.factory.makeSourcePackageRecipe(branches=branches)
        pending_build = self.factory.makeSourcePackageRecipeBuild(
            recipe=recipe)
        self.factory.makeSourcePackageRecipeBuildJob(
            recipe_build=pending_build)
        past_build = self.factory.makeSourcePackageRecipeBuild(
            recipe=recipe)
        self.factory.makeSourcePackageRecipeBuildJob(
            recipe_build=past_build)
        removeSecurityProxy(past_build).datebuilt = datetime.now(UTC)
        recipe.destroySelf()
        # Show no database constraints were violated
        Store.of(recipe).flush()

    def test_getMedianBuildDuration(self):
        recipe = removeSecurityProxy(self.factory.makeSourcePackageRecipe())
        self.assertIs(None, recipe.getMedianBuildDuration())
        build = removeSecurityProxy(
            self.factory.makeSourcePackageRecipeBuild(recipe=recipe))
        build.buildduration = timedelta(minutes=10)
        self.assertEqual(
            timedelta(minutes=10), recipe.getMedianBuildDuration())
        def addBuild(minutes):
            build = removeSecurityProxy(
                self.factory.makeSourcePackageRecipeBuild(recipe=recipe))
            build.buildduration = timedelta(minutes=minutes)
        addBuild(20)
        self.assertEqual(
            timedelta(minutes=10), recipe.getMedianBuildDuration())
        addBuild(11)
        self.assertEqual(
            timedelta(minutes=11), recipe.getMedianBuildDuration())


class TestRecipeBranchRoundTripping(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestRecipeBranchRoundTripping, self).setUp()
        self.base_branch = self.factory.makeAnyBranch()
        self.nested_branch = self.factory.makeAnyBranch()
        self.merged_branch = self.factory.makeAnyBranch()
        self.branch_identities = {
            'base': self.base_branch.bzr_identity,
            'nested': self.nested_branch.bzr_identity,
            'merged': self.merged_branch.bzr_identity,
            }

    def get_recipe(self, recipe_text):
        builder_recipe = RecipeParser(textwrap.dedent(recipe_text)).parse()
        registrant = self.factory.makePerson()
        owner = self.factory.makeTeam(owner=registrant)
        distroseries = self.factory.makeDistroSeries()
        sourcepackagename = self.factory.makeSourcePackageName()
        name = self.factory.getUniqueString(u'recipe-name')
        description = self.factory.getUniqueString(u'recipe-description')
        recipe = getUtility(ISourcePackageRecipeSource).new(
            registrant=registrant, owner=owner, distroseries=[distroseries],
            sourcepackagename=sourcepackagename, name=name,
            description=description, builder_recipe=builder_recipe)
        return recipe.builder_recipe

    def check_base_recipe_branch(self, branch, url, revspec=None,
            num_child_branches=0, revid=None, deb_version=None):
        self.check_recipe_branch(branch, None, url, revspec=revspec,
                num_child_branches=num_child_branches, revid=revid)
        self.assertEqual(deb_version, branch.deb_version)

    def check_recipe_branch(self, branch, name, url, revspec=None,
            num_child_branches=0, revid=None):
        self.assertEqual(name, branch.name)
        self.assertEqual(url, branch.url)
        self.assertEqual(revspec, branch.revspec)
        self.assertEqual(revid, branch.revid)
        self.assertEqual(num_child_branches, len(branch.child_branches))

    def test_builds_simplest_recipe(self):
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s
        ''' % self.branch_identities
        base_branch = self.get_recipe(recipe_text)
        self.check_base_recipe_branch(
            base_branch, self.base_branch.bzr_identity,
            deb_version='0.1-{revno}')

    def test_builds_recipe_with_merge(self):
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s
        merge bar %(merged)s
        ''' % self.branch_identities
        base_branch = self.get_recipe(recipe_text)
        self.check_base_recipe_branch(
            base_branch, self.base_branch.bzr_identity, num_child_branches=1,
            deb_version='0.1-{revno}')
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(
            child_branch, "bar", self.merged_branch.bzr_identity)

    def test_builds_recipe_with_nest(self):
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s
        nest bar %(nested)s baz
        ''' % self.branch_identities
        base_branch = self.get_recipe(recipe_text)
        self.check_base_recipe_branch(
            base_branch, self.base_branch.bzr_identity, num_child_branches=1,
            deb_version='0.1-{revno}')
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(
            child_branch, "bar", self.nested_branch.bzr_identity)

    def test_builds_recipe_with_nest_then_merge(self):
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s
        nest bar %(nested)s baz
        merge zam %(merged)s
        ''' % self.branch_identities
        base_branch = self.get_recipe(recipe_text)
        self.check_base_recipe_branch(
            base_branch, self.base_branch.bzr_identity, num_child_branches=2,
            deb_version='0.1-{revno}')
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(
            child_branch, "bar", self.nested_branch.bzr_identity)
        child_branch, location = base_branch.child_branches[1].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(
            child_branch, "zam", self.merged_branch.bzr_identity)

    def test_builds_recipe_with_merge_then_nest(self):
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s
        merge zam %(merged)s
        nest bar %(nested)s baz
        ''' % self.branch_identities
        base_branch = self.get_recipe(recipe_text)
        self.check_base_recipe_branch(
            base_branch, self.base_branch.bzr_identity, num_child_branches=2,
            deb_version='0.1-{revno}')
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(
            child_branch, "zam", self.merged_branch.bzr_identity)
        child_branch, location = base_branch.child_branches[1].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(
            child_branch, "bar", self.nested_branch.bzr_identity)

    def test_builds_a_merge_in_to_a_nest(self):
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s
        nest bar %(nested)s baz
          merge zam %(merged)s
        ''' % self.branch_identities
        base_branch = self.get_recipe(recipe_text)
        self.check_base_recipe_branch(
            base_branch, self.base_branch.bzr_identity, num_child_branches=1,
            deb_version='0.1-{revno}')
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(
            child_branch, "bar", self.nested_branch.bzr_identity,
            num_child_branches=1)
        child_branch, location = child_branch.child_branches[0].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(
            child_branch, "zam", self.merged_branch.bzr_identity)

    def tests_builds_nest_into_a_nest(self):
        nested2 = self.factory.makeAnyBranch()
        self.branch_identities['nested2'] = nested2.bzr_identity
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s
        nest bar %(nested)s baz
          nest zam %(nested2)s zoo
        ''' % self.branch_identities
        base_branch = self.get_recipe(recipe_text)
        self.check_base_recipe_branch(
            base_branch, self.base_branch.bzr_identity, num_child_branches=1,
            deb_version='0.1-{revno}')
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(
            child_branch, "bar", self.nested_branch.bzr_identity,
            num_child_branches=1)
        child_branch, location = child_branch.child_branches[0].as_tuple()
        self.assertEqual("zoo", location)
        self.check_recipe_branch(child_branch, "zam", nested2.bzr_identity)

    def tests_builds_recipe_with_revspecs(self):
        recipe_text = '''\
        # bzr-builder format 0.2 deb-version 0.1-{revno}
        %(base)s revid:a
        nest bar %(nested)s baz tag:b
        merge zam %(merged)s 2
        ''' % self.branch_identities
        base_branch = self.get_recipe(recipe_text)
        self.check_base_recipe_branch(
            base_branch, self.base_branch.bzr_identity, num_child_branches=2,
            revspec="revid:a", deb_version='0.1-{revno}')
        instruction = base_branch.child_branches[0]
        child_branch = instruction.recipe_branch
        location = instruction.nest_path
        self.assertEqual("baz", location)
        self.check_recipe_branch(
            child_branch, "bar", self.nested_branch.bzr_identity,
            revspec="tag:b")
        child_branch, location = base_branch.child_branches[1].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(
            child_branch, "zam", self.merged_branch.bzr_identity, revspec="2")


class TestWebservice(TestCaseWithFactory):

    layer = AppServerLayer

    def makeRecipeText(self):
        branch = self.factory.makeBranch()
        return MINIMAL_RECIPE_TEXT % branch.bzr_identity

    def makeRecipe(self, user=None, owner=None, recipe_text=None):
        if user is None:
            user = self.factory.makePerson()
        if owner is None:
            owner = user
        db_distroseries = self.factory.makeDistroSeries()
        if recipe_text is None:
            recipe_text = self.makeRecipeText()
        launchpad = launchpadlib_for('test', user,
                service_root="http://api.launchpad.dev:8085")
        login(ANONYMOUS)
        distroseries = ws_object(launchpad, db_distroseries)
        ws_owner = ws_object(launchpad, owner)
        recipe = ws_owner.createRecipe(
            name='toaster-1', sourcepackagename='toaster',
            description='a recipe', distroseries=[distroseries.self_link],
            recipe_text=recipe_text)
        # at the moment, distroseries is not exposed in the API.
        transaction.commit()
        db_recipe = owner.getRecipe(name=u'toaster-1')
        self.assertEqual(set([db_distroseries]), set(db_recipe.distroseries))
        return recipe, ws_owner, launchpad

    def test_createRecipe(self):
        """Ensure recipe creation works."""
        team = self.factory.makeTeam()
        recipe_text = self.makeRecipeText()
        recipe, user = self.makeRecipe(user=team.teamowner, owner=team,
            recipe_text=recipe_text)[:2]
        self.assertEqual(team.name, recipe.owner.name)
        self.assertEqual(team.teamowner.name, recipe.registrant.name)
        self.assertEqual('toaster-1', recipe.name)
        self.assertEqual(recipe_text, recipe.recipe_text)
        self.assertEqual('toaster', recipe.sourcepackagename)

    def test_recipe_text(self):
        recipe_text2 = self.makeRecipeText()
        recipe = self.makeRecipe()[0]
        recipe.setRecipeText(recipe_text=recipe_text2)
        self.assertEqual(recipe_text2, recipe.recipe_text)

    def test_getRecipe(self):
        """Person.getRecipe returns the named recipe."""
        recipe, user = self.makeRecipe()[:-1]
        self.assertEqual(recipe, user.getRecipe(name=recipe.name))

    def test_requestBuild(self):
        """Build requests can be performed."""
        person = self.factory.makePerson()
        archive = self.factory.makeArchive(owner=person)
        distroseries = self.factory.makeDistroSeries()
        distroseries_i386 = distroseries.newArch(
            'i386', ProcessorFamily.get(1), False, person,
            supports_virtualized=True)
        distroseries.nominatedarchindep = distroseries_i386

        recipe, user, launchpad = self.makeRecipe(person)
        distroseries = ws_object(launchpad, distroseries)
        archive = ws_object(launchpad, archive)
        recipe.requestBuild(
            archive=archive, distroseries=distroseries,
            pocket=PackagePublishingPocket.RELEASE.title)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
