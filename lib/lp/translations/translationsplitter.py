# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type


from storm.locals import ClassAlias, Store

from lp.translations.model.potemplate import POTemplate
from lp.translations.model.translationtemplateitem import (
    TranslationTemplateItem,
    )


class TranslationSplitter:
    """Split translations for a productseries, sourcepackage pair.

    If a productseries and sourcepackage were linked in error, and then
    unlinked, they may still share some translations.  This class breaks those
    associations.
    """

    def __init__(self, productseries, sourcepackage):
        self.productseries = productseries
        self.sourcepackage = sourcepackage

    def findShared(self):
        """Provide tuples of upstream, ubuntu for each shared POTMsgSet."""
        store = Store.of(self.productseries)
        UpstreamItem = ClassAlias(TranslationTemplateItem, 'UpstreamItem')
        UpstreamTemplate = ClassAlias(POTemplate, 'UpstreamTemplate')
        UbuntuItem = ClassAlias(TranslationTemplateItem, 'UbuntuItem')
        UbuntuTemplate = ClassAlias(POTemplate, 'UbuntuTemplate')
        return store.find(
            (UpstreamItem, UbuntuItem),
            UpstreamItem.potmsgsetID == UbuntuItem.potmsgsetID,
            UbuntuItem.potemplateID == UbuntuTemplate.id,
            UbuntuTemplate.sourcepackagenameID ==
                self.sourcepackage.sourcepackagename.id,
            UbuntuTemplate.distroseriesID ==
                self.sourcepackage.distroseries.id,
            UpstreamItem.potemplateID == UpstreamTemplate.id,
            UpstreamTemplate.productseriesID == self.productseries.id,
        )

    @staticmethod
    def splitPOTMsgSet(ubuntu_item):
        new_potmsgset = ubuntu_item.potmsgset.clone()
        from zope.security.proxy import removeSecurityProxy
        removeSecurityProxy(ubuntu_item).potmsgset = new_potmsgset
        return new_potmsgset
