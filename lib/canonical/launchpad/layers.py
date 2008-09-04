# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Define the layers used in Launchpad.

Also define utilities that manipulate layers.
"""

__metaclass__ = type

from zope.interface import directlyProvides, directlyProvidedBy, Interface
from zope.publisher.interfaces.browser import IDefaultBrowserLayer

from canonical.lazr.interfaces.rest import (
    WebServiceLayer as LazrWebServiceLayer)


def setAdditionalLayer(request, layer):
    directlyProvides(request, directlyProvidedBy(request) + layer)


def setFirstLayer(request, layer):
    directlyProvides(request, layer, directlyProvidedBy(request))


class LaunchpadLayer(IDefaultBrowserLayer):
    """The `LaunchpadLayer` layer."""


class TranslationsLayer(LaunchpadLayer):
    """The `TranslationsLayer` layer."""


class BugsLayer(LaunchpadLayer):
    """The `BugsLayer` layer."""


class CodeLayer(LaunchpadLayer):
    """The `CodeLayer` layer."""


class BlueprintLayer(LaunchpadLayer):
    """The `BlueprintLayer` layer."""
BlueprintsLayer = BlueprintLayer


class AnswersLayer(LaunchpadLayer):
    """The `AnswersLayer` layer."""

# XXX sinzui 2008-09-04 bug=264783:
# Remove this layer.
class OpenIdLayer(LaunchpadLayer):
    """The `OpenId` layer."""


class IdLayer(LaunchpadLayer):
    """The new OpenID `Id` layer."""


class DebugLayer(Interface):
    """The `DebugLayer` layer.

    This derives from Interface beacuse it is just a marker that this
    is a debug-related request.
    """


class PageTestLayer(LaunchpadLayer):
    """The `PageTestLayer` layer. (need to register a 404 view for this and
    for the debug page too.  and make the debugview a base class in the
    debug view and make system error, not found and unauthorized and
    forbidden views.

    This layer is applied to the request that is used for running page tests.
    Pages registered with this layer are accessible to pagetests but return
    404s when visited interactively, so this should be used only for pages we
    want to maintain but not expose to users.

    The SystemErrorView base class looks at the request to see if it provides
    this interface.  If so, it renders tracebacks as plain text.
    """


class ShipItLayer(LaunchpadLayer):
    """The `ShipIt` layer."""


class ShipItUbuntuLayer(ShipItLayer):
    """The `ShipIt` for Ubuntu layer."""


class ShipItKUbuntuLayer(ShipItLayer):
    """The `ShipIt` for KUbuntu layer."""


class ShipItEdUbuntuLayer(ShipItLayer):
    """The `ShipIt` for EdUbuntu layer."""

class FeedsLayer(LaunchpadLayer):
    """The `FeedsLayer` Layer."""


class WebServiceLayer(LazrWebServiceLayer, LaunchpadLayer):
    """The layer for web service requests."""

