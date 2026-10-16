"""Independent NHC advisory-completeness auditor (read-only)."""
from .core import audit, markdown_report

__all__ = ("audit", "markdown_report")
