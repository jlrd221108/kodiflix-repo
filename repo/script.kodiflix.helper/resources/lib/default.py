#!/usr/bin/python
# coding: utf-8

"""Command entry point for Kodiflix Helper maintenance actions."""

import os
import sys
import time

import xbmcgui

from service import (
    CACHE_DIRECTORY,
    CACHE_TOKEN_PROPERTY,
    HOME_WINDOW,
    clear_properties,
    ensure_cache_directory,
)


def clear_blur_cache():
    ensure_cache_directory()
    try:
        for entry in os.scandir(CACHE_DIRECTORY):
            if entry.is_file():
                try:
                    os.remove(entry.path)
                except OSError:
                    continue
    except OSError:
        pass
    clear_properties()
    HOME_WINDOW.setProperty(CACHE_TOKEN_PROPERTY, str(time.time()))
    xbmcgui.Dialog().notification("Kodiflix", "Blur cache cleared", time=2500)


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "action=clear_cache":
        clear_blur_cache()
