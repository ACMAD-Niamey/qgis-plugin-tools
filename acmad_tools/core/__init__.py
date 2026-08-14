# -*- coding: utf-8 -*-
"""Shared infrastructure for ACMAD Tools.

Code here is not specific to any single tool -- e.g. ``settings_manager``
persists the backend base URL/API token that every tool in ``tools/`` is
expected to reuse rather than each rolling its own connection settings.
"""
