# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""XXX write me."""

import os

from bzrlib.bzrdir import BzrDir

import transaction

from zope.component import getUtility

from canonical.launchpad.interfaces import ILaunchpadCelebrities
from canonical.config import config

from lp.code.interfaces.branchcollection import IAllBranches
from lp.code.interfaces.branchnamespace import IBranchNamespaceSet
from lp.code.enums import BranchType
from lp.codehosting.vfs import branch_id_to_path
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.pocket import PackagePublishingPocket

__metaclass__ = type
__all__ = []


def make_official_branch_in_new_distro_series(db_branch, new_distroseries):
    new_namespace = getUtility(IBranchNamespaceSet).get(
        person=db_branch.owner, product=None, distroseries=new_distroseries,
        sourcepackagename=db_branch.sourcepackagename)
    new_branch = new_namespace.createBranch(
        BranchType.HOSTED, db_branch.name, db_branch.registrant)
    new_branch.sourcepackage.setBranch(
        PackagePublishingPocket.RELEASE, new_branch,
        getUtility(ILaunchpadCelebrities).ubuntu_branches.teamowner)
    return new_branch


def switch_branches(prefix, scheme, old_branch, new_branch):
    # What happens if this function gets interrupted?
    # move .bzr directory from old to new
    old_underlying_path = os.path.join(
        prefix, branch_id_to_path(old_branch.id))
    new_underlying_path = os.path.join(
        prefix, branch_id_to_path(new_branch.id))
    os.makedirs(new_underlying_path)
    os.rename(
        os.path.join(old_underlying_path, '.bzr'),
        os.path.join(new_underlying_path, '.bzr'))

    #  init branch at old location
    new_location_bzrdir = BzrDir.open(scheme + new_branch.unique_name)
    old_location_bzrdir = new_location_bzrdir.clone(
        scheme + old_branch.unique_name, revision_id='null:')

    #  set stacked on url for old location
    old_location_branch = old_location_bzrdir.open_branch()
    old_location_branch.set_stacked_on_url('/' + new_branch.unique_name)

    #  pull from new location to new
    old_location_branch.pull(new_location_bzrdir.open_branch())


def clone_branch(db_branch, new_distroseries):
    # make new db branch
    new_branch = make_official_branch_in_new_distro_series(
        db_branch, new_distroseries)
    transaction.commit()

    # for both hosted and mirrored area:
    #  move .bzr directory from old to new (some abstraction violations here!)
    #  init branch at old location
    #  set stacked on url for old location
    #  pull from new location to new
    switch_branches(
        config.codehosting.hosted_branches_root,
        'lp-hosted:///', db_branch, new_branch)
    switch_branches(
        config.codehosting.mirrored_branches_root,
        'lp-mirrored:///', db_branch, new_branch)


class InconsistentOfficialPackageBranch(Exception):
    pass


def check_consistent_official_package_branch(branch):
    if branch.product:
        raise InconsistentOfficialPackageBranch(
            "Encountered unexpected product branch %r" % branch.unique_name)
    if not branch.distroseries:
        raise InconsistentOfficialPackageBranch(
            "Encountered unexpected personal branch %r" % branch.unique_name)
    package_branch = branch.sourcepackage.getBranch(
        PackagePublishingPocket.RELEASE)
    if package_branch != branch:
        raise InconsistentOfficialPackageBranch(
            "%r is not the official branch for its sourcepackage (%r is "
            "instead)" % (branch.unique_name, package_branch.unique_name))


def branch_distro(distro_name, old_distroseries_name, new_distroseries_name):
    distribution = getUtility(IDistributionSet).getByName(distro_name)
    old_distroseries = distribution.getSeries(old_distroseries_name)
    new_distroseries = distribution.getSeries(new_distroseries_name)
    branches = getUtility(IAllBranches)
    distroseries_branches = branches.inDistroSeries(old_distroseries)
    for branch in distroseries_branches.officialBranches():
        clone_branch(branch, new_distroseries)

