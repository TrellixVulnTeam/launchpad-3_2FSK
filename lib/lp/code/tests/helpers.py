# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper functions for code testing live here."""

__metaclass__ = type
__all__ = [
    'add_revision_to_branch',
    'make_linked_package_branch',
    'make_erics_fooix_project',
    ]


from datetime import timedelta
from difflib import unified_diff
from itertools import count

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy
from zope.security.proxy import isinstance as zisinstance

from lp.code.interfaces.seriessourcepackagebranch import (
    IMakeOfficialBranchLinks)
from lp.registry.interfaces.distroseries import DistroSeriesStatus
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.testing import time_counter


def add_revision_to_branch(factory, branch, revision_date, date_created=None,
                           mainline=True):
    """Add a new revision to the branch with the specified revision date.

    If date_created is None, it gets set to the revision_date.
    """
    if date_created is None:
        date_created = revision_date
    revision = factory.makeRevision(
        revision_date=revision_date, date_created=date_created)
    if mainline:
        sequence = branch.revision_count + 1
        branch_revision = branch.createBranchRevision(sequence, revision)
        branch.updateScannedDetails(revision, sequence)
    else:
        branch_revision = branch.createBranchRevision(None, revision)
    return branch_revision


def make_erics_fooix_project(factory):
    """Make Eric, the Fooix project, and some branches.

    :return: a dict of objects to put into local scope.
    """
    result = {}
    eric = factory.makePerson(
        name='eric', displayname='Eric the Viking',
        email='eric@example.com', password='test')
    fooix = factory.makeProduct(
        name='fooix', displayname='Fooix', owner=eric)
    trunk = factory.makeProductBranch(
        owner=eric, product=fooix, name='trunk')
    removeSecurityProxy(fooix.development_focus).branch = trunk
    # Development is done by Fred.
    fred = factory.makePerson(
        name='fred', displayname='Fred Flintstone',
        email='fred@example.com', password='test')
    feature = factory.makeProductBranch(
        owner=fred, product=fooix, name='feature')
    proposed = factory.makeProductBranch(
        owner=fred, product=fooix, name='proposed')
    bmp = proposed.addLandingTarget(
        registrant=fred, target_branch=trunk, needs_review=True,
        review_requests=[(eric, 'code')])
    # And fake a diff.
    naked_bmp = removeSecurityProxy(bmp)
    preview = removeSecurityProxy(naked_bmp.updatePreviewDiff(
        ''.join(unified_diff('', 'random content')), u'rev-a', u'rev-b'))
    naked_bmp.source_branch.last_scanned_id = preview.source_revision_id
    naked_bmp.target_branch.last_scanned_id = preview.target_revision_id
    preview.diff_lines_count = 47
    preview.added_lines_count = 7
    preview.remvoed_lines_count = 13
    preview.diffstat = {'file1': (3, 8), 'file2': (4, 5)}
    return {
        'eric': eric, 'fooix': fooix, 'trunk':trunk, 'feature': feature,
        'proposed': proposed, 'fred': fred}


def make_linked_package_branch(factory, distribution=None,
                               sourcepackagename=None):
    """Make a new package branch and make it official."""
    distro_series = factory.makeDistroRelease(distribution)
    source_package = factory.makeSourcePackage(
        sourcepackagename=sourcepackagename, distroseries=distro_series)
    branch = factory.makePackageBranch(sourcepackage=source_package)
    pocket = PackagePublishingPocket.RELEASE
    # It is possible for the param to be None, so reset to the factory
    # generated one.
    sourcepackagename = source_package.sourcepackagename
    # We don't care about who can make things official, so get rid of the
    # security proxy.
    series_set = removeSecurityProxy(getUtility(IMakeOfficialBranchLinks))
    series_set.new(
        distro_series, pocket, sourcepackagename, branch, branch.owner)
    return branch


def consistent_branch_names():
    """Provide a generator for getting consistent branch names.

    This generator does not finish!
    """
    for name in ['trunk', 'testing', 'feature-x', 'feature-y', 'feature-z']:
        yield name
    index = count(1)
    while True:
        yield "branch-%s" % index.next()


def make_package_branches(factory, series, sourcepackagename, branch_count,
                          official_count=0, owner=None, registrant=None):
    """Make some package branches.

    Make `branch_count` branches, and make `official_count` of those
    official branches.
    """
    if zisinstance(sourcepackagename, basestring):
        sourcepackagename = factory.getOrMakeSourcePackageName(
            sourcepackagename)
    # Make the branches created in the past in order.
    time_gen = time_counter(delta=timedelta(days=-1))
    branch_names = consistent_branch_names()
    branches = [
        factory.makePackageBranch(
            distroseries=series,
            sourcepackagename=sourcepackagename,
            date_created=time_gen.next(),
            name=branch_names.next(), owner=owner, registrant=registrant)
        for i in range(branch_count)]

    official = []
    # We don't care about who can make things official, so get rid of the
    # security proxy.
    series_set = removeSecurityProxy(getUtility(IMakeOfficialBranchLinks))
    # Sort the pocket items so RELEASE is last, and thus first popped.
    pockets = sorted(PackagePublishingPocket.items, reverse=True)
    # Since there can be only one link per pocket, max out the number of
    # official branches at the pocket count.
    for i in range(min(official_count, len(pockets))):
        branch = branches.pop()
        pocket = pockets.pop()
        sspb = series_set.new(
            series, pocket, sourcepackagename, branch, branch.owner)
        official.append(branch)

    return series, branches, official


def make_mint_distro_with_branches(factory):
    """This method makes a distro called mint with many branches.

    The mint distro has the following series and status:
        wild - experimental
        dev - development
        stable - current
        old - supported
        very-old - supported
        ancient - supported
        mouldy - supported
        dead - obsolete

    The mint distro has a team: mint-team, which has Albert, Bob, and Charlie
    as members.

    There are four different source packages:
        twisted, zope, bzr, python
    """
    albert, bob, charlie = [
        factory.makePerson(
            name=name, email=("%s@mint.example.com" % name), password="test")
        for name in ('albert', 'bob', 'charlie')]
    mint_team = factory.makeTeam(owner=albert, name="mint-team")
    mint_team.addMember(bob, albert)
    mint_team.addMember(charlie, albert)
    mint = factory.makeDistribution(
        name='mint', displayname='Mint', owner=albert, members=mint_team)
    series = [
        ("wild", "5.5", DistroSeriesStatus.EXPERIMENTAL),
        ("dev", "4.0", DistroSeriesStatus.DEVELOPMENT),
        ("stable", "3.0", DistroSeriesStatus.CURRENT),
        ("old", "2.0", DistroSeriesStatus.SUPPORTED),
        ("very-old", "1.5", DistroSeriesStatus.SUPPORTED),
        ("ancient", "1.0", DistroSeriesStatus.SUPPORTED),
        ("mouldy", "0.6", DistroSeriesStatus.SUPPORTED),
        ("dead", "0.1", DistroSeriesStatus.OBSOLETE),
        ]
    for name, version, status in series:
        factory.makeDistroRelease(
            distribution=mint, version=version, status=status, name=name)

    for pkg_index, name in enumerate(['twisted', 'zope', 'bzr', 'python']):
        for series_index, series in enumerate(mint.series):
            # Over the series and source packages, we want to have different
            # combinations of official and branch counts.
            # Make the more recent series have most official branches.
            official_count = 6 - series_index
            branch_count = official_count + pkg_index
            make_package_branches(
                factory, series, name, branch_count, official_count,
                owner=mint_team, registrant=albert)
