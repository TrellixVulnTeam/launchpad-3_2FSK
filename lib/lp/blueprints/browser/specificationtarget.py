# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""ISpecificationTarget browser views."""

__metaclass__ = type

__all__ = [
    'HasSpecificationsMenuMixin',
    'HasSpecificationsView',
    'RegisterABlueprintButtonView',
    'SpecificationAssignmentsView',
    'SpecificationDocumentationView',
    ]

from operator import itemgetter

from z3c.ptcompat import ViewPageTemplateFile
from zope.component import queryMultiAdapter

from canonical.config import config
from canonical.launchpad import _
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.interfaces.launchpad import IHasDrivers
from canonical.launchpad.webapp import (
    canonical_url,
    LaunchpadView,
    )
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.breadcrumb import Breadcrumb
from canonical.launchpad.webapp.menu import (
    enabled_with_permission,
    Link,
    )
from canonical.lazr.utils import smartquote
from lp.app.enums import service_uses_launchpad
from lp.app.interfaces.launchpad import IServiceUsage
from lp.blueprints.interfaces.specification import (
    SpecificationFilter,
    SpecificationSort,
    )
from lp.blueprints.interfaces.specificationtarget import ISpecificationTarget
from lp.blueprints.interfaces.sprint import ISprint
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.projectgroup import (
    IProjectGroup,
    IProjectGroupSeries,
    )
from lp.services.propertycache import cachedproperty


class HasSpecificationsMenuMixin:

    def listall(self):
        """Return a link to show all blueprints."""
        text = 'List all blueprints'
        return Link('+specs?show=all', text, icon='blueprint')

    def listaccepted(self):
        """Return a link to show the approved goals."""
        text = 'List approved blueprints'
        return Link('+specs?acceptance=accepted', text, icon='blueprint')

    def listproposed(self):
        """Return a link to show the proposed goals."""
        text = 'List proposed blueprints'
        return Link('+specs?acceptance=proposed', text, icon='blueprint')

    def listdeclined(self):
        """Return a link to show the declined goals."""
        text = 'List declined blueprints'
        return Link('+specs?acceptance=declined', text, icon='blueprint')

    def doc(self):
        text = 'List documentation'
        return Link('+documentation', text, icon='info')

    def setgoals(self):
        """Return a link to set the series goals."""
        text = 'Set series goals'
        return Link('+setgoals', text, icon='edit')

    def assignments(self):
        """Return a link to show the people assigned to the blueprint."""
        text = 'Assignments'
        return Link('+assignments', text, icon='person')

    def new(self):
        """Return a link to register a blueprint."""
        text = 'Register a blueprint'
        return Link('+addspec', text, icon='add')

    @enabled_with_permission('launchpad.View')
    def register_sprint(self):
        text = 'Register a meeting'
        summary = 'Register a developer sprint, summit, or gathering'
        return Link('/sprints/+new', text, summary=summary, icon='add')


class HasSpecificationsView(LaunchpadView):
    """Base class for several context-specific views that involve lists of
    specifications.

    This base class knows how to handle and represent lists of
    specifications, produced by a method view.specs(). The individual class
    view objects each implement that method in a way that is appropriate for
    them, because they each want to filter the list of specs in different
    ways. For example, in the case of PersonSpecsView, you want to filter
    based on the relationship the person has to the specs. In the case of a
    ProductSpecsView you want to filter primarily based on the completeness
    of the spec.
    """

    # these flags set the default column display. subclasses will override
    # them to add or remove columns from the default
    show_assignee = True
    show_target = False
    show_series = False
    show_milestone = False
    show_design = True
    show_implementation = True
    show_priority = True

    # these flags govern some of the content of the spec page, which allows
    # us to vary the text flow slightly without creating large numbers of
    # template fragments
    is_person = False
    is_pillar = False
    is_target = False
    is_project = False
    is_series = False
    is_sprint = False
    has_drivers = False

    # Templates for the various conditions of blueprints:
    # * On Launchpad
    # * External
    # * Disabled
    # * Unknown
    uses_launchpad_template = ViewPageTemplateFile(
        '../templates/hasspecifications-specs.pt')
    not_launchpad_template = ViewPageTemplateFile(
        '../templates/unknown-specs.pt')

    @property
    def template(self):
        # If specifications exist, ignore the usage enum.
        if self.has_any_specifications:
            return self.uses_launchpad_template
        # Otherwise, determine usage and provide the correct template.
        service_usage = IServiceUsage(self.context)
        if service_uses_launchpad(service_usage.blueprints_usage):
            return self.uses_launchpad_template
        else:
            return self.not_launchpad_template

    def render(self):
        return self.template

    # XXX: jsk: 2007-07-12 bug=173972: This method might be improved by
    # replacing the conditional execution with polymorphism.
    def initialize(self):
        if IPerson.providedBy(self.context):
            self.is_person = True
        elif (IDistribution.providedBy(self.context) or
              IProduct.providedBy(self.context)):
            self.is_target = True
            self.is_pillar = True
            self.show_series = True
        elif IProjectGroup.providedBy(self.context):
            self.is_project = True
            self.is_pillar = True
            self.show_target = True
            self.show_series = True
        elif IProjectGroupSeries.providedBy(self.context):
            self.show_milestone = True
            self.show_target = True
            self.show_series = True
        elif (IProductSeries.providedBy(self.context) or
              IDistroSeries.providedBy(self.context)):
            self.is_series = True
            self.show_milestone = True
        elif ISprint.providedBy(self.context):
            self.is_sprint = True
            self.show_target = True
        else:
            raise AssertionError('Unknown blueprint listing site.')

        if IHasDrivers.providedBy(self.context):
            self.has_drivers = True

        self.batchnav = BatchNavigator(
            self.specs, self.request,
            size=config.launchpad.default_batch_size)

    @property
    def label(self):
        mapping = {'name': self.context.displayname}
        if self.is_person:
            return _('Blueprints involving $name', mapping=mapping)
        else:
            return _('Blueprints for $name', mapping=mapping)

    page_title = 'Blueprints'

    def mdzCsv(self):
        """Quick hack for mdz, to get csv dump of specs."""
        import csv
        from StringIO import StringIO
        output = StringIO()
        writer = csv.writer(output)
        headings = [
            'name',
            'title',
            'url',
            'specurl',
            'status',
            'priority',
            'assignee',
            'drafter',
            'approver',
            'owner',
            'distroseries',
            'direction_approved',
            'man_days',
            'delivery'
            ]
        def dbschema(item):
            """Format a dbschema sortably for a spreadsheet."""
            return '%s-%s' % (item.value, item.title)
        def fperson(person):
            """Format a person as 'name (full name)', or 'none'"""
            if person is None:
                return 'none'
            else:
                return '%s (%s)' % (person.name, person.displayname)
        writer.writerow(headings)
        for spec in self.context.all_specifications:
            row = []
            row.append(spec.name)
            row.append(spec.title)
            row.append(canonical_url(spec))
            row.append(spec.specurl)
            row.append(dbschema(spec.definition_status))
            row.append(dbschema(spec.priority))
            row.append(fperson(spec.assignee))
            row.append(fperson(spec.drafter))
            row.append(fperson(spec.approver))
            row.append(fperson(spec.owner))
            if spec.distroseries is None:
                row.append('none')
            else:
                row.append(spec.distroseries.name)
            row.append(spec.direction_approved)
            row.append(spec.man_days)
            row.append(dbschema(spec.implementation_status))
            writer.writerow([unicode(item).encode('utf8') for item in row])
        self.request.response.setHeader('Content-Type', 'text/plain')
        return output.getvalue()

    @cachedproperty
    def has_any_specifications(self):
        return self.context.has_any_specifications

    @cachedproperty
    def all_specifications(self):
        return shortlist(self.context.all_specifications)

    @cachedproperty
    def searchrequested(self):
        return self.searchtext is not None

    @cachedproperty
    def searchtext(self):
        st = self.request.form.get('searchtext')
        if st is None:
            st = self.request.form.get('field.searchtext')
        return st

    @cachedproperty
    def spec_filter(self):
        """The list of specs that are going to be displayed in this view.

        This method determines the appropriate filtering to be passed to
        context.specifications(). See IHasSpecifications.specifications
        for further details.

        The method can review the URL and decide what will be included,
        and what will not.

        The typical URL is of the form:

           ".../name1/+specs?show=complete&informational&acceptance=accepted"

        This method will interpret the show= part based on the kind of
        object that is the context of this request.
        """
        show = self.request.form.get('show')
        acceptance = self.request.form.get('acceptance')
        role = self.request.form.get('role')
        informational = self.request.form.get('informational', False)

        filter = []

        # include text for filtering if it was given
        if self.searchtext is not None and len(self.searchtext) > 0:
            filter.append(self.searchtext)

        # filter on completeness
        if show == 'all':
            filter.append(SpecificationFilter.ALL)
        elif show == 'complete':
            filter.append(SpecificationFilter.COMPLETE)
        elif show == 'incomplete':
            filter.append(SpecificationFilter.INCOMPLETE)

        # filter for informational status
        if informational is not False:
            filter.append(SpecificationFilter.INFORMATIONAL)

        # filter on relationship or role. the underlying class will give us
        # the aggregate of everything if we don't explicitly select one or
        # more
        if role == 'registrant':
            filter.append(SpecificationFilter.CREATOR)
        elif role == 'assignee':
            filter.append(SpecificationFilter.ASSIGNEE)
        elif role == 'drafter':
            filter.append(SpecificationFilter.DRAFTER)
        elif role == 'approver':
            filter.append(SpecificationFilter.APPROVER)
        elif role == 'feedback':
            filter.append(SpecificationFilter.FEEDBACK)
        elif role == 'subscriber':
            filter.append(SpecificationFilter.SUBSCRIBER)

        # filter for acceptance state
        if acceptance == 'declined':
            filter.append(SpecificationFilter.DECLINED)
        elif show == 'proposed':
            filter.append(SpecificationFilter.PROPOSED)
        elif show == 'accepted':
            filter.append(SpecificationFilter.ACCEPTED)

        return filter

    @property
    def specs(self):
        filter = self.spec_filter
        return self.context.specifications(filter=filter)

    @cachedproperty
    def spec_count(self):
        return self.specs.count()

    @cachedproperty
    def documentation(self):
        filter = [SpecificationFilter.COMPLETE,
                  SpecificationFilter.INFORMATIONAL]
        return shortlist(self.context.specifications(filter=filter))

    @cachedproperty
    def categories(self):
        """This organises the specifications related to this target by
        "category", where a category corresponds to a particular spec
        status. It also determines the order of those categories, and the
        order of the specs inside each category.

        It is also used in IPerson, which is not an ISpecificationTarget but
        which does have a IPerson.specifications. In this case, it will also
        detect which set of specifications you want to see. The options are:

         - all specs (self.context.specifications())
         - created by this person
         - assigned to this person
         - for review by this person
         - specs this person must approve
         - drafted by this person
         - subscribed by this person

        """
        categories = {}
        for spec in self.specs:
            if spec.definition_status in categories:
                category = categories[spec.definition_status]
            else:
                category = {}
                category['status'] = spec.definition_status
                category['specs'] = []
                categories[spec.definition_status] = category
            category['specs'].append(spec)
        categories = categories.values()
        return sorted(categories, key=itemgetter('definition_status'))

    def getLatestSpecifications(self, quantity=5):
        """Return <quantity> latest specs created for this target.

        Only ACCEPTED specifications are returned.  This list is used by the
        +portlet-latestspecs view.
        """
        return self.context.specifications(sort=SpecificationSort.DATE,
            quantity=quantity, prejoin_people=False)


class SpecificationAssignmentsView(HasSpecificationsView):
    """View for +assignments pages."""
    page_title = "Assignments"

    @property
    def label(self):
        return smartquote(
            'Blueprint assignments for "%s"' % self.context.displayname)


class SpecificationDocumentationView(HasSpecificationsView):
    """View for blueprints +documentation page."""
    page_title = "Documentation"

    @property
    def label(self):
        return smartquote('Current documentation for "%s"' %
                          self.context.displayname)


class RegisterABlueprintButtonView:
    """View that renders a button to register a blueprint on its context."""

    @cachedproperty
    def target_url(self):
        """The +addspec URL for the specifiation target or None"""
        # Check if the context has an +addspec view available.
        if queryMultiAdapter(
            (self.context, self.request), name='+addspec'):
            target = self.context
        else:
            # otherwise find an adapter to ISpecificationTarget which will.
            target = ISpecificationTarget(self.context)
        if target is None:
            return None
        else:
            return canonical_url(
                target, rootsite='blueprints', view_name='+addspec')

    def __call__(self):
        if self.target_url is None:
            return ''
        return """
            <div id="involvement" class="portlet involvement">
              <ul>
                <li style="border: none">
                  <a class="menu-link-register_blueprint sprite blueprints"
                    href="%s">Register a blueprint</a>
                </li>
              </ul>
            </div>
            """ % self.target_url


class BlueprintsVHostBreadcrumb(Breadcrumb):
    rootsite = 'blueprints'
    text = 'Blueprints'
