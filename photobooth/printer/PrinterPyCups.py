#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Photobooth - a flexible photo booth software
# Copyright (C) 2019  Balthasar Reuter <photobooth at re - web dot eu>
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
#
# This class was contributed by
# @oelegeirnaert (https://github.com/oelegeirnaert)
# see https://github.com/reuterbal/photobooth/pull/113

import logging
import os
import re

try:
    import cups
except ImportError:
    logging.error("pycups is not installed")
    cups = None

from PIL import ImageQt

from . import Printer

# Matches the physical size PPDs commonly spell out in the human-readable
# half of a *PageSize entry, e.g. "Postcard/Postcard 100x148mm".
_PAGE_SIZE_MM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*mm")
_SIZE_MATCH_TOLERANCE_MM = 2


def _findMediaName(ppd_filename, width_mm, height_mm):
    """Find the PPD's PageSize keyword matching the configured page size.

    Many photo printers - the Selphy line among them - only offer a
    handful of fixed page sizes and reject an arbitrary "Custom.WxHmm"
    media string outright, or silently fall back to their own default.
    Reading the physical size out of the PPD instead works with whatever
    sizes the installed printer/driver actually supports.
    """
    with open(ppd_filename, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("*PageSize "):
                continue
            match = _PAGE_SIZE_MM_RE.search(line)
            if not match:
                continue
            keyword = line.split()[1].split("/")[0]
            for a, b in (
                (match.group(1), match.group(2)),
                (match.group(2), match.group(1)),
            ):
                if (
                    abs(float(a) - width_mm) <= _SIZE_MATCH_TOLERANCE_MM
                    and abs(float(b) - height_mm) <= _SIZE_MATCH_TOLERANCE_MM
                ):
                    return keyword

    return None


class PrinterPyCups(Printer):
    def __init__(self, page_size, num_prints, print_pdf=False):
        super().__init__(page_size, num_prints)

        self._conn = cups.Connection() if cups else None

        if print_pdf:
            logging.error("Printing to PDF not supported with pycups")
            self._conn = None

        if os.access("/dev/shm", os.W_OK):
            self._tmp_filename = "/dev/shm/print.jpg"
        else:
            self._tmp_filename = "/tmp/print.jpg"
        logging.debug('Storing temp files to "{}"'.format(self._tmp_filename))

        self._printer = None
        self._media_name = None
        if self._conn is not None:
            self._printer = self._conn.getDefault()
            logging.info('Using printer "%s"', self._printer)

            ppd_filename = self._conn.getPPD(self._printer)
            try:
                self._media_name = _findMediaName(ppd_filename, *page_size)
                if self._media_name is None:
                    logging.warning(
                        "No page size matching {}x{}mm in the PPD of "
                        '"{}", using the printer\'s default'.format(
                            page_size[0], page_size[1], self._printer
                        )
                    )
                else:
                    logging.info(
                        'Page size {}x{}mm maps to PPD media "{}"'.format(
                            page_size[0], page_size[1], self._media_name
                        )
                    )
            finally:
                os.remove(ppd_filename)

    def is_connected(self):
        if self._conn is None or self._printer is None:
            return False

        try:
            attrs = self._conn.getPrinterAttributes(self._printer)
        except cups.IPPError as e:
            logging.warning('Could not query printer state: "{}"'.format(e))
            return False

        # 5 is IPP_PRINTER_STOPPED - covers a disconnected USB printer as
        # well as one that is out of paper/ribbon or otherwise erroring.
        return attrs.get("printer-state") != 5

    def print(self, picture):
        options = {"media": self._media_name} if self._media_name else {}

        for n in range(self.num_prints):
            logging.info("Printing picture, {} of {}".format(n + 1, self.num_prints))
            if self._conn is not None:
                if isinstance(picture, ImageQt.ImageQt):
                    picture.save(self._tmp_filename)
                else:
                    picture.save(self._tmp_filename, format="JPEG")
                self._conn.printFile(
                    self._printer, self._tmp_filename, "photobooth", options
                )
