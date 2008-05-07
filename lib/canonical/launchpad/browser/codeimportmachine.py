# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Browser views for CodeImportMachines."""

__metaclass__ = type

__all__ = [
    'CodeImportMachineSetNavigation',
    'CodeImportMachineSetView',
    'CodeImportMachineView',
    ]


from zope.component import getUtility
from zope.interface import Interface
from zope.schema import TextLine

from canonical.cachedproperty import cachedproperty
from canonical.launchpad import _
from canonical.launchpad.interfaces import (
    CodeImportEventDataType, CodeImportMachineOfflineReason,
    CodeImportMachineState, ICodeImportEvent, ICodeImportMachineSet)
from canonical.launchpad.webapp import (
    action, canonical_url, GetitemNavigation, LaunchpadFormView, LaunchpadView)
from canonical.lazr import decorates


class CodeImportMachineSetNavigation(GetitemNavigation):
    """Navigation methods for IBuilder."""
    usedfor = ICodeImportMachineSet

    def breadcrumb(self):
        return u'Machines'


class CodeImportMachineSetView(LaunchpadView):
    """The view for the page that shows all the import machines."""

    __used_for__ = ICodeImportMachineSet

    label = "Import machines for Launchpad"

    @property
    def machines(self):
        """Get the machines, sorted alphabetically by hostname."""
        return getUtility(ICodeImportMachineSet).getAll()


class UpdateMachineStateForm(Interface):
    """An interface to allow the user to enter a reason for quiescing."""

    reason = TextLine(
        title=_('Reason'), required=False, description=_(
            "Why the machine state changing."))

class DecoratedEvent:

    decorates(ICodeImportEvent, 'event')

    def __init__(self, event):
        self.event = event

    @cachedproperty
    def items(self):
        return self.event.items()


class CodeImportMachineView(LaunchpadFormView):

    schema = UpdateMachineStateForm

    # The default reason is always the empty string.
    initial_values = {'reason': ''}

    @property
    def latest_events(self):
        return [DecoratedEvent(event) for event in self.context.events[:10]]

    @property
    def adapters(self):
        """See `LaunchpadFormView`"""
        return {UpdateMachineStateForm: self.context}

    def _canChangeToState(self, action):
        next_state = action.data['next_state']
        if next_state == CodeImportMachineState.QUIESCING:
            return self.context.state == CodeImportMachineState.ONLINE
        else:
            return self.context.state != next_state

    @action('Set Online', name='set_online',
            data={'next_state': CodeImportMachineState.ONLINE},
            condition=_canChangeToState)
    def set_online_action(self, action, data):
        self.context.setOnline(self.user, data['reason'])
        self.next_url = canonical_url(self.context)

    @action('Set Offline', name='set_offline',
            data={'next_state': CodeImportMachineState.OFFLINE},
            condition=_canChangeToState)
    def set_offline_action(self, action, data):
        self.context.setOffline(
            CodeImportMachineOfflineReason.STOPPED, self.user, data['reason'])
        self.next_url = canonical_url(self.context)

    @action('Set Quiescing', name='set_quiescing',
            data={'next_state': CodeImportMachineState.QUIESCING},
            condition=_canChangeToState)
    def set_quiescing_action(self, action, data):
        self.context.setQuiescing(self.user, data['reason'])
        self.next_url = canonical_url(self.context)
