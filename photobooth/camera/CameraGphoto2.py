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

import io
import logging
import os
from datetime import datetime

from PIL import Image

import gphoto2 as gp

from .CameraInterface import CameraInterface

# Directory the captured JPEGs are backed up to. RAW files are left on the
# camera's card on purpose, so the card doubles as the RAW archive.
BACKUP_BASE_PATH = "~/Desktop/photobooth_backups"

JPEG_SUFFIXES = (".jpg", ".jpeg")
RAW_SUFFIXES = (".cr2", ".cr3", ".raw")


class CameraGphoto2(CameraInterface):
    def __init__(self):
        super().__init__()

        self.hasPreview = True
        self.hasIdle = True

        logging.info("Using python-gphoto2 bindings")

        self._setupLogging()
        self._setupCamera()

    def cleanup(self):
        self._changeConfig("Shutdown")
        try:
            self._cap.exit(self._ctxt)
        except gp.GPhoto2Error as e:
            logging.warning("Error during camera exit: {}".format(e))

    def _setupLogging(self):
        gp.error_severity[gp.GP_ERROR] = logging.ERROR
        gp.check_result(gp.use_python_logging())

    def _setupCamera(self):
        self._ctxt = gp.Context()
        self._cap = gp.Camera()
        self._cap.init(self._ctxt)

        logging.info("Camera summary: %s", str(self._cap.get_summary(self._ctxt)))

        # read model specific configuration
        config = self._cap.get_config(self._ctxt)
        self.loadConfig(config.get_child_by_name("cameramodel").get_value())

        # set startup configuration
        self._changeConfig("Startup")

        #  print current config
        self._printConfig(self._cap.get_config(self._ctxt))

    @staticmethod
    def _configTreeToText(tree, indent=0):
        config_txt = ""

        for chld in tree.get_children():
            config_txt += indent * " "
            config_txt += chld.get_label() + " [" + chld.get_name() + "]: "

            if chld.count_children() > 0:
                config_txt += "\n"
                config_txt += CameraGphoto2._configTreeToText(chld, indent + 4)
            else:
                config_txt += str(chld.get_value())
                try:
                    choice_txt = " ("

                    for c in chld.get_choices():
                        choice_txt += c + ", "

                    choice_txt += ")"
                    config_txt += choice_txt
                except gp.GPhoto2Error:
                    pass
                config_txt += "\n"

        return config_txt

    @staticmethod
    def _printConfig(config):
        config_txt = "Camera configuration:\n"
        config_txt += CameraGphoto2._configTreeToText(config)
        logging.info(config_txt)

    def _changeConfig(self, state):
        if self.config[state]:
            config = self._cap.get_config(self._ctxt)

            for key in self.config[state]:
                val = config.get_child_by_name(key)
                if val.get_value().lower() != self.config[state][key].lower():
                    val.set_value(self.config[state][key])

            try:
                self._cap.set_config(config, self._ctxt)
            except Exception as e:
                logging.warning(
                    'CameraGphoto2: Applying config for state "{}" failed: {}'.format(
                        state, e
                    )
                )

    def _fileGet(self, folder, name, file_type):
        """Download a file from the camera.

        python-gphoto2 changed the signature of ``Camera.file_get`` between
        releases: older builds return the ``CameraFile``, newer ones expect it
        to be passed in. Support both so the same code runs on Debian's
        packaged bindings and on a pip-installed version.
        """
        try:
            camera_file = gp.CameraFile()
            self._cap.file_get(folder, name, file_type, camera_file, self._ctxt)
            return camera_file
        except TypeError as e:
            if "expected at most 4 arguments" not in str(e):
                raise
            return self._cap.file_get(folder, name, file_type, self._ctxt)

    def setActive(self):
        config = self._cap.get_config(self._ctxt)
        try:
            # Force the viewfinder on, otherwise the EOS RP drops out of
            # live view and the preview stalls.
            config.get_child_by_name("viewfinder").set_value(1)

            # Route the output to the PC so the camera's own screen does not
            # compete with the USB connection.
            config.get_child_by_name("output").set_value("PC")

            self._cap.set_config(config, self._ctxt)
        except (gp.GPhoto2Error, ValueError) as e:
            logging.warning("Could not lock live view: {}".format(e))

        self._changeConfig("Active")

    def setIdle(self):
        self._changeConfig("Idle")

    def setCaptureRaw(self, enabled):
        section = "Startup" if enabled else "StartupNoRaw"

        if not self.config.has_section(section):
            logging.warning(
                'Camera config has no section "{}", keeping the file format '
                "as it is".format(section)
            )
            return

        logging.info(
            "RAW capture {}, applying [{}]".format(
                "enabled" if enabled else "disabled", section
            )
        )
        self._changeConfig(section)

    def getPreview(self):
        try:
            camera_file = gp.CameraFile()
            self._cap.capture_preview(camera_file, self._ctxt)
            file_data = camera_file.get_data_and_size()

            # Return raw bytes. Passing those across the process boundary is
            # safer than a PIL object backed by a gphoto2 file handle.
            return bytes(file_data)
        except gp.GPhoto2Error as e:
            logging.warning("Preview capture failed: {}".format(e))
            return None

    def _findCapturedFiles(self, folder, base_name):
        """Return (jpeg_name, raw_name) written for a single shutter release."""
        jpeg_name = None
        raw_name = None

        file_list = self._cap.folder_list_files(folder, self._ctxt)

        for i in range(gp.gp_list_count(file_list)):
            ret, file_name = gp.gp_list_get_name(file_list, i)

            if ret != gp.GP_OK:
                logging.warning(
                    "Failed to get filename at index {}: {}".format(
                        i, gp.gp_result_as_string(ret)
                    )
                )
                continue

            if os.path.splitext(file_name)[0] != base_name:
                continue

            if file_name.lower().endswith(JPEG_SUFFIXES):
                jpeg_name = file_name
            elif file_name.lower().endswith(RAW_SUFFIXES):
                raw_name = file_name

            if jpeg_name and raw_name:
                break

        return jpeg_name, raw_name

    def _backupPath(self, file_name):
        backup_dir = os.path.join(
            os.path.expanduser(BACKUP_BASE_PATH), datetime.now().strftime("%Y-%m-%d")
        )
        os.makedirs(backup_dir, exist_ok=True)
        return os.path.join(backup_dir, file_name)

    def _getJpeg(self, folder, file_name):
        """Download the camera's JPEG and keep a copy on disk.

        Returns the raw JPEG bytes rather than a PIL image: the caller can
        pass them on untouched and save a decode/encode round trip.
        """
        logging.info("Downloading JPEG file: {}".format(file_name))

        camera_file = self._fileGet(folder, file_name, gp.GP_FILE_TYPE_NORMAL)
        file_data = bytes(camera_file.get_data_and_size())
        logging.info("JPEG file data length: {}".format(len(file_data)))

        try:
            backup_path = self._backupPath(file_name)
            with open(backup_path, "wb") as f:
                f.write(file_data)
            logging.info("Saved JPEG backup to: {}".format(backup_path))
        except OSError as e:
            # A failing backup must not cost us the picture.
            logging.error("Could not write JPEG backup: {}".format(e))

        return file_data

    def _getJpegFromRaw(self, folder, file_name):
        """Fallback for cameras configured to write RAW only.

        Not used in the normal RAW+JPEG setup, so ``rawpy`` is imported lazily
        and stays an optional dependency.
        """
        logging.info("No JPEG on camera, converting RAW file: {}".format(file_name))

        try:
            import rawpy
        except ImportError:
            logging.error("rawpy is not installed, cannot convert RAW to JPEG")
            return None

        camera_file = self._fileGet(folder, file_name, gp.GP_FILE_TYPE_RAW)
        file_data = bytes(camera_file.get_data_and_size())

        with rawpy.imread(io.BytesIO(file_data)) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                no_auto_bright=False,
                output_bps=8,
            )

        logging.info("Converted RAW file {} to JPEG in memory".format(file_name))
        return Image.fromarray(rgb)

    def getPicture(self):
        """Take a picture.

        Returns the JPEG bytes straight from the camera, or a PIL image when
        a RAW file had to be developed instead. Camera handles both.
        """
        try:
            file_info = self._cap.capture(gp.GP_CAPTURE_IMAGE, self._ctxt)
            logging.info(
                "Captured file path: Folder='{}', Name='{}'".format(
                    file_info.folder, file_info.name
                )
            )

            base_name = os.path.splitext(file_info.name)[0]
            jpeg_name, raw_name = self._findCapturedFiles(file_info.folder, base_name)

            # The RAW file is deliberately left on the card and never
            # downloaded when a JPEG is available - transferring ~25 MB per
            # shot over USB would stall the photobooth.
            if jpeg_name:
                return self._getJpeg(file_info.folder, jpeg_name)

            logging.warning(
                "No JPEG file found on camera with base name '{}'".format(base_name)
            )

            if raw_name:
                return self._getJpegFromRaw(file_info.folder, raw_name)

            logging.error("Camera wrote neither a JPEG nor a RAW file")
            return None

        except gp.GPhoto2Error as e:
            logging.error("GPhoto2 error during capture: {}".format(e))
            return None
        except Exception as e:
            logging.error("Unexpected error during capture: {}".format(e))
            return None
