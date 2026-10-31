"""Variants of variation definitions and usages (SysML 8.3.6.5): VariantMembership.

A variation (``variation part def V { variant part a; ... }``) owns each of
its variants through a :class:`VariantMembership`; the derived ``variants``
and ``variant_memberships`` of definitions and usages are installed by
:mod:`sysmlv2.derived`. :func:`add_variant` builds the membership.
"""
from __future__ import annotations

from typing import Optional

from kerml.namespaces import OwningMembership

from .definitions import Definition, Usage


class VariantMembership(OwningMembership):
    """Owns a variant Usage of a variation Definition or Usage (SysML 8.3.6.5)."""

    kind = "VariantMembership"

    @property
    def owned_variant_usage(self) -> Optional[Usage]:
        """The owned variant (spec ``ownedVariantUsage``)."""
        m = self.owned_member_element
        return m if isinstance(m, Usage) else None


def add_variant(variation: Definition | Usage, variant: Usage) -> VariantMembership:
    """Own `variant` as a variant of `variation` (``variant`` in a variation body)."""
    variation.own(variant, membership=VariantMembership)
    variant.is_variant = True
    return variant.owning_relationship  # type: ignore[return-value]


__all__ = ["VariantMembership", "add_variant"]
