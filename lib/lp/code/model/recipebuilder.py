# Copyright 2010-2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Code to build recipes on the buildfarm."""

__metaclass__ = type
__all__ = [
    'RecipeBuildBehaviour',
    ]

import traceback

from zope.component import adapts
from zope.interface import implements
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.interfaces.builder import CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
    )
from lp.buildmaster.model.buildfarmjobbehaviour import (
    BuildFarmJobBehaviourBase,
    )
from lp.code.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuild,
    )
from lp.services.config import config
from lp.soyuz.adapters.archivedependencies import (
    get_primary_current_component,
    get_sources_list_for_building,
    )


class RecipeBuildBehaviour(BuildFarmJobBehaviourBase):
    """How to build a recipe on the build farm."""

    adapts(ISourcePackageRecipeBuild)
    implements(IBuildFarmJobBehaviour)

    # The list of build status values for which email notifications are
    # allowed to be sent. It is up to each callback as to whether it will
    # consider sending a notification but it won't do so if the status is not
    # in this list.
    ALLOWED_STATUS_NOTIFICATIONS = [
        'OK', 'PACKAGEFAIL', 'DEPFAIL', 'CHROOTFAIL']

    def _extraBuildArgs(self, distroarchseries, logger=None):
        """
        Return the extra arguments required by the slave for the given build.
        """
        # Build extra arguments.
        args = {}
        args['suite'] = self.build.distroseries.getSuite(self.build.pocket)
        args['arch_tag'] = distroarchseries.architecturetag
        requester = self.build.requester
        if requester.preferredemail is None:
            # Use a constant, known, name and email.
            args["author_name"] = 'Launchpad Package Builder'
            args["author_email"] = config.canonical.noreply_from_address
        else:
            args["author_name"] = requester.displayname
            # We have to remove the security proxy here b/c there's not a
            # logged in entity, and anonymous email lookups aren't allowed.
            # Don't keep the naked requester around though.
            args["author_email"] = removeSecurityProxy(
                requester).preferredemail.email
        args["recipe_text"] = str(self.build.recipe.builder_recipe)
        args['archive_purpose'] = self.build.archive.purpose.name
        args["ogrecomponent"] = get_primary_current_component(
            self.build.archive, self.build.distroseries,
            None)
        args['archives'] = get_sources_list_for_building(self.build,
            distroarchseries, None)
        args['archive_private'] = self.build.archive.private

        # config.builddmaster.bzr_builder_sources_list can contain a
        # sources.list entry for an archive that will contain a
        # bzr-builder package that needs to be used to build this
        # recipe.
        try:
            extra_archive = config.builddmaster.bzr_builder_sources_list
        except AttributeError:
            extra_archive = None

        if extra_archive is not None:
            try:
                sources_line = extra_archive % (
                    {'series': self.build.distroseries.name})
                args['archives'].append(sources_line)
            except StandardError:
                # Someone messed up the config, don't add it.
                if logger:
                    logger.error(
                        "Exception processing bzr_builder_sources_list:\n%s"
                        % traceback.format_exc())

        args['distroseries_name'] = self.build.distroseries.name
        return args

    def composeBuildRequest(self, logger):
        das = self.build.distroseries.getDistroArchSeriesByProcessor(
            self._builder.processor)
        if das is None:
            raise CannotBuild(
                "Unable to find distroarchseries for %s in %s" %
                (self._builder.processor.name,
                 self.build.distroseries.displayname))
        return (
            "sourcepackagerecipe", das, {}, self._extraBuildArgs(das, logger))

    def verifyBuildRequest(self, logger):
        """Assert some pre-build checks.

        The build request is checked:
         * Virtualized builds can't build on a non-virtual builder
         * Ensure that we have a chroot
         * Ensure that the build pocket allows builds for the current
           distroseries state.
        """
        build = self.build
        assert not (not self._builder.virtualized and build.is_virtualized), (
            "Attempt to build virtual item on a non-virtual builder.")

        # This should already have been checked earlier, but just check again
        # here in case of programmer errors.
        reason = build.archive.checkUploadToPocket(
            build.distroseries, build.pocket)
        assert reason is None, (
                "%s (%s) can not be built for pocket %s: invalid pocket due "
                "to the series status of %s." %
                    (build.title, build.id, build.pocket.name,
                     build.distroseries.name))
