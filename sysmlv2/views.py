"""Renderings of views (SysML 8.3.26): RenderingDefinition, RenderingUsage, ViewRenderingMembership.

A view (``ViewDefinition`` / ``ViewUsage`` in :mod:`sysmlv2.definitions`) is
rendered by a RenderingUsage owned through a :class:`ViewRenderingMembership`
(``render r;``); the derived ``view_rendering`` of views is installed by
:mod:`sysmlv2.derived`.
"""
from __future__ import annotations

from typing import Optional

from kerml.features import Feature
from kerml.types import FeatureMembership

from .actions import referenced_feature_target
from .definitions import PartDefinition, PartUsage


class RenderingDefinition(PartDefinition):
    """Defines how a view is rendered (SysML 8.3.26.5)."""

    kind = "RenderingDefinition"


class RenderingUsage(PartUsage):
    """A usage of a RenderingDefinition (SysML 8.3.26.6)."""

    kind = "RenderingUsage"


class ViewRenderingMembership(FeatureMembership):
    """Owns the rendering of a view (``render r;``, SysML 8.3.26.10)."""

    kind = "ViewRenderingMembership"

    @property
    def owned_rendering(self) -> Optional[RenderingUsage]:
        """The owned RenderingUsage (spec ``ownedRendering``)."""
        m = self.owned_member_element
        return m if isinstance(m, RenderingUsage) else None

    @property
    def referenced_rendering(self) -> Optional[RenderingUsage]:
        """The rendering the owned rendering references (the feature target of its owned
        ReferenceSubsetting), else the owned rendering (spec ``referencedRendering``)."""
        owned = self.owned_member_element
        if not isinstance(owned, Feature):
            return None
        target = referenced_feature_target(owned)
        if target is None:
            return owned if isinstance(owned, RenderingUsage) else None
        return target if isinstance(target, RenderingUsage) else None


__all__ = ["RenderingDefinition", "RenderingUsage", "ViewRenderingMembership"]
