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

import logging
import time

from PIL import Image, ImageOps
from io import BytesIO

from .PictureDimensions import PictureDimensions
from .. import StateMachine
from ..Threading import Workers

# Pause between a failed capture and the next automatic retry.
RETRY_DELAY_SECONDS = 0.5

# Available camera modules as tuples of (config name, module name, class name)
modules = (
    ('python-gphoto2', 'CameraGphoto2', 'CameraGphoto2'),
    ('gphoto2-cffi', 'CameraGphoto2Cffi', 'CameraGphoto2Cffi'),
    ('gphoto2-commandline', 'CameraGphoto2CommandLine',
     'CameraGphoto2CommandLine'),
    ('opencv', 'CameraOpenCV', 'CameraOpenCV'),
    ('picamera', 'CameraPicamera', 'CameraPicamera'),
    ('dummy', 'CameraDummy', 'CameraDummy'))


class Camera:

    def __init__(self, config, comm, CameraModule):

        super().__init__()

        self._comm = comm
        self._cfg = config
        self._cam = CameraModule

        self._cap = None
        self._pic_dims = None

        self._is_preview = self._cfg.getBool('Photobooth', 'show_preview')
        self._is_keep_pictures = self._cfg.getBool('Storage', 'keep_pictures')
        self._capture_error_retry = self._cfg.getInt(
            'Photobooth', 'capture_error_retry')

        rot_vals = {0: None, 90: Image.ROTATE_90, 180: Image.ROTATE_180,
                    270: Image.ROTATE_270}
        self._rotation = rot_vals[self._cfg.getInt('Camera', 'rotation')]

    def startup(self):

        self._cap = self._cam()

        logging.info('Using camera {} preview functionality'.format(
            'with' if self._is_preview else 'without'))

        self._cap.setCaptureRaw(self._cfg.getBool('Camera', 'capture_raw'))

        test_picture = self._getPictureWithRetry('Startup')
        test_picture = self._toImage(test_picture)
        if self._rotation is not None:
            test_picture = test_picture.transpose(self._rotation)

        self._pic_dims = PictureDimensions(self._cfg, test_picture.size)
        self._is_preview = self._is_preview and self._cap.hasPreview

        background = self._cfg.get('Picture', 'background')
        if len(background) > 0:
            logging.info('Using background "{}"'.format(background))
            bg_picture = Image.open(background)
            self._template = bg_picture.resize(self._pic_dims.outputSize)
        else:
            self._template = Image.new('RGB', self._pic_dims.outputSize,
                                       (255, 255, 255))

        self.setIdle()
        logging.info('Idle waiting for camera events')
        self._comm.send(Workers.MASTER, StateMachine.CameraEvent('ready'))

    def teardown(self, state):

        if self._cap is not None:
            self._cap.cleanup()

    def run(self):

        for state in self._comm.iter(Workers.CAMERA):
            self.handleState(state)

        return True

    def handleState(self, state):

        if isinstance(state, StateMachine.StartupState):
            self.startup()
        elif isinstance(state, StateMachine.GreeterState):
            self.prepareCapture()
        elif isinstance(state, StateMachine.CountdownState):
            self.capturePreview()
        elif isinstance(state, StateMachine.CaptureState):
            self.capturePicture(state)
        elif isinstance(state, StateMachine.AssembleState):
            self.assemblePicture()
        elif isinstance(state, StateMachine.TeardownState):
            self.teardown(state)

    def setActive(self):

        self._cap.setActive()

    def setIdle(self):

        if self._cap.hasIdle:
            self._cap.setIdle()

    def prepareCapture(self):

        self.setActive()
        self._pictures = []

    def capturePreview(self):

        if self._is_preview:
            while self._comm.empty(Workers.CAMERA):
                picture = self._cap.getPreview()
                if picture is None:
                    continue
                picture = self._toImage(picture)
                if self._rotation is not None:
                    picture = picture.transpose(self._rotation)
                picture = picture.resize(self._pic_dims.previewSize)
                picture = ImageOps.mirror(picture)
                byte_data = BytesIO()
                picture.save(byte_data, format='jpeg', quality=70)
                self._comm.send(Workers.GUI,
                                StateMachine.CameraEvent('preview', byte_data))

    @staticmethod
    def _toImage(picture):

        # CameraGphoto2 hands out the raw JPEG bytes it received from the
        # camera, the other modules return a PIL image directly.
        if isinstance(picture, (bytes, bytearray)):
            return Image.open(BytesIO(picture))

        return picture

    def _getPictureWithRetry(self, context):
        """Fetch a picture from the camera, retrying on failure.

        A transient hiccup (a dropped USB frame, a slow write to the card)
        should not immediately drop into the manual-retry error dialog.
        [Photobooth] capture_error_retry controls how many extra attempts
        are made before giving up and raising, which is what still triggers
        that dialog.
        """
        attempts = self._capture_error_retry + 1

        for attempt in range(1, attempts + 1):
            try:
                picture = self._cap.getPicture()
            except Exception as e:
                picture = None
                logging.warning(
                    '{}: attempt {}/{} raised an exception: {}'.format(
                        context, attempt, attempts, e))

            if picture is not None:
                return picture

            if attempt < attempts:
                logging.warning(
                    '{}: attempt {}/{} returned no picture, retrying'.format(
                        context, attempt, attempts))
                time.sleep(RETRY_DELAY_SECONDS)

        raise RuntimeError(
            '{}: camera did not return a picture after {} attempt(s)'.format(
                context, attempts))

    def capturePicture(self, state):
        logging.info('capturing picture {}'.format(state.num_picture + 1))

        self.setIdle()
        picture = self._getPictureWithRetry('Capture')

        if isinstance(picture, (bytes, bytearray)) and self._rotation is None:
            # The camera already handed us a JPEG and nothing has to be
            # changed about it, so pass it on as it is. Decoding and
            # re-encoding 11 megapixels here would cost a good part of a
            # second for an identical result.
            byte_data = BytesIO(picture)
        else:
            picture = self._toImage(picture)
            if self._rotation is not None:
                picture = picture.transpose(self._rotation)
            logging.info('Got picture with size: {}'.format(picture.size))
            byte_data = BytesIO()
            picture.save(byte_data, format='jpeg')

        self._pictures.append(byte_data)
        self.setActive()

        if self._is_keep_pictures:
            self._comm.send(Workers.WORKER,
                            StateMachine.CameraEvent('capture', byte_data))

        if state.num_picture < self._pic_dims.totalNumPictures:
            self._comm.send(Workers.MASTER,
                            StateMachine.CameraEvent('countdown'))
        else:
            self._comm.send(Workers.MASTER,
                            StateMachine.CameraEvent('assemble'))

    def assemblePicture(self):

        self.setIdle()

        thumb_size = self._pic_dims.thumbnailSize

        picture = self._template.copy()
        for i in range(self._pic_dims.totalNumPictures):
            shot = Image.open(self._pictures[i])
            # Let libjpeg decode at a reduced scale right away when the shot
            # is larger than the thumbnail. It only steps down in powers of
            # two, so a resize is still needed afterwards - but on far fewer
            # pixels.
            shot.draft('RGB', thumb_size)
            resized = shot if shot.size == thumb_size else shot.resize(thumb_size)
            picture.paste(resized, self._pic_dims.thumbnailOffset[i])

        byte_data = BytesIO()
        picture.save(byte_data, format='jpeg')
        self._comm.send(Workers.MASTER,
                        StateMachine.CameraEvent('review', byte_data))
        self._pictures = []
