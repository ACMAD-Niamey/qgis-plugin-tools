# -*- coding: utf-8 -*-
"""Container package for individual ACMAD Tools plugin tools.

Each subpackage here (e.g. ``forecast_ingest``) is a self-contained tool
that exposes a ``tool.py`` module with a class implementing the small
duck-typed tool interface described in the repository README ("Adding a
new tool"): ``__init__(iface)``, ``name``, ``icon()``, ``initGui(menu,
toolbar)``, ``unload()``.
"""
