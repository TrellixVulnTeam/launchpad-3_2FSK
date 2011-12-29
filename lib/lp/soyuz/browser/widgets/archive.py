# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Widgets related to `IArchive`."""

__metaclass__ = type
__all__ = [
    'PPANameWidget',
    ]

import urlparse

from lp.services.config import config
from lp.app.widgets.textwidgets import URIComponentWidget


class PPANameWidget(URIComponentWidget):
    """A text input widget that looks like a URL path component entry."""

    @property
    def base_url(self):
        field = self.context
        owner = field.context
        if owner.private:
            root = config.personalpackagearchive.private_base_url
        else:
            root = config.personalpackagearchive.base_url
        return urlparse.urljoin(root, owner.name) + '/'
