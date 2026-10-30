"""SysML textual notation (stub)."""
from .kerml import KerMLParser


class SysMLParser(KerMLParser):
    LANGUAGE = "sysml"
