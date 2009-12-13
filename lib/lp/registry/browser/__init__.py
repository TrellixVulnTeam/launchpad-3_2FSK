# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Common registry browser helpers and mixins."""

__metaclass__ = type

__all__ = [
    'get_status_counts',
    'MilestoneOverlayMixin',
    'RegistryEditFormView',
    'RegistryDeleteViewMixin',
    'StatusCount',
    ]


from operator import attrgetter

from zope.component import getUtility

from storm.store import Store

from lp.bugs.interfaces.bugtask import BugTaskSearchParams, IBugTaskSet
from lp.registry.interfaces.productseries import IProductSeries
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.webapp.launchpadform import (
    action, LaunchpadEditFormView)
from canonical.launchpad.webapp.publisher import canonical_url


class StatusCount:
    """A helper that stores the count of status for a list of items.

    Items such as `IBugTask` and `ISpecification` can be summarised by
    their status.
    """

    def __init__(self, status, count):
        """Set the status and count."""
        self.status = status
        self.count = count


def get_status_counts(workitems, status_attr, key='sortkey'):
    """Return a list StatusCounts summarising the workitem."""
    statuses = {}
    for workitem in workitems:
        status = getattr(workitem, status_attr)
        if status is None:
            # This is not something we want to count.
            continue
        if status not in statuses:
            statuses[status] = 0
        statuses[status] += 1
    return [
        StatusCount(status, statuses[status])
        for status in sorted(statuses, key=attrgetter(key))]


class MilestoneOverlayMixin:
    """A mixin that provides the data for the milestoneoverlay script."""

    milestone_can_release = True

    @property
    def milestone_form_uri(self):
        """URI for form displayed by the formoverlay widget."""
        return canonical_url(self.context) + '/+addmilestone/++form++'

    @property
    def series_api_uri(self):
        """The series URL for API access."""
        return canonical_url(self.context, path_only_if_possible=True)

    @property
    def milestone_table_class(self):
        """The milestone table will be unseen if there are no milestones."""
        if len(self.context.all_milestones) > 0:
            return 'listing'
        else:
            # The page can remove the 'unseen' class to make the table
            # visible.
            return 'listing unseen'

    @property
    def milestone_row_uri_template(self):
        if IProductSeries.providedBy(self.context):
            pillar = self.context.product
        else:
            pillar = self.context.distribution
        uri = canonical_url(pillar, path_only_if_possible=True)
        return '%s/+milestone/{name}/+productseries-table-row' % uri

    @property
    def register_milestone_script(self):
        """Return the script to enable milestone creation via AJAX."""
        uris = {
            'series_api_uri': self.series_api_uri,
            'milestone_form_uri': self.milestone_form_uri,
            'milestone_row_uri': self.milestone_row_uri_template,
            }
        return """
            YUI().use(
                'node', 'lp.milestoneoverlay', 'lp.milestonetable',
                function (Y) {

                var series_uri = '%(series_api_uri)s';
                var milestone_form_uri = '%(milestone_form_uri)s';
                var milestone_row_uri = '%(milestone_row_uri)s';
                var milestone_rows_id = '#milestone-rows';

                Y.on('domready', function () {
                    var create_milestone_link = Y.get(
                        '.menu-link-create_milestone');
                    create_milestone_link.addClass('js-action');
                    var config = {
                        milestone_form_uri: milestone_form_uri,
                        series_uri: series_uri,
                        next_step: Y.lp.milestonetable.get_milestone_row,
                        activate_node: create_milestone_link
                        };
                    Y.lp.milestoneoverlay.attach_widget(config);
                    var table_config = {
                        milestone_row_uri_template: milestone_row_uri,
                        milestone_rows_id: milestone_rows_id
                        }
                    Y.lp.milestonetable.setup(table_config);
                });
            });
            """ % uris


class RegistryDeleteViewMixin:
    """A mixin class that provides common behavior for registry deletions."""

    @property
    def cancel_url(self):
        """The context's URL."""
        return canonical_url(self.context)

    def _getBugtasks(self, target):
        """Return the list `IBugTask`s associated with the target."""
        if IProductSeries.providedBy(target):
            params = BugTaskSearchParams(user=None)
            params.setProductSeries(target)
        else:
            params = BugTaskSearchParams(milestone=target, user=None)
        bugtasks = getUtility(IBugTaskSet).search(params)
        return list(bugtasks)

    def _getSpecifications(self, target):
        """Return the list `ISpecification`s associated to the target."""
        if IProductSeries.providedBy(target):
            return list(target.all_specifications)
        else:
            return list(target.specifications)

    def _getProductRelease(self, milestone):
        """The `IProductRelease` associated with the milestone."""
        return milestone.product_release

    def _getProductReleaseFiles(self, milestone):
        """The list of `IProductReleaseFile`s related to the milestone."""
        product_release = self._getProductRelease(milestone)
        if product_release is not None:
            return list(product_release.files)
        else:
            return []

    def _unsubscribe_structure(self, structure):
        """Removed the subscriptions from structure."""
        for subscription in structure.getSubscriptions():
            # The owner of the subscription or an admin are the only users
            # that can destroy a subscription, but this rule cannot prevent
            # the owner from removing the structure.
            Store.of(subscription).remove(subscription)

    def _remove_series_bugs_and_specifications(self, series):
        """Untarget the associated bugs and subscriptions."""
        for spec in self._getSpecifications(series):
            spec.proposeGoal(None, self.user)
        for bugtask in self._getBugtasks(series):
            # Bugtasks cannot be deleted directly. In this case, the bugtask
            # is already reported on the product, so the series bugtask has
            # no purpose without a series.
            Store.of(bugtask).remove(bugtask)

    def _deleteProductSeries(self, series):
        """Remove the series and delete/unlink related objects.

        All subordinate milestones, releases, and files will be deleted.
        Milestone bugs and blueprints will be untargeted.
        Series bugs and blueprints will be untargeted.
        Series and milestone structural subscriptions are unsubscribed.
        Series branches are unlinked.
        """
        self._unsubscribe_structure(series)
        self._remove_series_bugs_and_specifications(series)
        series.branch = None

        for milestone in series.all_milestones:
            self._deleteMilestone(milestone)
        # Series are not deleted because some objects like translations are
        # problematic. The series is assigned to obsolete-junk. They must be
        # renamed to avoid name collision.
        date_time = series.datecreated.strftime('%Y%m%d-%H%M%S')
        series.name = '%s-%s-%s' % (
            series.product.name, series.name, date_time)
        series.product = getUtility(ILaunchpadCelebrities).obsolete_junk

    def _deleteMilestone(self, milestone):
        """Delete a milestone and unlink related objects."""
        self._unsubscribe_structure(milestone)
        for bugtask in self._getBugtasks(milestone):
            bugtask.milestone = None
        for spec in self._getSpecifications(milestone):
            spec.milestone = None
        self._deleteRelease(milestone.product_release)
        milestone.destroySelf()

    def _deleteRelease(self, release):
        """Delete a release and it's files."""
        if release is not None:
            for release_file in release.files:
                release_file.destroySelf()
            release.destroySelf()


class RegistryEditFormView(LaunchpadEditFormView):
    """A base class that provides consistent edit form behaviour."""

    @property
    def page_title(self):
        """The page title."""
        return self.label

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    next_url = cancel_url

    @action("Change", name='change')
    def change_action(self, action, data):
        self.updateContextFromData(data)
