# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Utility for looking up Git repositories by name."""

__metaclass__ = type
__all__ = [
    'IDefaultGitTraversable',
    'IDefaultGitTraverser',
    'IGitLookup',
    ]

from zope.interface import Interface


class IDefaultGitTraversable(Interface):
    """A thing that can be traversed to find a thing with a default Git
    repository."""

    def traverse(owner, name, segments):
        """Return the object beneath this one that matches 'name'.

        :param owner: The current `IPerson` context, or None.
        :param name: The name of the object being traversed to.
        :param segments: Remaining path segments.
        :return: A tuple of
            * an `IPerson`, or None;
            * an `IDefaultGitTraversable` object if traversing should
              continue; an `ICanHasDefaultGitRepository` object otherwise.
        """


class IDefaultGitTraverser(Interface):
    """Utility for traversing to an object that can have a default Git
    repository."""

    def traverse(path):
        """Traverse to the object referred to by 'path'.

        :raises InvalidNamespace: If the path cannot be parsed as a
            repository namespace.
        :raises InvalidProductName: If the project component of the path is
            not a valid name.
        :raises NoSuchPerson: If the first segment of the path begins with a
            '~', but we can't find a person matching the remainder.
        :raises NoSuchProduct: If we can't find a project that matches the
            project component of the path.
        :raises NoSuchSourcePackageName: If the source package referred to
            does not exist.

        :return: A tuple of an `IPerson` or None, and one of
            * `IProduct`
            * `IDistributionSourcePackage`
        """


class IGitLookup(Interface):
    """Utility for looking up a Git repository by name."""

    def get(repository_id, default=None):
        """Return the repository with the given id.

        Return the default value if there is no such repository.
        """

    def getByUniqueName(unique_name):
        """Find a repository by its unique name.

        Unique names have one of the following forms:
            ~OWNER/PROJECT/+git/NAME
            ~OWNER/DISTRO/+source/SOURCE/+git/NAME
            ~OWNER/+git/NAME

        :return: An `IGitRepository`, or None.
        """

    def uriToHostingPath(uri):
        """Return the path for the URI, if the URI is on codehosting.

        This does not ensure that the path is valid.

        :param uri: An instance of lazr.uri.URI
        :return: The path if possible; None if the URI is not a valid
            codehosting URI.
        """

    def getByUrl(url):
        """Find a repository by URL.

        Either from the URL on git.launchpad.net (various schemes) or the
        lp: URL (which relies on client-side configuration).
        """

    def getByPath(path):
        """Find a repository by its path.

        Any of these forms may be used, with or without a leading slash:
            Unique names:
                ~OWNER/PROJECT/+git/NAME
                ~OWNER/DISTRO/+source/SOURCE/+git/NAME
                ~OWNER/+git/NAME
            Owner-target default aliases:
                ~OWNER/PROJECT
                ~OWNER/DISTRO/+source/SOURCE
            Official aliases:
                PROJECT
                DISTRO/+source/SOURCE

        :raises InvalidNamespace: If the path is not in one of the valid
            namespaces for a repository.
        :raises InvalidProductName: If the given project in a project
            shortcut is an invalid name for a project.

        :raises NoSuchGitRepository: If we can't find a repository that
            matches the repository component of the path.
        :raises NoSuchPerson: If we can't find a person who matches the
            person component of the path.
        :raises NoSuchProduct: If we can't find a project that matches the
            project component of the path.
        :raises NoSuchSourcePackageName: If the source package referred to
            does not exist.

        :return: An `IGitRepository`, or None.
        """
