import glob
from os.path import dirname, basename, isfile


def plugins():
    modules = glob.glob(dirname(__file__) + '/*.py')
    return [basename(f)[:-3] for f in modules if isfile(f)]
