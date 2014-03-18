oslist = []

class OS(object):

    def __init__(self, parent):
        self.parent = parent
        self.password = None
        self.viridian = False
        self.__installMethod = None

    def findPassword(self):
        """Try some passwords to determine which to use"""
        return

    @property
    def installMethod(self):
        return self.__installMethod

    @installMethod.setter
    def installMethod(self, value):
        assert value in self.supportedInstallMethods
        self.__installMethod = value
        

    @staticmethod
    def KnownDistro(distro):
        return False

def RegisterOS(os):
    oslist.append(os)

def OSFactory(distro, parent):
    for o in oslist:
        if o.KnownDistro(distro):
            return o(distro, parent)
    raise xenrt.XRTError("No class found for distro %s" % distro)

__all__ = ["OS", "RegisterOS"]

from xenrt.lib.opsys.linux import *
from xenrt.lib.opsys.debian import *
from xenrt.lib.opsys.windows import *
