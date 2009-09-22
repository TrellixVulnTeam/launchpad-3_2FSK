# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""ISpecificationTarget browser views."""

__metaclass__ = type

__all__ = [
    'HasSpecificationsView',
    'RegisterABlueprintButtonView',
    'SpecificationAssignmentsView',
    'SpecificationDocumentationView',
    ]

from operator import itemgetter
from zope.component import queryMultiAdapter

from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from canonical.launchpad.interfaces.launchpad import IHasDrivers
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.project import IProject, IProjectSeries
from lp.blueprints.interfaces.specification import (
    SpecificationFilter, SpecificationSort)
from lp.blueprints.interfaces.specificationtarget import (
    ISpecificationTarget)
from lp.blueprints.interfaces.sprint import ISprint

from canonical.config import config
from canonical.launchpad import _
from canonical.launchpad.webapp import LaunchpadView
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.breadcrumb import Breadcrumb
from canonical.launchpad.helpers import shortlist
from canonical.cachedproperty import cachedproperty
from canonical.launchpad.webapp import canonical_url
from canonical.lazr.utils import smartquote


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

    # XXX: jsk: 2007-07-12: This method might be improved by
    # replacing the conditional execution with polymorphism.
    # See https://bugs.launchpad.net/blueprint/+bug/173972.
    def initialize(self):
        mapping = {'name': self.context.displayname}
        if IPerson.providedBy(self.context):
            self.is_person = True
        elif (IDistribution.providedBy(self.context) or
              IProduct.providedBy(self.context)):
            self.is_target = True
            self.is_pillar = True
            self.show_series = True
        elif IProject.providedBy(self.context):
            self.is_project = True
            self.is_pillar = True
            self.show_target = True
            self.show_series = True
        elif IProjectSeries.providedBy(self.context):
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
            raise AssertionError, 'Unknown blueprint listing site'

        if self.is_person:
            self.title = _('Specifications involving $name', mapping=mapping)
        else:
            self.title = _('Specifications for $name', mapping=mapping)

        if IHasDrivers.providedBy(self.context):
            self.has_drivers = True

        self.batchnav = BatchNavigator(
            self.specs, self.request,
            size=config.launchpad.default_batch_size)

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
            if categories.has_key(spec.definition_status):
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
        """Return <quantity> latest specs created for this target. This
        is used by the +portlet-latestspecs view.
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

    @property
    def label(self):
        return smartquote('Current documentation for "%s"' %
                          self.context.displayname)


class RegisterABlueprintButtonView:
    """View that renders a button to register a blueprint on its context."""

    def __call__(self):
        # Check if the context has an +addspec view available.
        if queryMultiAdapter(
            (self.context, self.request), name='+addspec'):
            target = self.context
        else:
            # otherwise find an adapter to ISpecificationTarget which will.
            target = ISpecificationTarget(self.context)

        return """
              <a href="%s/+addspec" id="addspec">
                <img
                  alt="Register a blueprint"
                  src="/+icing/but-sml-registerablueprint.gif"
                />
              </a>
        """ % canonical_url(target, rootsite='blueprints')


class HasSpecificationsOnBlueprintsVHostBreadcrumb(Breadcrumb):
    rootsite = 'blueprints'

    @property
    def text(self):
        return 'Blueprints for %s' % self.context.title


class PersonOnBlueprintsVHostBreadcrumb(Breadcrumb):
    rootsite = 'blueprints'

    @property
    def text(self):
        return 'Blueprints involving %s' % self.context.displayname
