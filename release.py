"""
Running this script will generate Wheels for the aml-backend django app and its
dependencies

setuptools, wheel, and django libraries must be installed in the current python
environment before running this script

NOTE: It's not yet clear whether we want to install a Wheel for the aml_backend
application itself, or if it will be better to install wheels for all of the
dependencies, then use the source of aml_backend for running the app.

Installing aml_backend as a wheel will place it in <python_env>/lib/Python3.4.3/site-packages/,
which might not be as convenient as running from source.

After running this script, the application can be deployed "from source"
by doing:

tar -xzf <release tarball>
pip install --no-index --find-links=release/wheelhouse -r requirements.txt
gunicorn aml.wsgi ... (from the release directory referencing the local aml package)

Alternatively, the wheel for the application can be installed in the python
env and the source is no longer needed:

tar -xzf <release tarball>
pip install --no-index --find-links=release/wheelhouse aml_backend==1.0
gunicorn aml.wsgi ... (aml.wsgi is installed in site-packages, so it can be run
    from anywhere)

One problem with the latter method is that it will only include the python
packages (no static files, test data, etc). Theoretically we should be able
to modify setup.py and specify those things in data_files, but that has not
yet worked out
"""
import argparse
import datetime
import glob
import os
import re
import shutil
from subprocess import call
from aml import version

PACKAGE = 'aml_backend'


def get_date_time():
    """
    Get current date/time string
    """
    return datetime.datetime.now().strftime('%m_%d_%Y-%H-%M')


def cleanup():
    """
    Remove build directories
    """
    shutil.rmtree("wheel", ignore_errors=True)
    shutil.rmtree("wheelhouse", ignore_errors=True)
    shutil.rmtree("dist", ignore_errors=True)
    shutil.rmtree("build", ignore_errors=True)
    shutil.rmtree("release", ignore_errors=True)
    shutil.rmtree("{0!s}.egg-info".format(PACKAGE), ignore_errors=True)


def create_release_dir():
    """
    Creates a directory for the release and moves files there
    """
    os.mkdir("release")
    shutil.copytree("wheelhouse", "release/wheelhouse")
    shutil.copytree("docs", "release/docs")
    shutil.copytree("aml", "release/aml")
    shutil.copytree("amlcenter", "release/amlcenter")
    shutil.copytree("static", "release/static")
    shutil.copytree("plugins", "release/plugins")
    shutil.copy("manage.py", "release")
    shutil.copy("README.md", "release")
    shutil.copy("requirements.prod.txt", "release/requirements.txt")
    shutil.copy("Makefile", "release")
    shutil.copy("CHANGELOG.md", "release")


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', dest='version', action='store_true',
                        help='Use the version number in the file output')
    parser.add_argument('--no-version', dest='version', action='store_false',
                        help='Use the current date/time in the file output')
    parser.set_defaults(version=False)
    args = parser.parse_args()

    # clean up previous builds
    cleanup()

    # collect static files
    call("mkdir -p static", shell=True)
    call("python manage.py collectstatic --noinput", shell=True)
    # make directory for wheelhouse
    call("mkdir -p wheelhouse", shell=True)

    # build wheel for aml_backend - creates wheel in dist/
    call("python setup.py bdist_wheel", shell=True)

    # build/collect wheels for dependencies (this will put wheels in
    # wheelhouse/)
    call("pip wheel -r requirements.prod.txt --wheel-dir wheelhouse", shell=True)

    # add our wheel to the wheelhouse
    for file in glob.glob(r'dist/*.whl'):
        shutil.copy(file, "wheelhouse")

    # hack for it to work on deployment machine
    # call("cp wheelhouse/coverage-4.4.1-cp34-cp34m-manylinux1_x86_64.whl wheelhouse/coverage-4.4.1-py2.py3-none-any.whl", shell=True)
    call("cp wheelhouse/Pillow-4.2.1-cp34-cp34m-manylinux1_x86_64.whl wheelhouse/Pillow-4.2.1-cp34-cp34m-linux_x86_64.whl", shell=True)
    call("cp wheelhouse/psycopg2-2.7.3.1-cp34-cp34m-manylinux1_x86_64.whl wheelhouse/psycopg2-2.7.3.1-cp34-cp34m-linux_x86_64.whl", shell=True)
    # create release directory including the wheelhouse (dependencies) and the
    # relevant source for aml_backend
    create_release_dir()

    # tar everything up
    if args.version:
        call("tar -czf {0!s}-{1!s}.tar.gz release".format('aml-backend', version),
             shell=True)
    else:
        date = get_date_time()
        call("tar -czf {0!s}-{1!s}.tar.gz release".format('aml-backend', date),
             shell=True)

    # cleanup build dirs
    cleanup()


if __name__ == "__main__":
    run()
