# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Registry-specific testing infrastructure for Windmill."""

__metaclass__ = type
__all__ = [
    'RegistryWindmillLayer',
    'RegistryYUITestLayer',
    ]


from canonical.testing.layers import (
    BaseWindmillLayer,
    BaseYUITestLayer,
    )


class RegistryWindmillLayer(BaseWindmillLayer):
    """Layer for Registry Windmill tests."""

    @classmethod
    def setUp(cls):
        cls.base_url = cls.appserver_root_url()
        super(RegistryWindmillLayer, cls).setUp()


class RegistryYUITestLayer(BaseYUITestLayer):
    """Layer for Code YUI tests."""

    @classmethod
    def setUp(cls):
        cls.base_url = cls.appserver_root_url()
        super(RegistryYUITestLayer, cls).setUp()
