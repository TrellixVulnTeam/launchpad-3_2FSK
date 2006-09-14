# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

"""Specification views."""

__metaclass__ = type

__all__ = [
    'SpecificationContextMenu',
    'SpecificationNavigation',
    'SpecificationView',
    'SpecificationAddView',
    'SpecificationEditView',
    'SpecificationGoalProposeView',
    'SpecificationGoalDecideView',
    'SpecificationRetargetingView',
    'SpecificationSprintAddView',
    'SpecificationSupersedingView',
    'SpecificationTreePNGView',
    'SpecificationTreeImageTag',
    'SpecificationTreeDotOutput'
    ]

from subprocess import Popen, PIPE
from operator import attrgetter

from zope.component import getUtility
from zope.app.form.browser.itemswidgets import DropdownWidget

from canonical.cachedproperty import cachedproperty
from canonical.launchpad import _

from canonical.launchpad.interfaces import (
    IDistribution,
    ILaunchBag,
    IProduct,
    ISpecification,
    ISpecificationSet,
    )

from canonical.launchpad.browser.editview import SQLObjectEditView
from canonical.launchpad.browser.addview import SQLObjectAddView

from canonical.launchpad.webapp import (
    canonical_url, ContextMenu, Link, enabled_with_permission,
    LaunchpadView, Navigation, GeneralFormView, stepthrough)

from canonical.launchpad.helpers import check_permission

from canonical.lp.dbschema import SpecificationStatus


class SpecificationNavigation(Navigation):

    usedfor = ISpecification

    @stepthrough('+subscription')
    def traverse_subscriptions(self, name):
        return self.context.getSubscriptionByName(name)

    def traverse(self, name):
        # fallback to looking for a sprint with this name, with this feature
        # on the agenda
        return self.context.getSprintSpecification(name)


class SpecificationContextMenu(ContextMenu):

    usedfor = ISpecification
    links = ['alltarget', 'allgoal', 'edit', 'people', 'status', 'priority',
             'whiteboard', 'proposegoal',
             'milestone', 'requestfeedback', 'givefeedback', 'subscription',
             'subscribeanother',
             'linkbug', 'unlinkbug', 'adddependency', 'removedependency',
             'dependencytree', 'linksprint', 'supersede',
             'retarget', 'administer']

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        text = 'Administer'
        return Link('+admin', text, icon='edit')

    def alltarget(self):
        text = 'Other %s features' % self.context.target.displayname
        return Link(canonical_url(self.context.target), text, icon='list')

    def allgoal(self):
        enabled = self.context.goal is not None
        text = ''
        link = Link('dummy', 'dummy', enabled=enabled)
        if enabled:
            text = 'Other %s features' % self.context.goal.displayname
            link = Link(canonical_url(self.context.goal), text,
                icon='list', enabled=enabled)
        return link

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Edit title and summary'
        return Link('+edit', text, icon='edit')

    def givefeedback(self):
        text = 'Give feedback'
        enabled = (self.user is not None and
                   self.context.getFeedbackRequests(self.user))
        return Link('+givefeedback', text, icon='edit', enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def milestone(self):
        text = 'Target milestone'
        return Link('+milestone', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def people(self):
        text = 'Change people'
        return Link('+people', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def priority(self):
        text = 'Change priority'
        return Link('+priority', text, icon='edit')

    def requestfeedback(self):
        text = 'Request feedback'
        return Link('+requestfeedback', text, icon='edit')

    def proposegoal(self):
        text = 'Propose as goal'
        if self.context.goal is not None:
            text = 'Modify goal'
        if self.context.distribution is not None:
            link = '+setrelease'
        elif self.context.product is not None:
            link = '+setseries'
        else:
            raise AssertionError(
                'Unknown target on specification "%s".' % self.context.name)
        return Link(link, text, icon='edit')

    def status(self):
        text = 'Change status'
        return Link('+status', text, icon='edit')

    def subscribeanother(self):
        text = 'Subscribe someone'
        return Link('+addsubscriber', text, icon='add')

    def subscription(self):
        user = self.user
        if user is not None and self.context.subscription(user) is not None:
            text = 'Modify subscription'
        else:
            text = 'Subscribe yourself'
        return Link('+subscribe', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def supersede(self):
        text = 'Mark superseded'
        return Link('+supersede', text, icon='edit')

    def linkbug(self):
        text = 'Link to bug'
        return Link('+linkbug', text, icon='add')

    def unlinkbug(self):
        text = 'Remove bug link'
        enabled = bool(self.context.bugs)
        return Link('+unlinkbug', text, icon='add', enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def adddependency(self):
        text = 'Add dependency'
        return Link('+linkdependency', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def removedependency(self):
        text = 'Remove dependency'
        enabled = bool(self.context.dependencies)
        return Link('+removedependency', text, icon='remove', enabled=enabled)

    def dependencytree(self):
        text = 'Show dependencies'
        enabled = (
            bool(self.context.dependencies) or bool(self.context.blocked_specs)
            )
        return Link('+deptree', text, icon='info', enabled=enabled)

    def linksprint(self):
        text = 'Propose for meeting agenda'
        return Link('+linksprint', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def retarget(self):
        text = 'Retarget'
        return Link('+retarget', text, icon='edit')

    def whiteboard(self):
        text = 'Edit whiteboard'
        return Link('+whiteboard', text, icon='edit')


class SpecificationView(LaunchpadView):

    __used_for__ = ISpecification

    def initialize(self):
        # The review that the user requested on this spec, if any.
        self.feedbackrequests = []
        self.notices = []
        request = self.request

        # establish if a subscription form was posted
        sub = request.form.get('subscribe')
        upd = request.form.get('update')
        unsub = request.form.get('unsubscribe')
        essential = request.form.get('essential', False)
        if self.user and request.method == 'POST':
            if sub is not None:
                self.context.subscribe(self.user, essential)
                self.notices.append("You have subscribed to this spec.")
            elif upd is not None:
                self.context.subscribe(self.user, essential)
                self.notices.append('Your subscription has been updated.')
            elif unsub is not None:
                self.context.unsubscribe(self.user)
                self.notices.append("You have unsubscribed from this spec.")

        if self.user is not None:
            # establish if this user has a review queued on this spec
            self.feedbackrequests = self.context.getFeedbackRequests(self.user)
            if self.feedbackrequests:
                msg = "You have %d feedback request(s) on this specification."
                msg %= len(self.feedbackrequests)
                self.notices.append(msg)

    @property
    def subscription(self):
        """whether the current user has a subscription to the spec."""
        if self.user is None:
            return None
        return self.context.subscription(self.user)

    @cachedproperty
    def has_dep_tree(self):
        return self.context.dependencies or self.context.blocked_specs


class SpecificationAddView(SQLObjectAddView):

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self._nextURL = '.'
        SQLObjectAddView.__init__(self, context, request)

    def create(self, name, title, specurl, summary, status,
               owner, assignee=None, drafter=None, approver=None):
        """Create a new Specification."""
        # Inject the relevant product or distribution into the kw args.
        product = None
        distribution = None
        if IProduct.providedBy(self.context):
            product = self.context.id
        elif IDistribution.providedBy(self.context):
            distribution = self.context.id
        # clean up name
        name = name.strip().lower()
        spec = getUtility(ISpecificationSet).new(name, title, specurl,
            summary, status, owner, product=product,
            distribution=distribution, assignee=assignee, drafter=drafter,
            approver=approver)
        self._nextURL = canonical_url(spec)
        return spec

    def add(self, content):
        """Skipping 'adding' this content to a container, because
        this is a placeless system."""
        return content

    def nextURL(self):
        return self._nextURL


class SpecificationEditView(SQLObjectEditView):

    def changed(self):
        # we need to ensure that resolution is recorded if the spec is now
        # resolved
        user = getUtility(ILaunchBag).user
        newstate = self.context.updateLifecycleStatus(user)
        if newstate is not None:
            self.request.response.addNotification(
                'Specification is now considered "%s".' % newstate.title)
        self.request.response.redirect(canonical_url(self.context))


class SpecificationGoalProposeView(GeneralFormView):

    @property
    def initial_values(self):
        return {
            'productseries': self.context.productseries,
            'distrorelease': self.context.distrorelease,
            'whiteboard': self.context.whiteboard,
            }

    def process(self, productseries=None, distrorelease=None,
        whiteboard=None):
        # this can accept either distrorelease or productseries but the menu
        # system will only link to the relevant page for that type of spec
        # target (distro or upstream)
        if productseries and distrorelease:
            return 'Please choose a series OR a release, not both.'
        goal = None
        if productseries is not None:
            goal = productseries
        if distrorelease is not None:
            goal = distrorelease
        self.context.whiteboard = whiteboard
        self.context.proposeGoal(goal, self.user)
        # Now we want to auto-approve the goal if the person making
        # the proposal has permission to do this anyway
        if goal is not None and check_permission('launchpad.Driver', goal):
            self.context.acceptBy(self.user)
        self._nextURL = canonical_url(self.context)
        return 'Done.'


class SpecificationGoalDecideView(LaunchpadView):
    """View used to allow the drivers of a series or distrorelease to accept
    or decline the spec as a goal for that release. Typically they would use
    the multi-select goalset view on their series or release, but it's also
    useful for them to have this one-at-a-time view on the spec itself.
    """

    def initialize(self):
        accept = self.request.form.get('accept')
        decline = self.request.form.get('decline')
        cancel = self.request.form.get('cancel')
        decided = False
        if accept is not None:
            self.context.acceptBy(self.user)
            decided = True
        elif decline is not None:
            self.context.declineBy(self.user)
            decided = True
        if decided or cancel is not None:
            self.request.response.redirect(
                canonical_url(self.context))


class SpecificationRetargetingView(GeneralFormView):

    @property
    def initial_values(self):
        return {
            'product': self.context.product,
            'distribution': self.context.distribution,
            }

    def process(self, product=None, distribution=None):
        if product and distribution:
            return 'Please choose a product OR a distribution, not both.'
        if not (product or distribution):
            return 'Please choose a product or distribution for this spec.'
        # we need to ensure that there is not already a spec with this name
        # for this new target
        if product:
            if product.getSpecification(self.context.name) is not None:
                return '%s already has a spec called %s' % (
                    product.name, self.context.name)
        elif distribution:
            if distribution.getSpecification(self.context.name) is not None:
                return '%s already has a spec called %s' % (
                    distribution.name, self.context.name)
        self.context.retarget(product=product, distribution=distribution)
        self._nextURL = canonical_url(self.context)
        return 'Done.'


class SpecificationSupersedingView(GeneralFormView):

    @property
    def initial_values(self):
        return {
            'superseded_by': self.context.superseded_by,
            }

    def process(self, superseded_by=None):
        self.context.superseded_by = superseded_by
        if superseded_by is not None:
            # set the state to superseded
            self.context.status = SpecificationStatus.SUPERSEDED
        else:
            # if the current state is SUPERSEDED and we are now removing the
            # superseded-by then we should move this spec back into the
            # drafting pipeline by resetting its status to NEW
            if self.context.status == SpecificationStatus.SUPERSEDED:
                self.context.status = SpecificationStatus.NEW
        newstate = self.context.updateLifecycleStatus(self.user)
        if newstate is not None:
            self.request.response.addNotification(
                'Specification is now considered "%s".' % newstate.title)
        self.request.response.redirect(canonical_url(self.context))
        return 'Done.'


class SupersededByWidget(DropdownWidget):
    """Custom select widget for specification superseding.

    This is just a standard DropdownWidget with the (no value) text
    rendered as something meaningful to the user, as per Bug #4116.

    TODO: This should be replaced with something more scalable as there
    is no upper limit to the number of specifications.
    -- StuartBishop 20060704
    """
    _messageNoValue = _("(Not Superseded)")


class SpecGraph:
    """A directed linked graph of nodes representing spec dependencies."""

    # We want to be able to test SpecGraph and SpecGraphNode without setting
    # up canonical_urls.  This attribute is used by tests to generate URLs for
    # nodes without calling canonical_url.
    # The pattern is either None (meaning use canonical_url) or a string
    # containing one '%s' replacement marker.
    url_pattern_for_testing = None

    def __init__(self):
        self.nodes = set()
        self.edges = set()
        self.root_node = None

    def newNode(self, spec, root=False):
        """Return a new node based on the given spec.

        If root=True, make this the root node.

        There can be at most one root node set.
        """
        assert self.getNode(spec.name) is None, (
            "A spec called %s is already in the graph" % spec.name)
        node = SpecGraphNode(spec, root=root,
                url_pattern_for_testing=self.url_pattern_for_testing)
        self.nodes.add(node)
        if root:
            assert not self.root_node
            self.root_node = node
        return node

    def getNode(self, name):
        """Return the node with the given name.

        Return None if there is no such node.
        """
        # Efficiency: O(n)
        for node in self.nodes:
            if node.name == name:
                return node
        return None

    def newOrExistingNode(self, spec):
        """Return the node for the spec.

        If there is already a node for spec.name, return that node.
        Otherwise, create a new node for the spec, and return that.
        """
        node = self.getNode(spec.name)
        if node is None:
            node = self.newNode(spec)
        return node

    def link(self, from_node, to_node):
        """Form a direction link from from_node to to_node."""
        assert from_node in self.nodes
        assert to_node in self.nodes
        assert (from_node, to_node) not in self.edges
        self.edges.add((from_node, to_node))

    def addDependencyNodes(self, spec):
        """Add nodes for the specs that the given spec depends on,
        transitively.
        """
        get_related_specs_fn = attrgetter('dependencies')
        def link_nodes_fn(node, dependency):
            self.link(dependency, node)
        self.walkSpecsMakingNodes(spec, get_related_specs_fn, link_nodes_fn)

    def addBlockedNodes(self, spec):
        """Add nodes for the specs that the given spec blocks, transitively."""
        get_related_specs_fn = attrgetter('blocked_specs')
        def link_nodes_fn(node, blocked_spec):
            self.link(node, blocked_spec)
        self.walkSpecsMakingNodes(spec, get_related_specs_fn, link_nodes_fn)

    def walkSpecsMakingNodes(self, spec, get_related_specs_fn, link_nodes_fn):
        """Walk the specs, making and linking nodes.

        Examples of functions to use:

        get_related_specs_fn = lambda spec: spec.blocked_specs

        def link_nodes_fn(node, related):
            graph.link(node, related)
        """
        # This is a standard pattern for "flattening" a recursive algorithm.
        to_search = set([spec])
        visited = set()
        while to_search:
            current_spec = to_search.pop()
            visited.add(current_spec)
            node = self.newOrExistingNode(current_spec)
            related_specs = set(get_related_specs_fn(current_spec))
            for related_spec in related_specs:
                link_nodes_fn(node, self.newOrExistingNode(related_spec))
            to_search.update(related_specs.difference(visited))

    def getNodesSorted(self):
        """Return a list of all nodes, sorted by name."""
        return sorted(self.nodes, key=attrgetter('name'))

    def getEdgesSorted(self):
        """Return a list of all edges, sorted by name.

        An edge is a tuple (from_node, to_node).
        """
        return sorted(self.edges,
            key=lambda (from_node, to_node): (from_node.name, to_node.name))

    def listNodes(self):
        """Return a string of diagnostic output of nodes and edges.

        Used for debugging and in unit tests.
        """
        L = []
        edges = self.getEdgesSorted()
        if self.root_node:
            L.append('Root is %s' % self.root_node)
        else:
            L.append('Root is undefined')
        for node in self.getNodesSorted():
            L.append('%s:' % node)
            to_nodes = [to_node for from_node, to_node in edges
                        if from_node == node]
            L += ['    %s' % to_node.name for to_node in to_nodes]
        return '\n'.join(L)

    def getDOTGraphStatement(self):
        """Return a unicode string that is the DOT representation of this
        graph.

        graph : [ strict ] (graph | digraph) [ ID ] '{' stmt_list '}'
        stmt_list : [ stmt [ ';' ] [ stmt_list ] ]
        stmt : node_stmt | edge_stmt | attr_stmt | ID '=' ID | subgraph

        """
        graphname = 'deptree'
        graph_attrs = dict(
            mode='hier',
            # bgcolor='transparent',  # Fails with graphviz-cairo.
            bgcolor='#fcfcfc',  # Same as Launchpad page background.
            size='5.2,9',  # Width fits in centre of 3 col layout, 1024x768.
            ratio='auto',
            ranksep=0.25,
            nodesep=0.25
            )

        # Global node and edge attributes.
        node_attrs = dict(
            fillcolor='white',
            style='filled',
            fontname='Sans',
            fontsize=11
            )
        edge_attrs = dict(arrowhead='normal')

        L = []
        L.append('digraph %s {' % to_DOT_ID(graphname))
        L.append('graph')
        L.append(dict_to_DOT_attrs(graph_attrs))
        L.append('node')
        L.append(dict_to_DOT_attrs(node_attrs))
        L.append('edge')
        L.append(dict_to_DOT_attrs(edge_attrs))
        for node in self.getNodesSorted():
            L.append(node.getDOTNodeStatement())
        for from_node, to_node in self.getEdgesSorted():
            L.append('%s -> %s' % (
                to_DOT_ID(from_node.name), to_DOT_ID(to_node.name)))
        L.append('}')
        return u'\n'.join(L)


class SpecificationSprintAddView(SQLObjectAddView):

    def create(self, sprint):
        user = getUtility(ILaunchBag).user
        sprint_link = self.context.linkSprint(sprint, user)
        if check_permission('launchpad.Edit', sprint_link):
            sprint_link.acceptBy(user)
        return sprint_link

    def add(self, content):
        """Skipping 'adding' this content to a container, because
        this is a placeless system."""
        return content

    def nextURL(self):
        return canonical_url(self.context)


class SpecGraphNode:
    """Node in the spec dependency graph.

    A SpecGraphNode object has various display-related properties.
    """

    def __init__(self, spec, root=False, url_pattern_for_testing=None):
        self.name = spec.name
        if url_pattern_for_testing:
            self.URL = url_pattern_for_testing % self.name
        else:
            self.URL = canonical_url(spec)
        self.isRoot = root
        if self.isRoot:
            self.color = 'red'
        elif spec.is_complete:
            self.color = 'grey'
        else:
            self.color = 'black'
        self.comment = spec.title
        self.label = self.makeLabel(spec)
        self.tooltip = spec.title

    def makeLabel(self, spec):
        """Return a label for the spec."""
        if spec.assignee:
            label = '%s\n(%s)' % (spec.name, spec.assignee.name)
        else:
            label = spec.name
        return label

    def __str__(self):
        return '<%s>' % self.name

    def getDOTNodeStatement(self):
        """Return this node's data as a DOT unicode.

        This fills in the node_stmt in the DOT BNF:
        http://www.graphviz.org/doc/info/lang.html

        node_stmt : node_id [ attr_list ]
        node_id : ID [ port ]
        attr_list : '[' [ a_list ] ']' [ attr_list ]
        a_list  : ID [ '=' ID ] [ ',' ] [ a_list ]
        port : ':' ID [ ':' compass_pt ] | ':' compass_pt
        compass_pt : (n | ne | e | se | s | sw | w | nw)

        We don't care about the [ port ] part.

        """
        attrnames = ['color', 'comment', 'label', 'tooltip']
        if not self.isRoot:
            # We want to have links in the image map for all nodes
            # except the one that were currently on the page of.
            attrnames.append('URL')
        attrdict = dict((name, getattr(self, name)) for name in attrnames)
        return u'%s\n%s' % (to_DOT_ID(self.name), dict_to_DOT_attrs(attrdict))


def dict_to_DOT_attrs(some_dict, indent='    '):
    r"""Convert some_dict to unicode DOT attrs output.

    attr_list : '[' [ a_list ] ']' [ attr_list ]
    a_list  : ID [ '=' ID ] [ ',' ] [ a_list ]

    The attributes are sorted by dict key.

    >>> some_dict = dict(
    ...     foo='foo',
    ...     bar='bar " \n bar',
    ...     baz='zab')
    >>> print dict_to_DOT_attrs(some_dict, indent='  ')
      [
      "bar"="bar \" \n bar",
      "baz"="zab",
      "foo"="foo"
      ]

    """
    if not some_dict:
        return u''
    L = []
    L.append('[')
    for key, value in sorted(some_dict.items()):
        L.append('%s=%s,' % (to_DOT_ID(key), to_DOT_ID(value)))
    # Remove the trailing comma from the last attr.
    lastitem = L.pop()
    L.append(lastitem[:-1])
    L.append(']')
    return u'\n'.join('%s%s' % (indent, line) for line in L)


def to_DOT_ID(value):
    r"""Accept a value and return the DOT escaped version.

    The returned value is always a unicode string.

    >>> to_DOT_ID(u'foo " bar \n')
    u'"foo \\" bar \\n"'

    """
    if isinstance(value, str):
        unitext = unicode(value, encoding='ascii')
    else:
        unitext = unicode(value)
    output = unitext.replace(u'"', u'\\"')
    output = output.replace(u'\n', u'\\n')
    return u'"%s"' % output


class ProblemRenderingGraph(Exception):
    """There was a problem rendering the graph."""


class SpecificationTreeGraphView(LaunchpadView):
    """View for displaying the dependency tree as a PNG with image map."""

    def makeSpecGraph(self):
        """Return a SpecGraph object rooted on the spec that is self.context.
        """
        graph = SpecGraph()
        root = graph.newNode(self.context, root=True)
        graph.addDependencyNodes(self.context)
        graph.addBlockedNodes(self.context)
        return graph

    def getDotFileText(self):
        """Return a unicode string of the dot file text."""
        specgraph = self.makeSpecGraph()
        return specgraph.getDOTGraphStatement()

    def renderGraphvizGraph(self, format):
        """Return graph data in the appropriate format.

        Shell out to `dot` to do the work.
        Raise ProblemRenderingGraph exception if `dot` gives any error output.
        """
        assert format in ('png', 'cmapx')
        input = self.getDotFileText().encode('UTF-8')
        cmd = 'unflatten -l 2 | dot -T%s' % format
        process = Popen(
            cmd, shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE,
            close_fds=True)
        process.stdin.write(input)
        process.stdin.close()
        output = process.stdout.read()
        err = process.stderr.read()
        if err:
            raise ProblemRenderingGraph(err, output)
        return output


class SpecificationTreePNGView(SpecificationTreeGraphView):

    def render(self):
        """Render a PNG displaying the specification dependency graph."""
        self.request.response.setHeader('Content-type', 'image/png')
        return self.renderGraphvizGraph('png')


class SpecificationTreeImageTag(SpecificationTreeGraphView):

    def render(self):
        """Render the image and image map tags for this dependency graph."""
        return (u'<img src="deptree.png" usemap="#deptree" />\n' +
                self.renderGraphvizGraph('cmapx'))


class SpecificationTreeDotOutput(SpecificationTreeGraphView):

    def render(self):
        """Render the dep tree as a DOT file.

        This is useful for experimenting with the node layout offline.
        """
        self.request.response.setHeader('Content-type', 'text/plain')
        return self.getDotFileText()

