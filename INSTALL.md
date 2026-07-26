# Installation instructions

These instructions are tailored towards running the photobooth on a Raspberry Pi (tested on 1B+ and 3B+).
However, I use my standard Ubuntu Laptop (18.04) with the built-in webcam and OpenCV for development and as such, the app should work on any other hardware just as well.
Simply skip the Raspberry Pi specific installation parts.

## Install Raspbian and configure it

This is just for my own reference and maybe useful, if you have a similar hardware setup.
Skip this, if you have your hardware already up and running.

### Install Raspbian Desktop
Choose Raspbian Desktop instead of the Lite flavor, which lacks some packages required for the GUI.

Download and installation instructions are available at the [Raspberry Pi website](https://www.raspberrypi.org/documentation/installation/installing-images/)

### Configure and update Raspbian
Boot up the Raspberry Pi for the first time and open a terminal (press Ctrl+Alt+T).
Enter the following to update everything to the latest version:

```bash
sudo rpi-update
sudo apt update
sudo apt dist-upgrade
```

Afterwards, open the configuration utility to adapt everything to your needs (e.g., setup WiFi, hostname, etc.)
```bash
sudo rpi-config
```

### Disable screensaver/screen blanking
By default, Raspbian blanks the screen after ten minutes of idle time.
You probably do not want that for a photobooth, thus it is best to disable this.

For that, edit  `/etc/lightdm/lightdm.conf` and change the startup command to the following:
```
xserver-command=X -s 0 -dpms
```

### Configure touch screen, printer etc.
Configure any not working hardware, e.g., my touch screen needs some additional steps since some of the latest Raspbian releases.
See the instructions at the end for my hardware setup.

If you plan on using a printer, make sure it is configured as default printer!


## Install dependencies for the photobooth

These dependencies are required to run the application.
You might be able to skip some packages if you plan on not using gphoto2.

### Install required packages
In a terminal, enter the following commands
```bash
sudo apt install python3-dev python3-pip virtualenv
sudo apt install python3-pyqt6 python3-pyqt6.qtmultimedia # for the GUI
sudo apt install gphoto2 libgphoto2-dev # to use gphoto2
sudo apt install libcups2-dev # to use pycups
```

On systems without PyQt6 packages (e.g. older Raspberry Pi OS releases), install
`python3-pyqt5` and `python3-pyqt5.qtmultimedia` instead - the GUI code runs
under either binding via [qtpy](https://github.com/spyder-ide/qtpy). Use the
`pyqt5` extra below rather than `pyqt` in that case.

If you want to use the gphoto2-cffi bindings you have to install the following packages:
```bash
sudo apt install libffi6 libffi-dev # for gphoto2-cffi bindings
```

### Remove some files to get gphoto2 working
Raspbian ships with a utility called `gvfs` to allow mounting cameras as virtual file systems.
This enables you to access some camera models as if they were USB storage drives, however, it interferes with our use of the camera, as the operating system then claims exclusive access to the camera.
Thus, we have to disable these functionalities.

*Note: This might break file manager access etc. for some camera models.*

To remove these files, enter the following in a terminal:
```bash
sudo rm /usr/share/dbus-1/services/org.gtk.vfs.GPhoto2VolumeMonitor.service
sudo rm /usr/share/gvfs/mounts/gphoto2.mount
sudo rm /usr/share/gvfs/remote-volume-monitors/gphoto2.mount
sudo rm /usr/lib/gvfs/gvfs-gphoto2-volume-monitor
sudo rm /usr/lib/gvfs/gvfsd-gphoto2
```

You should reboot afterwards to make sure these changes are effective.

## Install photobooth

These are the steps to install the application.

### Clone the Photobooth repository
Run the following command to obtain the source code:
```bash
git clone https://github.com/reuterbal/photobooth.git
```
This will create a folder `photobooth` with all necessary files.

### Initialize `virtualenv`
To avoid installing everything on a system level, I recommend to initialize a virtual environment.
For that, enter the folder created in the previous step
```bash
cd photobooth
```
and run the following command
```bash
virtualenv -p python3 --system-site-packages .venv
```
Activate the virtual environment.
You have to do this whenever you open a new terminal or rebooted your hardware
```bash
source .venv/bin/activate
```

#### Alternative: `uv`

[uv](https://docs.astral.sh/uv/) resolves and installs considerably faster and
pins the Python version explicitly, which avoids surprises on a rolling system.
Instead of the two commands above, run
```bash
uv venv --python 3.13
```
`uv` fetches a matching interpreter if the system does not provide one.
Activation works the same way, and `uv pip install` replaces `pip install` in
the next step. `autostart.sh` calls `.venv/bin/python` directly, so it works
with either variant.

### Install photobooth with dependencies
Run the following command to download and install all dependencies and the photobooth:
```bash
pip install -e .
```

Some dependencies are optional and must be included explicitly if you plan on using them.
For that, change the above command to (note the lack of a whitespace after the dot)
```bash
pip install -e .[extras]
```
and replace `extras` by a comma separated list (without whitespaces!) of the desired options.
These include:
- `pyqt` if you want to install PyQt6 from PIP (doesn't work on Raspbian)
- `pyqt5` for PyQt5 instead, on systems without PyQt6 wheels
- `picamera` if you want to use the Raspberry Pi camera module
- `gphoto2-cffi` if you want to use the `gphoto2-cffi` bindings
- `raw` if your camera writes RAW files without an accompanying JPEG, so they
  have to be developed on the fly (not needed for the usual RAW+JPEG setup)

## Run Photobooth
If not yet done, activate your virtual environment
```bash
source .venv/bin/activate
```
and run the photobooth as
```bash
python -m photobooth
```

Alternatively, use the Python binary of the virtual environment to start the photobooth directly without activating the environment first:
```bash
.venv/bin/python -m photobooth
```
This is useful, e.g., when starting the photobooth from scripts, desktop shortcuts, or when using an autostart mechanism of your window manager.

Change any settings via the "Settings" menu.
Afterwards, select "Start photobooth" to get started.
You can trigger the countdown via space bar or an external button.

To exit the application, use the Esc-key or an external button.

You can directly startup the photobooth to the idle screen (skipping the welcome screen) by appending the parameter `--run`.
