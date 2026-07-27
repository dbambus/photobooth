#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Photobooth - a flexible photo booth software
# Copyright (C) 2018  Balthasar Reuter <photobooth at re - web dot eu>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import os
import sys

# Prefer PyQt6 over PyQt5 when both are installed - e.g. on a system where
# PyQt5 is still around for other applications. qtpy reads QT_API at import
# time, so this has to happen before any of our modules import it.
# An explicit QT_API set by the operator always wins.
if "QT_API" not in os.environ:
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        pass
    else:
        os.environ["QT_API"] = "pyqt6"

from .main import main

name = "photobooth"

if __name__ == "__main__":
    sys.exit(main(sys.argv))
