# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from canonical.testing.layers import DatabaseFunctionalLayer
from lp.bugs.mail.commands import (
    AffectsEmailCommand,
    )
from lp.services.mail.interfaces import BugTargetNotFound
from lp.testing import (
    login_celebrity,
    login_person,
    TestCaseWithFactory,
    )


class AffectsEmailCommandTestCase(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test__splitPath_with_slashes(self):
        self.assertEqual(
            ('foo', 'bar/baz'), AffectsEmailCommand._splitPath('foo/bar/baz'))

    def test__splitPath_no_slashes(self):
        self.assertEqual(
            ('foo', ''), AffectsEmailCommand._splitPath('foo'))

    def test__normalizePath_leading_slash(self):
        self.assertEqual(
            'foo/bar', AffectsEmailCommand._normalizePath('/foo/bar'))

    def test__normalizePath_distros(self):
        self.assertEqual(
            'foo/bar', AffectsEmailCommand._normalizePath('/distros/foo/bar'))

    def test__normalizePath_products(self):
        self.assertEqual(
            'foo/bar',
            AffectsEmailCommand._normalizePath('/products/foo/bar'))

    def test_getBugTarget_no_pillar_error(self):
        message = "There is no project named 'fnord' registered in Launchpad."
        self.assertRaisesWithContent(
            BugTargetNotFound, message,
            AffectsEmailCommand.getBugTarget, 'fnord')

    def test_getBugTarget_project_group_error(self):
        owner = self.factory.makePerson()
        login_person(owner)
        project_group = self.factory.makeProject(name='fnord', owner=owner)
        project_1 = self.factory.makeProduct(name='pting', owner=owner)
        project_1.project = project_group
        project_2 = self.factory.makeProduct(name='snarf', owner=owner)
        project_2.project = project_group
        message = (
            "fnord is a group of projects. To report a bug, you need to "
            "specify which of these projects the bug applies to: "
            "pting, snarf")
        self.assertRaisesWithContent(
            BugTargetNotFound, message,
            AffectsEmailCommand.getBugTarget, 'fnord')

    def test_getBugTarget_deactivated_project_error(self):
        project = self.factory.makeProduct(name='fnord')
        login_celebrity('admin')
        project.active = False
        message = "There is no project named 'fnord' registered in Launchpad."
        self.assertRaisesWithContent(
            BugTargetNotFound, message,
            AffectsEmailCommand.getBugTarget, 'fnord')

    def test_getBugTarget_project(self):
        project = self.factory.makeProduct(name='fnord')
        self.assertEqual(project, AffectsEmailCommand.getBugTarget('fnord'))

    def test_getBugTarget_no_project_series_error(self):
        self.factory.makeProduct(name='fnord')
        message = "Fnord doesn't have a series named 'pting'."
        self.assertRaisesWithContent(
            BugTargetNotFound, message,
            AffectsEmailCommand.getBugTarget, 'fnord/pting')

    def test_getBugTarget_project_series(self):
        project = self.factory.makeProduct(name='fnord')
        series = self.factory.makeProductSeries(name='pting', product=project)
        self.assertEqual(
            series, AffectsEmailCommand.getBugTarget('fnord/pting'))

    def test_getBugTarget_product_extra_path_error(self):
        product = self.factory.makeProduct(name='fnord')
        self.factory.makeProductSeries(name='pting', product=product)
        message = "Unexpected path components: snarf"
        self.assertRaisesWithContent(
            BugTargetNotFound, message,
            AffectsEmailCommand.getBugTarget, 'fnord/pting/snarf')

    def test_getBugTarget_no_series_or_package_error(self):
        self.factory.makeDistribution(name='fnord')
        message = (
            "Fnord doesn't have a series or source package named 'pting'.")
        self.assertRaisesWithContent(
            BugTargetNotFound, message,
            AffectsEmailCommand.getBugTarget, 'fnord/pting')

    def test_getBugTarget_distribution(self):
        distribution = self.factory.makeDistribution(name='fnord')
        self.assertEqual(
            distribution, AffectsEmailCommand.getBugTarget('fnord'))

    def test_getBugTarget_distroseries(self):
        distribution = self.factory.makeDistribution(name='fnord')
        series = self.factory.makeDistroSeries(
            name='pting', distribution=distribution)
        self.assertEqual(
            series, AffectsEmailCommand.getBugTarget('fnord/pting'))

    def test_getBugTarget_source_package(self):
        distribution = self.factory.makeDistribution(name='fnord')
        series = self.factory.makeDistroSeries(
            name='pting', distribution=distribution)
        package = self.factory.makeSourcePackage(
            sourcepackagename='snarf', distroseries=series, publish=True)
        self.assertEqual(
            package, AffectsEmailCommand.getBugTarget('fnord/pting/snarf'))

    def test_getBugTarget_distribution_source_package(self):
        distribution = self.factory.makeDistribution(name='fnord')
        series = self.factory.makeDistroSeries(
            name='pting', distribution=distribution)
        package = self.factory.makeSourcePackage(
            sourcepackagename='snarf', distroseries=series, publish=True)
        dsp = distribution.getSourcePackage(package.name)
        self.assertEqual(
            dsp, AffectsEmailCommand.getBugTarget('fnord/snarf'))

    def test_getBugTarget_distribution_extra_path_error(self):
        distribution = self.factory.makeDistribution(name='fnord')
        series = self.factory.makeDistroSeries(
            name='pting', distribution=distribution)
        self.factory.makeSourcePackage(
            sourcepackagename='snarf', distroseries=series, publish=True)
        message = "Unexpected path components: thrup"
        self.assertRaisesWithContent(
            BugTargetNotFound, message,
            AffectsEmailCommand.getBugTarget, 'fnord/pting/snarf/thrup')
