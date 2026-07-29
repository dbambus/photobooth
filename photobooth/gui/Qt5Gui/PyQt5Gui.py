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
import os
import io
import time

from qtpy import QtCore
from qtpy import QtGui
from qtpy import QtWidgets
from qtpy.QtGui import QImage, QPixmap

__QTMULTIMEDIAIMPORTED__ = False
try:
    from qtpy import QtMultimedia

    __QTMULTIMEDIAIMPORTED__ = True
except ImportError:
    __QTMULTIMEDIAIMPORTED__ = False

from PIL import Image, ImageQt

from ...StateMachine import GuiEvent, TeardownEvent
from ...Threading import Workers

from ..GuiSkeleton import GuiSkeleton
from ..GuiPostprocessor import GuiPostprocessor

from . import styles
from . import Frames
from . import Receiver
from . import Worker


class PyQt5Gui(GuiSkeleton):
    def __init__(self, argv, config, comm):
        super().__init__(comm)

        self._cfg = config

        self._initUI(argv)
        self._initReceiver()
        self._initWorker()

        self._picture = None
        self._postprocess = GuiPostprocessor(self._cfg)

        self._is_gif_enabled = self._cfg.getBool("GIF", "enable")
        self._audio = AudioHelper(self._cfg)

        # Measured durations of the last few shots, used to size the progress
        # bar shown while waiting for the camera.
        self._capture_durations = []
        self._capture_started = None

    def run(self):
        exit_code = self._app.exec()
        self._gui = None
        return exit_code

    def _initUI(self, argv):
        self._disableTrigger()

        # Load stylesheet
        style = self._cfg.get("Gui", "style")
        filename = next((file for name, file in styles if name == style), None)
        if filename is None:
            default_name, filename = styles[0]
            logging.warning(
                'Unknown style "{}" in config, falling back to "{}"'.format(
                    style, default_name
                )
            )
        with open(os.path.join(os.path.dirname(__file__), filename), "r") as f:
            stylesheet = f.read()

        # Create application and main window
        self._app = QtWidgets.QApplication(argv)
        self._app.setStyleSheet(stylesheet)
        self._gui = PyQt5MainWindow(self._cfg, self._handleKeypressEvent)

        # Load additional fonts
        fonts = [
            "photobooth/gui/Qt5Gui/fonts/AmaticSC-Regular.ttf",
            "photobooth/gui/Qt5Gui/fonts/AmaticSC-Bold.ttf",
        ]
        # QFontDatabase's methods are static since Qt6; PyQt5 accepts the
        # same call without instantiating the class.
        for font in fonts:
            QtGui.QFontDatabase.addApplicationFont(font)

    def _initReceiver(self):
        # Create receiver thread
        self._receiver = Receiver.Receiver(self._comm)
        self._receiver.notify.connect(self.handleState)
        self._receiver.start()

    def _initWorker(self):
        # Create worker thread for time consuming tasks to keep gui responsive
        self._worker = Worker.Worker(self._comm)
        self._worker.start()

    def _enableEscape(self):
        self._is_escape = True

    def _disableEscape(self):
        self._is_escape = False

    def _enableTrigger(self):
        self._is_trigger = True

    def _disableTrigger(self):
        self._is_trigger = False

    # Duration of the cross fade between screens
    FADE_MS = 220
    # Duration of the shutter flash
    FLASH_MS = 170

    def _setWidget(self, widget, fade=True):
        if not fade or self._gui.centralWidget() is None:
            self._gui.setCentralWidget(widget)
            return

        effect = QtWidgets.QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        self._gui.setCentralWidget(widget)

        anim = QtCore.QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(self.FADE_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
        # Drop the effect once it has served its purpose: it would otherwise
        # route every later repaint through an offscreen buffer, which is
        # wasted work on screens that redraw continuously.
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

    def _flash(self):
        """Brief white flash, echoing the camera's shutter."""
        overlay = QtWidgets.QWidget(self._gui)
        overlay.setObjectName("FlashOverlay")
        overlay.setStyleSheet("background-color: #ffffff;")
        overlay.setGeometry(self._gui.rect())
        overlay.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        effect = QtWidgets.QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        overlay.show()
        overlay.raise_()

        anim = QtCore.QPropertyAnimation(effect, b"opacity", overlay)
        anim.setDuration(self.FLASH_MS)
        anim.setStartValue(0.85)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
        anim.finished.connect(overlay.deleteLater)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

    def close(self):
        if self._gui.close():
            self._comm.send(Workers.MASTER, TeardownEvent(TeardownEvent.EXIT))

    def teardown(self, state):
        if state.target == TeardownEvent.WELCOME:
            self._comm.send(Workers.MASTER, GuiEvent("welcome"))
        elif state.target in (TeardownEvent.EXIT, TeardownEvent.RESTART):
            self._worker.put(None)
            self._app.exit(0)

    def showError(self, state):
        logging.error("%s: %s", state.origin, state.message)

        err_msg = self._cfg.get("Photobooth", "overwrite_error_message")
        if len(err_msg) > 0:
            message = err_msg
        else:
            message = "Error: " + state.message

        reply = QtWidgets.QMessageBox.critical(
            self._gui,
            state.origin,
            message,
            QtWidgets.QMessageBox.StandardButton.Retry
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )

        if reply == QtWidgets.QMessageBox.StandardButton.Retry:
            self._comm.send(Workers.MASTER, GuiEvent("retry"))
        else:
            self._comm.send(Workers.MASTER, GuiEvent("abort"))
            
    def get_pixmap_from_pil(pil_img):
        """Converts a PIL image to a QPixmap without using PIL.ImageQt"""
        # 1. Convert to RGB to ensure compatibility
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        
        # 2. Save to a byte buffer (RAM)
        byte_array = io.BytesIO()
        pil_img.save(byte_array, format='PNG')
    
        # 3. Load into Qt
        q_image = QImage()
        q_image.loadFromData(byte_array.getvalue())
    
        return QPixmap.fromImage(q_image)         

    def showWelcome(self, state):
        self._disableTrigger()
        self._disableEscape()
        self._setWidget(
            Frames.Welcome(
                lambda: self._comm.send(Workers.MASTER, GuiEvent("start")),
                self._showSetDateTime,
                self._showSettings,
                self.close,
            )
        )
        if QtWidgets.QApplication.overrideCursor() != 0:
            QtWidgets.QApplication.restoreOverrideCursor()

    def showStartup(self, state):
        self._disableTrigger()
        self._enableEscape()
        self._setWidget(Frames.WaitMessage(_("Starting the photobooth...")))
        if self._cfg.getBool("Gui", "hide_cursor"):
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BlankCursor)

    def showIdle(self, state):
        self._enableEscape()
        self._enableTrigger()
        if self._is_gif_enabled:
            self._setWidget(
                Frames.IdleMessage(
                    lambda: self._comm.send(Workers.MASTER, GuiEvent("trigger")),
                    lambda: self._comm.send(Workers.MASTER, GuiEvent("triggerVideo")),
                )
            )
        else:
            self._setWidget(
                Frames.IdleMessage(
                    lambda: self._comm.send(Workers.MASTER, GuiEvent("trigger"))
                )
            )

    def showGreeter(self, state):
        self._enableEscape()
        self._disableTrigger()

        num_pic = (
            self._cfg.getInt("Picture", "num_x"),
            self._cfg.getInt("Picture", "num_y"),
        )
        skip = [
            i
            for i in self._cfg.getIntList("Picture", "skip")
            if 1 <= i <= num_pic[0] * num_pic[1]
        ]
        greeter_time = self._cfg.getInt("Photobooth", "greeter_time") * 1000

        self._setWidget(
            Frames.GreeterMessage(
                *num_pic,
                skip,
                lambda: self._comm.send(Workers.MASTER, GuiEvent("countdown")),
                state.gif,
            )
        )
        QtCore.QTimer.singleShot(
            greeter_time, lambda: self._comm.send(Workers.MASTER, GuiEvent("countdown"))
        )

    def showCountdown(self, state):
        # Reached again after a shot when further pictures follow.
        self.noteCaptureFinished()
        countdown_time = self._cfg.getInt("Photobooth", "countdown_time")
        self._setWidget(
            Frames.CountdownMessage(
                countdown_time,
                lambda: self._comm.send(Workers.MASTER, GuiEvent("capture")),
                self._audio,
            ),
            # Follows straight after the button press, so it has to feel
            # immediate - and the countdown repaints constantly anyway.
            fade=False,
        )

    def updateCountdown(self, event):
        pil_picture = Image.open(event.picture)
        
        if pil_picture.mode != "RGB":
            pil_picture = pil_picture.convert("RGB")
            
        buffer = io.BytesIO()
        pil_picture.save(buffer, format="jpeg")
        
        q_image = QImage()
        q_image.loadFromData(buffer.getvalue())
        
        self._gui.centralWidget().picture = q_image
        self._gui.centralWidget().update()

#    def updateCountdown(self, event):
#        picture = Image.open(event.picture)
#        self._gui.centralWidget().picture = ImageQt.imageQt(picture)
#       self._gui.centralWidget().update()

    # Assumed duration of a shot until the first one has been measured.
    DEFAULT_CAPTURE_SECONDS = 2.5
    # Number of recent shots the average is taken over.
    CAPTURE_HISTORY = 5

    def expectedCaptureDuration(self):
        if not self._capture_durations:
            return self.DEFAULT_CAPTURE_SECONDS

        return sum(self._capture_durations) / len(self._capture_durations)

    def noteCaptureFinished(self):
        """Record how long the camera actually took."""
        if self._capture_started is None:
            return

        self._capture_durations.append(time.monotonic() - self._capture_started)
        del self._capture_durations[: -self.CAPTURE_HISTORY]
        self._capture_started = None

        logging.debug(
            "Capture took {:.2f}s, expecting {:.2f}s next time".format(
                self._capture_durations[-1], self.expectedCaptureDuration()
            )
        )

    def showCapture(self, state):
        num_pic = (
            self._cfg.getInt("Picture", "num_x"),
            self._cfg.getInt("Picture", "num_y"),
        )
        skip = [
            i
            for i in self._cfg.getIntList("Picture", "skip")
            if 1 <= i and i <= num_pic[0] * num_pic[1]
        ]
        self._capture_started = time.monotonic()
        self._setWidget(
            Frames.CaptureMessage(
                state.num_picture,
                *num_pic,
                skip,
                state.gif,
                self.expectedCaptureDuration()
            ),
            fade=False,
        )
        self._flash()

    def showAssemble(self, state):
        self.noteCaptureFinished()
        self._setWidget(Frames.WaitMessage(_("Processing picture...")))

    def _pil_to_qimage(self, path):
        """Helper to safely convert a file path to a QImage via PIL"""
        with Image.open(path) as pil_img:
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            
            byte_array = io.BytesIO()
            pil_img.save(byte_array, format='jpeg')
            
            q_img = QImage()
            q_img.loadFromData(byte_array.getvalue())
            return q_img

    def showReview(self, state):
        # Convert the picture once at the start
        self._picture = self._pil_to_qimage(state.picture)
        review_time = self._cfg.getInt("Photobooth", "display_time") * 1000

        if state.gif:
            self._setWidget(Frames.GIFMessage(state.picture))
            QtCore.QTimer.singleShot(
                review_time,
                lambda: self._comm.send(Workers.MASTER, GuiEvent("postprocess")),
            )
            self._postprocess.do(self._picture, gif=True)
        else:
            self._setWidget(Frames.PictureMessage(self._picture))
            QtCore.QTimer.singleShot(
                review_time,
                lambda: self._comm.send(Workers.MASTER, GuiEvent("postprocess")),
            )
            self._postprocess.do(self._picture)

#    def showReview(self, state):
#        if state.gif:
#            review_time = self._cfg.getInt("Photobooth", "display_time") * 1000
#            self._setWidget(Frames.GIFMessage(state.picture))
#            QtCore.QTimer.singleShot(
#                review_time,
#                lambda: self._comm.send(Workers.MASTER, GuiEvent("postprocess")),
#            )
#            picture = Image.open(state.picture)
#            self._picture = ImageQt.imageQt(picture)
#            self._postprocess.do(self._picture, gif=True)
#        else:
#           picture = Image.open(state.picture)
#            self._picture = ImageQt.imageQt(picture)
#            review_time = self._cfg.getInt("Photobooth", "display_time") * 1000
#            self._setWidget(Frames.PictureMessage(self._picture))
#            QtCore.QTimer.singleShot(
#                review_time,
#                lambda: self._comm.send(Workers.MASTER, GuiEvent("postprocess")),
#            )
#            self._postprocess.do(self._picture)

    def showPostprocess(self, state):
        tasks = self._postprocess.get(self._picture, state.gif)

        if not tasks:
            # Nothing to confirm - e.g. the printer is disabled - so there
            # is nothing to show here.
            self._comm.send(Workers.MASTER, GuiEvent("idle"))
            return

        postproc_t = self._cfg.getInt("Photobooth", "postprocess_time")

        Frames.PostprocessMessage(
            self._gui.centralWidget(),
            tasks,
            self._worker,
            lambda: self._comm.send(Workers.MASTER, GuiEvent("idle")),
            postproc_t * 1000,
        )

    def _handleKeypressEvent(self, event):
        if self._is_escape and event.key() == QtCore.Qt.Key.Key_Escape:
            self._comm.send(Workers.MASTER, TeardownEvent(TeardownEvent.WELCOME))
        elif self._is_trigger and event.key() == QtCore.Qt.Key.Key_Space:
            self._comm.send(Workers.MASTER, GuiEvent("trigger"))
        elif self._is_trigger and event.key() == QtCore.Qt.Key.Key_B:
            self._comm.send(Workers.MASTER, GuiEvent("triggerVideo"))

    def _showSetDateTime(self):
        self._disableTrigger()
        self._disableEscape()
        self._setWidget(
            Frames.SetDateTime(
                self.showWelcome,
                lambda: self._comm.send(
                    Workers.MASTER, TeardownEvent(TeardownEvent.RESTART)
                ),
            )
        )

    def _showSettings(self):
        self._disableTrigger()
        self._disableEscape()
        self._setWidget(
            Frames.Settings(
                self._cfg,
                self._showSettings,
                self.showWelcome,
                lambda: self._comm.send(
                    Workers.MASTER, TeardownEvent(TeardownEvent.RESTART)
                ),
            )
        )


class PyQt5MainWindow(QtWidgets.QMainWindow):
    def __init__(self, config, keypress_handler):
        super().__init__()

        self._cfg = config
        self._handle_key = keypress_handler
        self._initUI()

    def _initUI(self):
        self.setWindowTitle("Photobooth")

        if self._cfg.getBool("Gui", "fullscreen"):
            self.showFullScreen()
        else:
            self.setFixedSize(
                self._cfg.getInt("Gui", "width"), self._cfg.getInt("Gui", "height")
            )
            self.show()

    def closeEvent(self, e):
        reply = QtWidgets.QMessageBox.question(
            self,
            _("Confirmation"),
            _("Quit Photobooth?"),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            e.accept()
        else:
            e.ignore()

    def keyPressEvent(self, event):
        self._handle_key(event)


class AudioHelper(object):
    def __init__(self, config, *args, **kwargs):
        self._cfg = config
        self._do_play_audio = self._cfg.getBool("Audio", "enable")
        if self._do_play_audio and not __QTMULTIMEDIAIMPORTED__:
            logging.error(
                "Requested to play audio but QtMultimedia not installed in namespace. Disabling audio."
            )
            self._do_play_audio = False

        if self._do_play_audio:
            logging.info("Enabling countdown sounds")
            self.audio_beep = QtMultimedia.QSoundEffect()
            self.audio_shutter = QtMultimedia.QSoundEffect()
            url_beep = QtCore.QUrl.fromLocalFile(self._cfg.get("Audio", "beep_wav"))
            self.audio_beep.setSource(url_beep)
            logging.info(f'Set countdown sound file: "{url_beep.path()}"')
            url_shutter = QtCore.QUrl.fromLocalFile(
                self._cfg.get("Audio", "shutter_wav")
            )
            self.audio_shutter.setSource(url_shutter)
            logging.info(f'Set shutter sound file: "{url_shutter.path()}"')
            # play only once
            loop_count = 0
            self.audio_beep.setLoopCount(loop_count)
            self.audio_shutter.setLoopCount(loop_count)
            # set volume
            volume = self._cfg.getFloat("Audio", "volume")
            self.audio_beep.setVolume(volume)
            self.audio_shutter.setVolume(volume)
            logging.info(f"Audio volume set to: {volume}")

    @property
    def do_play_audio(self):
        return self._do_play_audio

    def beep(self):
        if self._do_play_audio:
            self.audio_beep.play()

    def shutter(self):
        if self._do_play_audio:
            self.audio_shutter.play()
