# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type


from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.testing.pages import find_tag_by_id
from canonical.testing.layers import DatabaseFunctionalLayer
from lp.blueprints.interfaces.specificationtarget import (
    IHasSpecifications,
    ISpecificationTarget,
    )
from lp.app.enums import ServiceUsage
from lp.blueprints.browser.specificationtarget import HasSpecificationsView
from lp.blueprints.publisher import BlueprintsLayer
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )
from lp.testing.matchers import IsConfiguredBatchNavigator
from lp.testing.views import (
    create_view,
    create_initialized_view,
    )


class TestRegisterABlueprintButtonView(TestCaseWithFactory):
    """Test specification menus links."""
    layer = DatabaseFunctionalLayer

    def verify_view(self, context, name):
        view = create_view(
            context, '+register-a-blueprint-button')
        self.assertEqual(
            'http://blueprints.launchpad.dev/%s/+addspec' % name,
            view.target_url)
        self.assertTrue(
            '<div id="involvement" class="portlet involvement">' in view())

    def test_specificationtarget(self):
        context = self.factory.makeProduct(name='almond')
        self.assertTrue(ISpecificationTarget.providedBy(context))
        self.verify_view(context, context.name)

    def test_adaptable_to_specificationtarget(self):
        context = self.factory.makeProject(name='hazelnut')
        self.assertFalse(ISpecificationTarget.providedBy(context))
        self.verify_view(context, context.name)

    def test_sprint(self):
        # Sprints are a special case. They are not ISpecificationTargets,
        # nor can they be adapted to a ISpecificationTarget,
        # but can create a spcification for a ISpecificationTarget.
        context = self.factory.makeSprint(title='Walnut', name='walnut')
        self.assertFalse(ISpecificationTarget.providedBy(context))
        self.verify_view(context, 'sprints/%s' % context.name)


class TestHasSpecificationsViewInvolvement(TestCaseWithFactory):
    """Test specification menus links."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson(name="macadamia")
        login_person(self.user)

    def verify_involvment(self, context):
        self.assertTrue(IHasSpecifications.providedBy(context))
        view = create_view(
            context, '+specs', layer=BlueprintsLayer, principal=self.user)
        self.assertTrue(
            '<div id="involvement" class="portlet involvement">' in view())

    def test_specificationtarget(self):
        context = self.factory.makeProduct(name='almond')
        naked_product = removeSecurityProxy(context)
        naked_product.blueprints_usage = ServiceUsage.LAUNCHPAD
        self.verify_involvment(context)

    def test_adaptable_to_specificationtarget(self):
        # A project should adapt to the products within to determine
        # involvment.
        context = self.factory.makeProject(name='hazelnut')
        product = self.factory.makeProduct(project=context)
        naked_product = removeSecurityProxy(product)
        naked_product.blueprints_usage = ServiceUsage.LAUNCHPAD
        self.verify_involvment(context)

    def test_sprint(self):
        context = self.factory.makeSprint(title='Walnut', name='walnut')
        self.verify_involvment(context)

    def test_person(self):
        context = self.factory.makePerson(name='pistachio')
        self.assertTrue(IHasSpecifications.providedBy(context))
        view = create_view(
            context, '+specs', layer=BlueprintsLayer, principal=self.user)
        self.assertFalse(
            '<div id="involvement" class="portlet involvement">' in view())

    def test_specs_batch(self):
        # Some pages turn up in very large contexts and patch. E.g.
        # Distro:+assignments which uses SpecificationAssignmentsView, a
        # subclass.
        person = self.factory.makePerson()
        view = create_initialized_view(person, name='+assignments')
        # Because +assignments is meant to provide an overview, we default to
        # 500 as the default batch size.
        matcher = IsConfiguredBatchNavigator(
            'specification', 'specifications', batch_size=500)
        self.assertThat(view.specs_batched, matcher)


class TestAssignments(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_assignments_are_batched(self):
        product = self.factory.makeProduct()
        spec1 = self.factory.makeSpecification(product=product)
        spec2 = self.factory.makeSpecification(product=product)
        view = create_initialized_view(product, name='+assignments',
            query_string="batch=1")
        content = view.render()
        self.assertEqual('next',
            find_tag_by_id(content, 'upper-batch-nav-batchnav-next')['class'])
        self.assertEqual('next',
            find_tag_by_id(content, 'lower-batch-nav-batchnav-next')['class'])


class TestHasSpecificationsTemplates(TestCaseWithFactory):
    """Tests the selection of templates based on blueprints usage."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestHasSpecificationsTemplates, self).setUp()
        self.user = self.factory.makePerson()
        login_person(self.user)

    def _test_templates_for_configuration(self, target, context=None):
        if context is None:
            context = target
        naked_target = removeSecurityProxy(target)
        test_configurations = [
            ServiceUsage.UNKNOWN,
            ServiceUsage.EXTERNAL,
            ServiceUsage.NOT_APPLICABLE,
            ServiceUsage.LAUNCHPAD,
            ]
        correct_templates = [
            HasSpecificationsView.not_launchpad_template.filename,
            HasSpecificationsView.not_launchpad_template.filename,
            HasSpecificationsView.not_launchpad_template.filename,
            HasSpecificationsView.default_template.filename,
            ]
        used_templates = list()
        for config in test_configurations:
            naked_target.blueprints_usage = config
            view = create_view(
                context,
                '+specs',
                layer=BlueprintsLayer,
                principal=self.user)
            used_templates.append(view.template.filename)
        self.assertEqual(correct_templates, used_templates)

    def test_product(self):
        product = self.factory.makeProduct()
        self._test_templates_for_configuration(product)

    def test_product_series(self):
        product = self.factory.makeProduct()
        product_series = self.factory.makeProductSeries(product=product)
        self._test_templates_for_configuration(
            target=product,
            context=product_series)

    def test_distribution(self):
        distribution = self.factory.makeDistribution()
        self._test_templates_for_configuration(distribution)

    def test_distroseries(self):
        distribution = self.factory.makeDistribution()
        distro_series = self.factory.makeDistroSeries(
            distribution=distribution)
        self._test_templates_for_configuration(
            target=distribution,
            context=distro_series)

    def test_projectgroup(self):
        project = self.factory.makeProject()
        product1 = self.factory.makeProduct(project=project)
        product2 = self.factory.makeProduct(project=project)
        self._test_templates_for_configuration(
            target=product1,
            context=project)


class TestHasSpecificationsConfiguration(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_cannot_configure_blueprints_product_no_edit_permission(self):
        product = self.factory.makeProduct()
        view = create_initialized_view(product, '+specs')
        self.assertEqual(False, view.can_configure_blueprints)

    def test_can_configure_blueprints_product_with_edit_permission(self):
        product = self.factory.makeProduct()
        login_person(product.owner)
        view = create_initialized_view(product, '+specs')
        self.assertEqual(True, view.can_configure_blueprints)

    def test_cant_configure_blueprints_distribution_no_edit_permission(self):
        distribution = self.factory.makeDistribution()
        view = create_initialized_view(distribution, '+specs')
        self.assertEqual(False, view.can_configure_blueprints)

    def test_can_configure_blueprints_distribution_with_edit_permission(self):
        distribution = self.factory.makeDistribution()
        login_person(distribution.owner)
        view = create_initialized_view(distribution, '+specs')
        self.assertEqual(True, view.can_configure_blueprints)

    def test_cannot_configure_blueprints_projectgroup(self):
        project_group = self.factory.makeProject()
        login_person(project_group.owner)
        view = create_initialized_view(project_group, '+specs')
        self.assertEqual(False, view.can_configure_blueprints)
