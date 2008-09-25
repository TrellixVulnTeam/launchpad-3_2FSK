# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Interfaces including and related to IDiff."""

__metaclass__ = type

__all__ = [
    'IDiff',
    'IStaticDiff',
    'IStaticDiffJob',
    'IStaticDiffJobSource',
    ]

from zope.schema import (
    Object, Int, Text, TextLine)
from zope.interface import (
    Interface)

from canonical.launchpad import _
from canonical.launchpad.interfaces.job import IJob
from canonical.launchpad.interfaces.librarian import ILibraryFileAlias

class IDiff(Interface):
    """A diff that is stored in the Library."""

    diff_text = Object(
        title=_('Content of this diff'), required=True,
        schema=ILibraryFileAlias)

    diff_lines_count = Int(
        title=_('The number of lines in this diff.'))

    diffstat = Text(title=_('Statistics about this diff'))

    added_lines_count = Int(
        title=_('The number of lines added in this diff.'))

    removed_lines_count = Int(
        title=_('The number of lines removed in this diff.'))


class IStaticDiff(Interface):
    """A diff with a fixed value, i.e. between two revisions."""

    from_revision_id = TextLine()

    to_revision_id = TextLine()

    diff = Object(title=_('The Diff object.'), schema=IDiff)

    def destroySelf():
        """Destroy this object."""


class IStaticDiffJob(Interface):
    """A job to create a static diff."""

    job = Object(schema=IJob, required=True)

    branch = Object(
        title=_('Branch to use for this diff'), required=True,
        schema=ILibraryFileAlias)

    from_revision_spec = TextLine(title=_('The revision spec to diff from.'))

    to_revision_spec = TextLine(title=_('The revision spec to diff to.'))

    def destroySelf():
        """Destroy this object."""

    def run():
        """Acquire the static diff this job requires.

        :return: the generated StaticDiff.
        """


class IStaticDiffJobSource(Interface):

    def create(branch, from_revision_spec, to_revision_spec):
        """Substitute for being able to use a constructor."""
