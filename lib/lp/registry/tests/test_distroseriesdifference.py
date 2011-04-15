# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Model tests for the DistroSeriesDifference class."""

__metaclass__ = type

from storm.exceptions import IntegrityError
from storm.store import Store
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.testing import verifyObject
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.registry.enum import (
    DistroSeriesDifferenceStatus,
    DistroSeriesDifferenceType,
    )
from lp.registry.errors import (
    DistroSeriesDifferenceError,
    NotADerivedSeriesError,
    )
from lp.registry.interfaces.distroseriesdifference import (
    IDistroSeriesDifference,
    IDistroSeriesDifferenceSource,
    )
from lp.services.propertycache import get_property_cache
from lp.soyuz.enums import PackageDiffStatus
from lp.soyuz.interfaces.publishing import PackagePublishingStatus
from lp.testing import (
    celebrity_logged_in,
    person_logged_in,
    TestCaseWithFactory,
    )


class DistroSeriesDifferenceTestCase(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def test_implements_interface(self):
        # The implementation implements the interface correctly.
        ds_diff = self.factory.makeDistroSeriesDifference()
        # Flush the store to ensure db constraints are triggered.
        Store.of(ds_diff).flush()

        verifyObject(IDistroSeriesDifference, ds_diff)

    def test_source_implements_interface(self):
        # The utility for creating differences implements its interface.
        utility = getUtility(IDistroSeriesDifferenceSource)

        verifyObject(IDistroSeriesDifferenceSource, utility)

    def test_new_non_derived_series(self):
        # A DistroSeriesDifference cannot be created with a non-derived
        # series.
        distro_series = self.factory.makeDistroSeries()
        source_package_name = self.factory.makeSourcePackageName('myfoo')
        distroseriesdifference_factory = getUtility(
            IDistroSeriesDifferenceSource)

        self.assertRaises(
            NotADerivedSeriesError, distroseriesdifference_factory.new,
            distro_series, source_package_name)

    def test_source_pub(self):
        # The related source pub is returned for the derived series.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew")

        self.assertEqual(
            'foonew', ds_diff.source_pub.source_package_name)
        self.assertEqual(
            ds_diff.derived_series, ds_diff.source_pub.distroseries)

    def test_source_pub_gets_latest_pending(self):
        # The most recent publication is always returned, even if its pending.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew")
        pending_pub = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=ds_diff.source_package_name,
            distroseries=ds_diff.derived_series,
            status=PackagePublishingStatus.PENDING)

        self.assertEqual(pending_pub, ds_diff.source_pub)

    def test_source_pub_returns_none(self):
        # None is returned when there is no source pub.
        ds_diff = self.factory.makeDistroSeriesDifference(
            difference_type=(
                DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES))

        self.assertIs(None, ds_diff.source_pub)

    def test_parent_source_pub(self):
        # The related source pub for the parent distro series is returned.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew")

        self.assertEqual(
            'foonew', ds_diff.parent_source_pub.source_package_name)
        self.assertEqual(
            ds_diff.derived_series.parent_series,
            ds_diff.parent_source_pub.distroseries)

    def test_parent_source_pub_gets_latest_pending(self):
        # The most recent publication is always returned, even if its pending.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew")
        pending_pub = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=ds_diff.source_package_name,
            distroseries=ds_diff.derived_series.parent_series,
            status=PackagePublishingStatus.PENDING)

        self.assertEqual(pending_pub, ds_diff.parent_source_pub)

    def test_source_version(self):
        # The version of the source in the derived series is returned.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew")

        self.assertEqual(
            ds_diff.source_pub.source_package_version, ds_diff.source_version)

    def test_source_version_none(self):
        # None is returned for source_version when there is no source pub.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew",
            difference_type=(
                DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES))

        self.assertEqual(None, ds_diff.source_version)

    def test_update_resolves_difference(self):
        # Status is set to resolved when versions match.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew",
            versions={
                'parent': '1.0',
                'derived': '0.9',
                })
        new_derived_pub = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=ds_diff.source_package_name,
            distroseries=ds_diff.derived_series,
            status=PackagePublishingStatus.PENDING,
            version='1.0')

        was_updated = ds_diff.update()

        self.assertTrue(was_updated)
        self.assertEqual(
            DistroSeriesDifferenceStatus.RESOLVED,
            ds_diff.status)

    def test_update_re_opens_difference(self):
        # The status of a resolved difference will updated with new
        # uploads.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew",
            versions={
                'parent': '1.0',
                'derived': '1.0',
                },
            status=DistroSeriesDifferenceStatus.RESOLVED)
        new_derived_pub = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=ds_diff.source_package_name,
            distroseries=ds_diff.derived_series,
            status=PackagePublishingStatus.PENDING,
            version='1.1')

        was_updated = ds_diff.update()

        self.assertTrue(was_updated)
        self.assertEqual(
            DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
            ds_diff.status)

    def test_update_new_version_doesnt_change_status(self):
        # Uploading a new (different) version does not update the
        # status of the record, but the version is updated.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew",
            versions={
                'parent': '1.0',
                'derived': '0.9',
                })
        new_derived_pub = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=ds_diff.source_package_name,
            distroseries=ds_diff.derived_series,
            status=PackagePublishingStatus.PENDING,
            version='1.1')

        was_updated = ds_diff.update()

        self.assertTrue(was_updated)
        self.assertEqual(
            DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
            ds_diff.status)
        self.assertEqual('1.1', ds_diff.source_version)

    def test_update_changes_type(self):
        # The type of difference is updated when appropriate.
        # In this case, a package that was previously only in the
        # derived series (UNIQUE_TO_DERIVED_SERIES), is uploaded
        # to the parent series with a different version.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew",
            versions={
                'derived': '0.9',
                },
            difference_type=(
                DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES))
        new_parent_pub = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=ds_diff.source_package_name,
            distroseries=ds_diff.derived_series.parent_series,
            status=PackagePublishingStatus.PENDING,
            version='1.1')

        was_updated = ds_diff.update()

        self.assertTrue(was_updated)
        self.assertEqual(
            DistroSeriesDifferenceType.DIFFERENT_VERSIONS,
            ds_diff.difference_type)

    def test_update_removes_version_blacklist(self):
        # A blacklist on a version of a package is removed when a new
        # version is uploaded to the derived series.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew",
            versions={
                'derived': '0.9',
                },
            difference_type=(
                DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES),
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)
        new_derived_pub = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=ds_diff.source_package_name,
            distroseries=ds_diff.derived_series,
            status=PackagePublishingStatus.PENDING,
            version='1.1')

        was_updated = ds_diff.update()

        self.assertTrue(was_updated)
        self.assertEqual(
            DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
            ds_diff.status)

    def test_update_does_not_remove_permanent_blacklist(self):
        # A permanent blacklist is not removed when a new version
        # is uploaded, even if it resolves the difference (as later
        # uploads could re-create a difference, and we want to keep
        # the blacklist).
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew",
            versions={
                'derived': '0.9',
                'parent': '1.0',
                },
            status=DistroSeriesDifferenceStatus.BLACKLISTED_ALWAYS)
        new_derived_pub = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=ds_diff.source_package_name,
            distroseries=ds_diff.derived_series,
            status=PackagePublishingStatus.PENDING,
            version='1.0')

        was_updated = ds_diff.update()

        self.assertTrue(was_updated)
        self.assertEqual(
            DistroSeriesDifferenceStatus.BLACKLISTED_ALWAYS,
            ds_diff.status)

    def test_title(self):
        # The title is a friendly description of the difference.
        parent_series = self.factory.makeDistroSeries(name="lucid")
        derived_series = self.factory.makeDistroSeries(
            parent_series=parent_series, name="derilucid")
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew", derived_series=derived_series,
            versions={
                'parent': '1.0',
                'derived': '0.9',
                })

        self.assertEqual(
            "Difference between distroseries 'Lucid' and 'Derilucid' "
            "for package 'foonew' (1.0/0.9)",
            ds_diff.title)

    def test_addComment(self):
        # Adding a comment creates a new DistroSeriesDifferenceComment
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foonew")

        person = self.factory.makePerson()
        with person_logged_in(person):
            dsd_comment = ds_diff.addComment(
                person, "Wait until version 2.1")

        self.assertEqual(ds_diff, dsd_comment.distro_series_difference)

    def test_getComments(self):
        # All comments for this difference are returned with the
        # most recent comment first.
        ds_diff = self.factory.makeDistroSeriesDifference()

        person = self.factory.makePerson()
        with person_logged_in(person):
            dsd_comment = ds_diff.addComment(
                person, "Wait until version 2.1")
            dsd_comment_2 = ds_diff.addComment(
                person, "Wait until version 2.1")

        self.assertEqual(
            [dsd_comment_2, dsd_comment], list(ds_diff.getComments()))

    def test_addComment_for_owners(self):
        # Comments can be added by any of the owners of the derived
        # series.
        ds_diff = self.factory.makeDistroSeriesDifference()

        person = self.factory.makePerson()
        with person_logged_in(person):
            self.assertTrue(check_permission('launchpad.Edit', ds_diff))
            diff_comment = ds_diff.addComment(
                ds_diff.derived_series.owner, "Boo")

    def _setupPackageSets(self, ds_diff, distroseries, nb_packagesets):
        # Helper method to create packages sets.
        packagesets = []
        with celebrity_logged_in('admin'):
            for i in range(nb_packagesets):
                ps = self.factory.makePackageset(
                    packages=[ds_diff.source_package_name],
                    distroseries=distroseries)
                packagesets.append(ps)
        return packagesets

    def test_getParentPackageSets(self):
        # All parent's packagesets are returned ordered alphabetically.
        ds_diff = self.factory.makeDistroSeriesDifference()
        packagesets = self._setupPackageSets(
            ds_diff, ds_diff.derived_series.parent_series, 5)
        parent_packagesets = ds_diff.getParentPackageSets()
        self.assertEquals(
            sorted([packageset.name for packageset in packagesets]),
            [packageset.name for packageset in parent_packagesets])

    def test_getPackageSets(self):
        # All the packagesets are returned ordered alphabetically.
        ds_diff = self.factory.makeDistroSeriesDifference()
        packagesets = self._setupPackageSets(
            ds_diff, ds_diff.derived_series, 5)
        self.assertEquals(
            sorted([packageset.name for packageset in packagesets]),
            [packageset.name for packageset in ds_diff.getPackageSets()])

    def test_blacklist_default(self):
        # By default the current version is blacklisted.
        ds_diff = self.factory.makeDistroSeriesDifference()

        with person_logged_in(self.factory.makePerson()):
            ds_diff.blacklist()

        self.assertEqual(
            DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT,
            ds_diff.status)

    def test_blacklist_all(self):
        # All versions are blacklisted with the all=True param.
        ds_diff = self.factory.makeDistroSeriesDifference()

        with person_logged_in(self.factory.makePerson()):
            ds_diff.blacklist(all=True)

        self.assertEqual(
            DistroSeriesDifferenceStatus.BLACKLISTED_ALWAYS,
            ds_diff.status)

    def test_unblacklist(self):
        # Unblacklisting will return to NEEDS_ATTENTION by default.
        ds_diff = self.factory.makeDistroSeriesDifference(
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)

        with person_logged_in(self.factory.makePerson()):
            ds_diff.unblacklist()

        self.assertEqual(
            DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
            ds_diff.status)

    def test_unblacklist_resolved(self):
        # Status is resolved when unblacklisting a now-resolved difference.
        ds_diff = self.factory.makeDistroSeriesDifference(
            versions={
                'derived': '0.9',
                'parent': '1.0',
                },
            status=DistroSeriesDifferenceStatus.BLACKLISTED_ALWAYS)
        new_derived_pub = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=ds_diff.source_package_name,
            distroseries=ds_diff.derived_series,
            status=PackagePublishingStatus.PENDING,
            version='1.0')

        with person_logged_in(self.factory.makePerson()):
            ds_diff.unblacklist()

        self.assertEqual(
            DistroSeriesDifferenceStatus.RESOLVED,
            ds_diff.status)

    def test_source_package_name_unique_for_derived_series(self):
        # We cannot create two differences for the same derived series
        # for the same package.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str="foo")
        self.assertRaises(
            IntegrityError, self.factory.makeDistroSeriesDifference,
            derived_series=ds_diff.derived_series,
            source_package_name_str="foo")

    def test_cached_properties(self):
        # The source and parent publication properties are cached on the
        # model.
        ds_diff = self.factory.makeDistroSeriesDifference()
        ds_diff.source_pub
        ds_diff.parent_source_pub

        cache = get_property_cache(ds_diff)

        self.assertContentEqual(
            ['source_pub', 'parent_source_pub'], cache)

    def test_base_version_none(self):
        # The attribute is set to None if there is no common base version.
        # Publish different versions in the series.
        derived_series = self.factory.makeDistroSeries(
            parent_series=self.factory.makeDistroSeries())
        source_package_name = self.factory.getOrMakeSourcePackageName('foo')
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=derived_series,
            version='1.0deri1',
            sourcepackagename=source_package_name,
            status=PackagePublishingStatus.PUBLISHED)
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=derived_series.parent_series,
            version='1.0ubu2',
            sourcepackagename=source_package_name,
            status=PackagePublishingStatus.PUBLISHED)
        ds_diff = self.factory.makeDistroSeriesDifference()

        self.assertIs(None, ds_diff.base_version)

    def test_base_version_multiple(self):
        # The latest common base version is set as the base-version.
        derived_series = self.factory.makeDistroSeries(
            parent_series=self.factory.makeDistroSeries())
        source_package_name = self.factory.getOrMakeSourcePackageName('foo')
        # Create changelogs for both.
        changelog_lfa = self.factory.makeChangelog('foo', ['1.2', '1.1'])
        parent_changelog_lfa = self.factory.makeChangelog('foo', ['1.1'])
        transaction.commit() # Yay, librarian.

        ds_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series, source_package_name_str='foo',
            versions={
                'derived': '1.2',
                'parent': '1.3',
                },
            changelogs={
                'derived': changelog_lfa,
                'parent': parent_changelog_lfa})

        self.assertEqual('1.1', ds_diff.base_version)

    def test_base_version_invalid(self):
        # If the maximum base version is invalid, it is discarded and not
        # set as the base version.
        derived_series = self.factory.makeDistroSeries(
            parent_series=self.factory.makeDistroSeries())
        source_package_name = self.factory.getOrMakeSourcePackageName('foo')
        # Create changelogs for both.
        changelog_lfa = self.factory.makeChangelog(
            'foo', ['1:2.0-1', 'a1:1.8.8-070403-1~priv1', '1:1.7-1'])
        parent_changelog_lfa = self.factory.makeChangelog(
            'foo', ['1:2.0-2', 'a1:1.8.8-070403-1~priv1', '1:1.7-1'])
        transaction.commit() # Yay, librarian.

        ds_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series, source_package_name_str='foo',
            versions={
                'derived': '1:2.0-1',
                'parent': '1:2.0-2',
                },
            changelogs={
                'derived': changelog_lfa,
                'parent': parent_changelog_lfa})

        self.assertEqual('1:1.7-1', ds_diff.base_version)

    def test_base_source_pub_none(self):
        # None is simply returned if there is no base version.
        ds_diff = self.factory.makeDistroSeriesDifference()

        self.assertIs(None, ds_diff.base_version)
        self.assertIs(None, ds_diff.base_source_pub)

    def test_base_source_pub(self):
        # The publication in the parent series with the base version is
        # returned.
        derived_changelog = self.factory.makeChangelog(
            versions=['1.0', '1.2'])
        parent_changelog = self.factory.makeChangelog(
            versions=['1.0', '1.3'])
        transaction.commit() # Yay, librarian.

        ds_diff = self.factory.makeDistroSeriesDifference(versions={
            'derived': '1.2',
            'parent': '1.3',
            'base': '1.0',
            },
            changelogs={
                'derived': derived_changelog,
                'parent': parent_changelog,
            })

        base_pub = ds_diff.base_source_pub
        self.assertEqual('1.0', base_pub.source_package_version)
        self.assertEqual(
            ds_diff.derived_series.parent_series, base_pub.distroseries)

    def test_base_source_pub_not_published(self):
        # If the base version isn't published, the base version is
        # calculated, but the source publication isn't set.
        derived_changelog = self.factory.makeChangelog(
            versions=['1.0', '1.2'])
        parent_changelog = self.factory.makeChangelog(
            versions=['1.0', '1.3'])
        transaction.commit() # Yay, librarian.

        ds_diff = self.factory.makeDistroSeriesDifference(versions={
            'derived': '1.2',
            'parent': '1.3',
            },
            changelogs={
                'derived': derived_changelog,
                'parent': parent_changelog,
            })
        self.assertEqual('1.0', ds_diff.base_version)
        self.assertIs(None, ds_diff.base_source_pub)

    def test_base_source_pub_only_in_child(self):
        # If the base version is only published in the child distroseries,
        # the base source publication is still located and returned.
        derived_changelog = self.factory.makeChangelog(
            versions=['1.0', '1.2'])
        parent_changelog = self.factory.makeChangelog(
            versions=['1.0', '1.3'])
        transaction.commit() # Yay, librarian.

        ds_diff = self.factory.makeDistroSeriesDifference(
            versions={
                'derived': '1.2',
                'parent': '1.3',
            },
            changelogs={
                'derived': derived_changelog,
                'parent': parent_changelog,
            })

        # Passing in a base version to makeDistroSeriesDifference() creates
        # it in both distroseries, which we don't want, so we need to do it
        # ourselves.
        spr = self.factory.makeSourcePackageRelease(
            sourcepackagename=ds_diff.source_package_name, version='1.0')
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=ds_diff.derived_series, sourcepackagerelease=spr,
            status=PackagePublishingStatus.SUPERSEDED)
        self.assertEqual('1.0', ds_diff.base_version)
        self.assertEqual(
            ds_diff.derived_series, ds_diff.base_source_pub.distroseries)

    def test_requestPackageDiffs(self):
        # IPackageDiffs are created for the corresponding versions.
        derived_changelog = self.factory.makeChangelog(
            versions=['1.0', '1.2'])
        parent_changelog = self.factory.makeChangelog(
            versions=['1.0', '1.3'])
        transaction.commit() # Yay, librarian.
        ds_diff = self.factory.makeDistroSeriesDifference(versions={
            'derived': '1.2',
            'parent': '1.3',
            'base': '1.0',
            },
            changelogs={
                'derived': derived_changelog,
                'parent': parent_changelog,
            })

        person = self.factory.makePerson()
        with person_logged_in(person):
            ds_diff.requestPackageDiffs(person)

        self.assertEqual(
            '1.2', ds_diff.package_diff.to_source.version)
        self.assertEqual(
            '1.3', ds_diff.parent_package_diff.to_source.version)
        self.assertEqual(
            '1.0', ds_diff.package_diff.from_source.version)
        self.assertEqual(
            '1.0', ds_diff.parent_package_diff.from_source.version)

    def test_requestPackageDiffs_child_is_base(self):
        # When the child has the same version as the base version, when
        # diffs are requested, child diffs aren't.
        derived_changelog = self.factory.makeChangelog(versions=['0.1-1'])
        parent_changelog = self.factory.makeChangelog(
            versions=['0.1-2', '0.1-1'])
        transaction.commit() # Yay, librarian.
        ds_diff = self.factory.makeDistroSeriesDifference(
            versions={
                'derived': '0.1-1',
                'parent': '0.1-2',
                'base': '0.1-1',
            },
            changelogs={
                'derived': derived_changelog,
                'parent': parent_changelog,
            })

        person = self.factory.makePerson()
        with person_logged_in(person):
            ds_diff.requestPackageDiffs(person)
        self.assertIs(None, ds_diff.package_diff)
        self.assertIsNot(None, ds_diff.parent_package_diff)

    def test_requestPackageDiffs_with_resolved_DSD(self):
        # Diffs can't be requested for DSDs that are RESOLVED.
        changelog_lfa = self.factory.makeChangelog(versions=['0.1-1'])
        transaction.commit() # Yay, librarian.
        ds_diff = self.factory.makeDistroSeriesDifference(
            status=DistroSeriesDifferenceStatus.RESOLVED,
            versions={
                'derived': '0.1-1',
                'parent': '0.1-1',
                'base': '0.1-1',
            },
            changelogs={
                'derived': changelog_lfa,
                'parent': changelog_lfa,
            })
        person = self.factory.makePerson()
        with person_logged_in(person):
            self.assertRaisesWithContent(
                DistroSeriesDifferenceError,
                "Can not generate package diffs for a resolved difference.",
                ds_diff.requestPackageDiffs, person)

    def test_package_diff_urls_none(self):
        # URLs to the package diffs are only present when the diffs
        # have been generated.
        ds_diff = self.factory.makeDistroSeriesDifference()

        self.assertEqual(None, ds_diff.package_diff_url)
        self.assertEqual(None, ds_diff.parent_package_diff_url)

    def test_source_package_release_pending(self):
        # source_package_release returns the package release of version
        # source_version with status PUBLISHED or PENDING.
        derived_series = self.factory.makeDistroSeries(
            parent_series=self.factory.makeDistroSeries())
        source_package_name = self.factory.getOrMakeSourcePackageName('foo')
        versions = {'derived': u'1.2', 'parent': u'1.3'}

        ds_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str=source_package_name.name,
            versions=versions)

        # Create pending source package releases.
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=derived_series,
            version='1.4',
            sourcepackagename=source_package_name,
            status=PackagePublishingStatus.PENDING)
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=derived_series.parent_series,
            version='1.5',
            sourcepackagename=source_package_name,
            status=PackagePublishingStatus.PENDING)

        # Manually change the diff's source_version and
        # parent_source_version.
        naked_ds_diff = removeSecurityProxy(ds_diff)
        naked_ds_diff.source_version = '1.4'
        naked_ds_diff.parent_source_version = '1.5'

        self.assertEqual(ds_diff.source_package_release.version, '1.4')
        self.assertEqual(ds_diff.parent_source_package_release.version, '1.5')


class DistroSeriesDifferenceLibrarianTestCase(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def test_package_diff_urls(self):
        # Only completed package diffs have urls.
        ds_diff = self.factory.makeDistroSeriesDifference()
        naked_dsdiff = removeSecurityProxy(ds_diff)
        naked_dsdiff.package_diff = self.factory.makePackageDiff(
            status=PackageDiffStatus.PENDING)
        naked_dsdiff.parent_package_diff = self.factory.makePackageDiff()

        self.assertEqual(None, ds_diff.package_diff_url)
        self.assertTrue(ds_diff.parent_package_diff_url is not None)


class DistroSeriesDifferenceSourceTestCase(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        # The implementation implements the interface correctly.
        dsd_source = getUtility(IDistroSeriesDifferenceSource)

        verifyObject(IDistroSeriesDifferenceSource, dsd_source)

    def makeDiffsForDistroSeries(self, derived_series):
        # Helper that creates a range of differences for a derived
        # series.
        diffs = {
            'normal': [],
            'unique': [],
            'ignored': [],
            }
        diffs['normal'].append(
            self.factory.makeDistroSeriesDifference(
                derived_series=derived_series))
        diffs['unique'].append(
            self.factory.makeDistroSeriesDifference(
                derived_series=derived_series,
                difference_type=(
                    DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES)))
        diffs['ignored'].append(
            self.factory.makeDistroSeriesDifference(
                derived_series=derived_series,
                status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT))
        return diffs

    def makeDerivedSeries(self):
        # Keep tests DRY.
        return self.factory.makeDistroSeries(
            parent_series=self.factory.makeDistroSeries())

    def test_getForDistroSeries_default(self):
        # By default all differences needing attention for the given
        # series are returned.
        derived_series = self.makeDerivedSeries()
        diffs = self.makeDiffsForDistroSeries(derived_series)

        result = getUtility(IDistroSeriesDifferenceSource).getForDistroSeries(
            derived_series)

        self.assertContentEqual(
            diffs['normal'], result)

    def test_getForDistroSeries_filters_by_distroseries(self):
        # Differences for other series are not included.
        derived_series = self.makeDerivedSeries()
        diffs = self.makeDiffsForDistroSeries(derived_series)
        diff_for_other_series = self.factory.makeDistroSeriesDifference()

        result = getUtility(IDistroSeriesDifferenceSource).getForDistroSeries(
            derived_series)

        self.assertFalse(diff_for_other_series in result)

    def test_getForDistroSeries_filters_by_type(self):
        # Only differences for the specified types are returned.
        derived_series = self.makeDerivedSeries()
        diffs = self.makeDiffsForDistroSeries(derived_series)

        result = getUtility(IDistroSeriesDifferenceSource).getForDistroSeries(
            derived_series,
            DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES)

    def test_getForDistroSeries_filters_by_status(self):
        # A single status can be used to filter results.
        derived_series = self.makeDerivedSeries()
        diffs = self.makeDiffsForDistroSeries(derived_series)

        result = getUtility(IDistroSeriesDifferenceSource).getForDistroSeries(
            derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)

        self.assertContentEqual(diffs['ignored'], result)

    def test_getForDistroSeries_filters_by_multiple_statuses(self):
        # Multiple statuses can be passed for filtering.
        derived_series = self.makeDerivedSeries()
        diffs = self.makeDiffsForDistroSeries(derived_series)

        result = getUtility(IDistroSeriesDifferenceSource).getForDistroSeries(
            derived_series,
            status=(
                DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT,
                DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
                ))

        self.assertContentEqual(diffs['normal'] + diffs['ignored'], result)

    def test_getForDistroSeries_sorted_by_package_name(self):
        # The differences are sorted by package name.
        derived_series = self.makeDerivedSeries()
        names = []
        for i in range(10):
            diff = self.factory.makeDistroSeriesDifference(
                derived_series=derived_series)
            names.append(diff.source_package_name.name)

        results = getUtility(
            IDistroSeriesDifferenceSource).getForDistroSeries(derived_series)

        self.assertContentEqual(
            sorted(names),
            [result.source_package_name.name for result in results])

    def test_getByDistroSeriesAndName(self):
        # An individual difference is obtained using the name.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str='fooname')

        dsd_source = getUtility(IDistroSeriesDifferenceSource)
        result = dsd_source.getByDistroSeriesAndName(
            ds_diff.derived_series, 'fooname')

        self.assertEqual(ds_diff, result)
